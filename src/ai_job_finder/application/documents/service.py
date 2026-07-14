from __future__ import annotations

import hashlib
import logging
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from ai_job_finder.application.documents._common import _normalize_optional_str, _validate_upload
from ai_job_finder.domain.common import new_uuid, utc_now
from ai_job_finder.domain.enums import SourceDocumentExtractionStatus, SourceDocumentType
from ai_job_finder.domain.errors import DuplicateSourceDocumentError, NotFoundError
from ai_job_finder.infrastructure.database.models import SourceDocumentModel
from ai_job_finder.infrastructure.storage import DocumentStorage

logger = logging.getLogger(__name__)


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
