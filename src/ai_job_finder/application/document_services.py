from __future__ import annotations

import hashlib
import logging
import re
import time
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from ai_job_finder.application.extraction import (
    CareerFactExtractor,
    ExtractedCareerFactProposal,
    ExtractedDocument,
    chunk_extracted_document,
    excerpt_is_grounded,
    normalize_text_for_matching,
    proposal_fingerprint,
)
from ai_job_finder.domain.common import new_uuid, utc_now
from ai_job_finder.domain.document_ingestion import ensure_valid_proposal_transition
from ai_job_finder.domain.enums import (
    CareerFactLifecycle,
    CareerFactProposalReviewStatus,
    ExtractionRunStatus,
    ProvenanceType,
    SourceDocumentExtractionStatus,
    SourceDocumentType,
)
from ai_job_finder.domain.errors import (
    DocumentExtractionLimitError,
    DocumentTooLargeError,
    DuplicateSourceDocumentError,
    ExtractionProviderUnavailableError,
    InvalidProposalEditError,
    InvalidProposalTransitionError,
    MalformedExtractionOutputError,
    MergeTargetMismatchError,
    NotFoundError,
    UnsupportedDocumentTypeError,
)
from ai_job_finder.infrastructure.database.models import (
    CareerFactModel,
    CareerFactProposalModel,
    ExtractionRunModel,
    SourceDocumentModel,
)
from ai_job_finder.infrastructure.storage import DocumentStorage
from ai_job_finder.infrastructure.text_extraction import extract_text_from_document

logger = logging.getLogger(__name__)

SUPPORTED_UPLOADS = {
    ".txt": {"text/plain"},
    ".pdf": {"application/pdf"},
}


def _normalize_list(values: list[str]) -> list[str]:
    normalized: list[str] = []
    for value in values:
        item = value.strip()
        if item and item not in normalized:
            normalized.append(item)
    return normalized


def _normalize_optional_str(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    return normalized or None


def _extension(filename: str) -> str:
    return f".{filename.rsplit('.', maxsplit=1)[-1].lower()}" if "." in filename else ""


def _validate_upload(filename: str, content_type: str, content: bytes, max_size: int) -> None:
    extension = _extension(filename)
    if extension not in SUPPORTED_UPLOADS or content_type not in SUPPORTED_UPLOADS[extension]:
        msg = "Only UTF-8 .txt and embedded-text .pdf uploads are supported."
        raise UnsupportedDocumentTypeError(msg)
    if len(content) > max_size:
        msg = f"Uploaded document exceeds the configured {max_size} byte limit."
        raise DocumentTooLargeError(msg)


def _source_type_to_provenance(source_type: str) -> str:
    if source_type == SourceDocumentType.RESUME.value:
        return ProvenanceType.RESUME.value
    if source_type == SourceDocumentType.PERFORMANCE_REVIEW.value:
        return ProvenanceType.PERFORMANCE_REVIEW.value
    if source_type == SourceDocumentType.PROJECT_NOTES.value:
        return ProvenanceType.PROJECT_NOTES.value
    if source_type == SourceDocumentType.CAREER_NOTES.value:
        return ProvenanceType.PERSONAL_RECOLLECTION.value
    return ProvenanceType.OTHER.value


def _token_set(value: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", normalize_text_for_matching(value)))


def _jaccard(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


def _find_duplicate_fact(
    session: Session,
    *,
    candidate_profile_id: UUID,
    proposal: ExtractedCareerFactProposal,
) -> UUID | None:
    facts = list(
        session.scalars(
            select(CareerFactModel).where(
                CareerFactModel.candidate_profile_id == candidate_profile_id
            )
        )
    )
    proposal_statement_tokens = _token_set(proposal.statement)
    proposal_technologies = {normalize_text_for_matching(item) for item in proposal.technologies}
    proposal_tags = {tag.value for tag in proposal.evidence_tags}
    proposal_metric = normalize_text_for_matching(proposal.metric or "")
    proposal_organization = normalize_text_for_matching(proposal.source_organization or "")
    for fact in facts:
        statement_similarity = _jaccard(proposal_statement_tokens, _token_set(fact.statement))
        same_category = fact.category == proposal.category.value
        fact_organization = normalize_text_for_matching(fact.source_organization or "")
        same_organization = (
            bool(proposal_organization) and proposal_organization == fact_organization
        )
        metric_overlap = bool(proposal_metric) and proposal_metric == normalize_text_for_matching(
            fact.metric or ""
        )
        fact_technologies = {normalize_text_for_matching(item) for item in fact.technologies}
        technology_overlap = bool(proposal_technologies & fact_technologies)
        tag_overlap = bool(proposal_tags & set(fact.evidence_tags))
        score = sum(
            [
                statement_similarity >= 0.72,
                same_category,
                same_organization,
                metric_overlap,
                technology_overlap,
                tag_overlap,
            ]
        )
        if score >= 4 or (statement_similarity >= 0.88 and same_category):
            return fact.id
    return None


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


def upload_source_document(
    session: Session,
    storage: DocumentStorage,
    *,
    candidate_profile_id: UUID,
    original_filename: str,
    content_type: str,
    content: bytes,
    source_type: str,
    max_upload_size_bytes: int,
    upload_note: str | None = None,
) -> SourceDocumentModel:
    SourceDocumentType(source_type)
    _validate_upload(original_filename, content_type, content, max_upload_size_bytes)
    checksum = hashlib.sha256(content).hexdigest()
    duplicate = session.scalar(
        select(SourceDocumentModel).where(
            SourceDocumentModel.candidate_profile_id == candidate_profile_id,
            SourceDocumentModel.checksum_sha256 == checksum,
        )
    )
    if duplicate is not None:
        msg = f"Document duplicates existing upload {duplicate.id}."
        raise DuplicateSourceDocumentError(msg)
    document_id = new_uuid()
    storage_key = storage.save(
        candidate_profile_id=candidate_profile_id,
        document_id=document_id,
        original_filename=original_filename,
        content=content,
    )
    now = utc_now()
    document = SourceDocumentModel(
        id=document_id,
        candidate_profile_id=candidate_profile_id,
        original_filename=original_filename,
        content_type=content_type,
        byte_size=len(content),
        checksum_sha256=checksum,
        source_type=source_type,
        storage_key=storage_key,
        extraction_status=SourceDocumentExtractionStatus.UPLOADED.value,
        upload_note=_normalize_optional_str(upload_note),
        uploaded_at=now,
        created_at=now,
        updated_at=now,
    )
    session.add(document)
    try:
        session.commit()
    except Exception:
        session.rollback()
        try:
            storage.delete(storage_key)
        except Exception:
            logger.exception(
                "failed to clean up stored document after upload persistence "
                "failure document_id=%s",
                document_id,
            )
        raise
    session.refresh(document)
    return document


def list_source_documents(
    session: Session, candidate_profile_id: UUID
) -> list[SourceDocumentModel]:
    return list(
        session.scalars(
            select(SourceDocumentModel)
            .where(SourceDocumentModel.candidate_profile_id == candidate_profile_id)
            .options(
                selectinload(SourceDocumentModel.extraction_runs),
                selectinload(SourceDocumentModel.proposals),
            )
            .order_by(
                SourceDocumentModel.uploaded_at.desc(),
                SourceDocumentModel.created_at.desc(),
            )
        )
    )


def get_source_document(session: Session, document_id: UUID) -> SourceDocumentModel:
    document = session.scalar(
        select(SourceDocumentModel)
        .where(SourceDocumentModel.id == document_id)
        .options(
            selectinload(SourceDocumentModel.extraction_runs),
            selectinload(SourceDocumentModel.proposals),
        )
    )
    if document is None:
        msg = f"Source document {document_id} was not found."
        raise NotFoundError(msg)
    return document


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


def _create_proposal_model(
    *,
    document: SourceDocumentModel,
    run: ExtractionRunModel,
    proposal: ExtractedCareerFactProposal,
    duplicate_fact_id: UUID | None,
) -> CareerFactProposalModel:
    now = utc_now()
    return CareerFactProposalModel(
        id=new_uuid(),
        source_document_id=document.id,
        extraction_run_id=run.id,
        candidate_profile_id=document.candidate_profile_id,
        proposed_category=proposal.category.value,
        proposed_source_organization=_normalize_optional_str(proposal.source_organization),
        proposed_statement=proposal.statement.strip(),
        proposed_metric=_normalize_optional_str(proposal.metric),
        proposed_technologies=_normalize_list(proposal.technologies),
        proposed_leadership_scope=_normalize_optional_str(proposal.leadership_scope),
        proposed_business_outcome=_normalize_optional_str(proposal.business_outcome),
        proposed_approved_wording=_normalize_optional_str(proposal.approved_wording),
        proposed_evidence_tags=_normalize_list([tag.value for tag in proposal.evidence_tags]),
        supporting_excerpt=proposal.supporting_excerpt.strip(),
        source_location=_normalize_optional_str(proposal.source_location),
        confidence=proposal.confidence,
        review_status=CareerFactProposalReviewStatus.PENDING.value,
        duplicate_candidate_fact_id=duplicate_fact_id,
        created_at=now,
        updated_at=now,
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
    proposals: list[ExtractedCareerFactProposal] = []
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
            duplicate_fact_id = _find_duplicate_fact(
                session,
                candidate_profile_id=document.candidate_profile_id,
                proposal=proposal,
            )
            session.add(
                _create_proposal_model(
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


def list_career_fact_proposals(
    session: Session,
    *,
    candidate_profile_id: UUID,
    review_status: str | None = None,
    document_id: UUID | None = None,
    category: str | None = None,
    source_organization: str | None = None,
    evidence_tag: str | None = None,
) -> list[CareerFactProposalModel]:
    query = select(CareerFactProposalModel).where(
        CareerFactProposalModel.candidate_profile_id == candidate_profile_id
    )
    if review_status is not None:
        query = query.where(CareerFactProposalModel.review_status == review_status)
    if document_id is not None:
        query = query.where(CareerFactProposalModel.source_document_id == document_id)
    if category is not None:
        query = query.where(CareerFactProposalModel.proposed_category == category)
    if source_organization is not None:
        query = query.where(
            CareerFactProposalModel.proposed_source_organization == source_organization
        )
    proposals = list(
        session.scalars(
            query.options(selectinload(CareerFactProposalModel.source_document)).order_by(
                CareerFactProposalModel.review_status.asc(),
                CareerFactProposalModel.created_at.desc(),
            )
        )
    )
    if evidence_tag is not None:
        proposals = [
            proposal for proposal in proposals if evidence_tag in proposal.proposed_evidence_tags
        ]
    return proposals


def get_career_fact_proposal(session: Session, proposal_id: UUID) -> CareerFactProposalModel:
    proposal = session.scalar(
        select(CareerFactProposalModel)
        .where(CareerFactProposalModel.id == proposal_id)
        .options(selectinload(CareerFactProposalModel.source_document))
    )
    if proposal is None:
        msg = f"Career fact proposal {proposal_id} was not found."
        raise NotFoundError(msg)
    return proposal


def edit_career_fact_proposal(
    session: Session,
    *,
    proposal_id: UUID,
    category: str,
    source_organization: str | None,
    statement: str,
    metric: str | None,
    technologies: list[str],
    leadership_scope: str | None,
    business_outcome: str | None,
    approved_wording: str | None,
    evidence_tags: list[str],
    supporting_excerpt: str,
    source_location: str | None,
    confidence: float,
) -> CareerFactProposalModel:
    proposal = get_career_fact_proposal(session, proposal_id)
    if proposal.review_status != CareerFactProposalReviewStatus.PENDING.value:
        msg = "Reviewed proposals are immutable except for audit metadata."
        raise InvalidProposalTransitionError(msg)
    if proposal.supporting_excerpt != supporting_excerpt.strip():
        msg = "Supporting excerpt is immutable after extraction."
        raise InvalidProposalEditError(msg)
    proposal.proposed_category = category
    proposal.proposed_source_organization = _normalize_optional_str(source_organization)
    proposal.proposed_statement = statement.strip()
    proposal.proposed_metric = _normalize_optional_str(metric)
    proposal.proposed_technologies = _normalize_list(technologies)
    proposal.proposed_leadership_scope = _normalize_optional_str(leadership_scope)
    proposal.proposed_business_outcome = _normalize_optional_str(business_outcome)
    proposal.proposed_approved_wording = _normalize_optional_str(approved_wording)
    proposal.proposed_evidence_tags = _normalize_list(evidence_tags)
    proposal.source_location = _normalize_optional_str(source_location)
    proposal.confidence = confidence
    proposal.updated_at = utc_now()
    session.add(proposal)
    session.commit()
    session.refresh(proposal)
    return proposal


def accept_career_fact_proposal(session: Session, *, proposal_id: UUID) -> CareerFactProposalModel:
    proposal = get_career_fact_proposal(session, proposal_id)
    ensure_valid_proposal_transition(
        CareerFactProposalReviewStatus(proposal.review_status),
        CareerFactProposalReviewStatus.ACCEPTED,
    )
    fact = CareerFactModel(
        id=new_uuid(),
        candidate_profile_id=proposal.candidate_profile_id,
        category=proposal.proposed_category,
        source_organization=proposal.proposed_source_organization,
        statement=proposal.proposed_statement,
        metric=proposal.proposed_metric,
        technologies=list(proposal.proposed_technologies),
        leadership_scope=proposal.proposed_leadership_scope,
        business_outcome=proposal.proposed_business_outcome,
        approved_wording=proposal.proposed_approved_wording or proposal.proposed_statement,
        lifecycle_status=CareerFactLifecycle.DRAFT.value,
        evidence_tags=list(proposal.proposed_evidence_tags),
        provenance_type=_source_type_to_provenance(proposal.source_document.source_type),
        source_reference=f"source_document:{proposal.source_document_id} proposal:{proposal.id}",
        verified_at=None,
        archived_at=None,
        created_at=utc_now(),
        updated_at=utc_now(),
    )
    proposal.review_status = CareerFactProposalReviewStatus.ACCEPTED.value
    proposal.accepted_career_fact_id = fact.id
    proposal.reviewed_at = utc_now()
    session.add_all([fact, proposal])
    session.commit()
    session.refresh(proposal)
    return proposal


def reject_career_fact_proposal(session: Session, *, proposal_id: UUID) -> CareerFactProposalModel:
    proposal = get_career_fact_proposal(session, proposal_id)
    ensure_valid_proposal_transition(
        CareerFactProposalReviewStatus(proposal.review_status),
        CareerFactProposalReviewStatus.REJECTED,
    )
    proposal.review_status = CareerFactProposalReviewStatus.REJECTED.value
    proposal.reviewed_at = utc_now()
    session.add(proposal)
    session.commit()
    session.refresh(proposal)
    return proposal


def merge_career_fact_proposal(
    session: Session,
    *,
    proposal_id: UUID,
    target_fact_id: UUID,
    replace_statement: bool = False,
    replace_approved_wording: bool = False,
) -> CareerFactProposalModel:
    proposal = get_career_fact_proposal(session, proposal_id)
    ensure_valid_proposal_transition(
        CareerFactProposalReviewStatus(proposal.review_status),
        CareerFactProposalReviewStatus.MERGED,
    )
    fact = session.get(CareerFactModel, target_fact_id)
    if fact is None:
        msg = f"Career fact {target_fact_id} was not found."
        raise NotFoundError(msg)
    if fact.candidate_profile_id != proposal.candidate_profile_id:
        msg = "Merge target belongs to a different candidate profile."
        raise MergeTargetMismatchError(msg)
    fact.technologies = _normalize_list([*fact.technologies, *proposal.proposed_technologies])
    fact.evidence_tags = _normalize_list([*fact.evidence_tags, *proposal.proposed_evidence_tags])
    if fact.metric is None:
        fact.metric = proposal.proposed_metric
    if fact.leadership_scope is None:
        fact.leadership_scope = proposal.proposed_leadership_scope
    if fact.business_outcome is None:
        fact.business_outcome = proposal.proposed_business_outcome
    if replace_statement:
        fact.statement = proposal.proposed_statement
    if replace_approved_wording and proposal.proposed_approved_wording:
        fact.approved_wording = proposal.proposed_approved_wording
    if fact.lifecycle_status == CareerFactLifecycle.VERIFIED.value:
        fact.lifecycle_status = CareerFactLifecycle.DRAFT.value
        fact.verified_at = None
        fact.archived_at = None
    fact.updated_at = utc_now()
    proposal.review_status = CareerFactProposalReviewStatus.MERGED.value
    proposal.accepted_career_fact_id = fact.id
    proposal.reviewed_at = utc_now()
    session.add_all([fact, proposal])
    session.commit()
    session.refresh(proposal)
    return proposal
