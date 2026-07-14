from __future__ import annotations

import logging
import time
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from ai_job_finder.application.documents import proposals as proposal_services
from ai_job_finder.application.documents.service import get_source_document
from ai_job_finder.application.extraction import (
    CareerFactExtractor,
    ExtractedDocument,
    chunk_extracted_document,
    excerpt_is_grounded,
    proposal_fingerprint,
)
from ai_job_finder.domain.common import new_uuid, utc_now
from ai_job_finder.domain.enums import (
    ExtractionRunStatus,
    SourceDocumentExtractionStatus,
    SourceDocumentType,
)
from ai_job_finder.domain.errors import (
    DocumentExtractionLimitError,
    DocumentTooLargeError,
    ExtractionProviderUnavailableError,
    InvalidProposalTransitionError,
    MalformedExtractionOutputError,
)
from ai_job_finder.infrastructure.database.models import ExtractionRunModel, SourceDocumentModel
from ai_job_finder.infrastructure.storage import DocumentStorage
from ai_job_finder.infrastructure.text_extraction import extract_text_from_document

logger = logging.getLogger(__name__)


def _safe_error_message(exc: Exception) -> str:
    if isinstance(
        exc,
        (
            ExtractionProviderUnavailableError,
            MalformedExtractionOutputError,
            DocumentExtractionLimitError,
        ),
    ):
        message = " ".join(str(exc).split())
        return message[:500] if message else exc.__class__.__name__
    return f"Extraction failed due to an unexpected {exc.__class__.__name__}."


def _persist_failed_extraction_state(
    session: Session,
    *,
    document_id: UUID,
    run_id: UUID,
    error_message: str,
    mark_processed: bool,
) -> None:
    try:
        session.rollback()
        run = session.get(ExtractionRunModel, run_id)
        document = session.get(SourceDocumentModel, document_id)
        failed_at = utc_now()
        if run is not None:
            run.status = ExtractionRunStatus.FAILED.value
            run.completed_at = failed_at
            run.error_message = error_message
            session.add(run)
        if document is not None:
            document.extraction_status = SourceDocumentExtractionStatus.EXTRACTION_FAILED.value
            document.extraction_error = error_message
            if mark_processed:
                document.processed_at = failed_at
            session.add(document)
        session.commit()
    except Exception:
        session.rollback()
        logger.exception(
            "failed to persist extraction failure state document_id=%s run_id=%s",
            document_id,
            run_id,
        )


def extract_document_text(
    session: Session,
    storage: DocumentStorage,
    *,
    document_id: UUID,
    max_extracted_characters: int,
) -> SourceDocumentModel:
    document = get_source_document(session, document_id)
    try:
        extracted = extract_text_from_document(
            filename=document.original_filename,
            content_type=document.content_type,
            content=storage.read(document.storage_key),
        )
    except Exception as exc:
        document.extraction_status = SourceDocumentExtractionStatus.EXTRACTION_FAILED.value
        document.extraction_error = str(exc)
        document.processed_at = utc_now()
        session.add(document)
        session.commit()
        raise
    if len(extracted.text) > max_extracted_characters:
        msg = f"Extracted text exceeds the configured {max_extracted_characters} character limit."
        document.extraction_status = SourceDocumentExtractionStatus.EXTRACTION_FAILED.value
        document.extraction_error = msg
        document.processed_at = utc_now()
        session.add(document)
        session.commit()
        raise DocumentTooLargeError(msg)
    document.extracted_text = extracted.text
    document.extraction_error = None
    document.extraction_status = SourceDocumentExtractionStatus.TEXT_EXTRACTED.value
    document.processed_at = utc_now()
    session.add(document)
    session.commit()
    session.refresh(document)
    return document


def list_extraction_runs(session: Session, document_id: UUID) -> list[ExtractionRunModel]:
    get_source_document(session, document_id)
    return list(
        session.scalars(
            select(ExtractionRunModel)
            .where(ExtractionRunModel.source_document_id == document_id)
            .order_by(ExtractionRunModel.started_at.desc(), ExtractionRunModel.created_at.desc())
        )
    )


def start_extraction_run(
    session: Session,
    storage: DocumentStorage,
    extractor: CareerFactExtractor,
    *,
    document_id: UUID,
    max_extracted_characters: int,
    chunk_size: int,
    max_chunks: int,
) -> ExtractionRunModel:
    document = get_source_document(session, document_id)
    if document.extracted_text is None:
        document = extract_document_text(
            session,
            storage,
            document_id=document.id,
            max_extracted_characters=max_extracted_characters,
        )
    assert document.extracted_text is not None
    chunks = chunk_extracted_document(
        document.extracted_text,
        max_characters=chunk_size,
    )
    total_chunks = len(chunks)
    now = utc_now()
    run = ExtractionRunModel(
        id=new_uuid(),
        source_document_id=document.id,
        provider=extractor.provider,
        model_id=extractor.model_id,
        prompt_version=extractor.prompt_version,
        schema_version=extractor.schema_version,
        status=ExtractionRunStatus.RUNNING.value,
        started_at=now,
        input_character_count=len(document.extracted_text),
        input_token_count=None,
        output_token_count=None,
        chunk_count=total_chunks,
        temperature=extractor.temperature,
        created_at=now,
    )
    session.add(run)
    session.commit()
    session.refresh(run)

    logger.info(
        "extraction run started document_id=%s run_id=%s chunks=%s provider=%s model=%s prompt=%s",
        document.id,
        run.id,
        len(chunks),
        extractor.provider,
        extractor.model_id,
        extractor.prompt_version,
    )
    started = time.monotonic()
    raw_responses: list[str] = []
    input_tokens = 0
    output_tokens = 0
    proposals = []
    seen_fingerprints: set[str] = set()
    try:
        if total_chunks > max_chunks:
            msg = (
                "Document extraction requires "
                f"{total_chunks} chunks, which exceeds the configured limit of {max_chunks}. "
                "Reduce the document size or increase extraction_max_chunks."
            )
            raise DocumentExtractionLimitError(msg)
        for chunk in chunks:
            result = extractor.extract(
                ExtractedDocument(
                    text=chunk.text,
                    source_type=SourceDocumentType(document.source_type),
                    source_location=chunk.source_location,
                )
            )
            if result.raw_response:
                raw_responses.append(result.raw_response)
            if result.input_token_count is not None:
                input_tokens += result.input_token_count
            if result.output_token_count is not None:
                output_tokens += result.output_token_count
            for proposal in result.proposals:
                if not excerpt_is_grounded(document.extracted_text, proposal.supporting_excerpt):
                    msg = (
                        "Model output included a supporting excerpt that was not grounded "
                        "in the document."
                    )
                    raise MalformedExtractionOutputError(msg)
                fingerprint = proposal_fingerprint(proposal)
                if fingerprint in seen_fingerprints:
                    continue
                seen_fingerprints.add(fingerprint)
                proposals.append(proposal)
        for proposal in proposals:
            duplicate_fact_id = proposal_services._find_duplicate_fact(
                session,
                candidate_profile_id=document.candidate_profile_id,
                proposal=proposal,
            )
            session.add(
                proposal_services._create_proposal_model(
                    document=document,
                    run=run,
                    proposal=proposal,
                    duplicate_fact_id=duplicate_fact_id,
                )
            )
        run.status = ExtractionRunStatus.SUCCEEDED.value
        run.completed_at = utc_now()
        run.input_token_count = input_tokens or None
        run.output_token_count = output_tokens or None
        run.raw_response = "\n".join(raw_responses)[:20000] if raw_responses else None
        document.extraction_status = SourceDocumentExtractionStatus.FACTS_EXTRACTED.value
        document.extraction_error = None
        document.processed_at = run.completed_at
        session.add_all([run, document])
        session.commit()
    except (
        ExtractionProviderUnavailableError,
        MalformedExtractionOutputError,
        DocumentExtractionLimitError,
    ) as exc:
        _persist_failed_extraction_state(
            session,
            document_id=document.id,
            run_id=run.id,
            error_message=_safe_error_message(exc),
            mark_processed=True,
        )
        raise
    except Exception as exc:
        _persist_failed_extraction_state(
            session,
            document_id=document.id,
            run_id=run.id,
            error_message=_safe_error_message(exc),
            mark_processed=True,
        )
        raise
    finally:
        logger.info(
            "extraction run ended document_id=%s run_id=%s status=%s elapsed_ms=%s "
            "input_tokens=%s output_tokens=%s",
            document.id,
            run.id,
            run.status,
            int((time.monotonic() - started) * 1000),
            run.input_token_count,
            run.output_token_count,
        )
    session.refresh(run)
    return run


def rerun_failed_extraction(
    session: Session,
    storage: DocumentStorage,
    extractor: CareerFactExtractor,
    *,
    document_id: UUID,
    max_extracted_characters: int,
    chunk_size: int,
    max_chunks: int,
) -> ExtractionRunModel:
    document = get_source_document(session, document_id)
    if document.extraction_status != SourceDocumentExtractionStatus.EXTRACTION_FAILED.value:
        msg = "Only failed document extractions can be rerun with this action."
        raise InvalidProposalTransitionError(msg)
    return start_extraction_run(
        session,
        storage,
        extractor,
        document_id=document_id,
        max_extracted_characters=max_extracted_characters,
        chunk_size=chunk_size,
        max_chunks=max_chunks,
    )
