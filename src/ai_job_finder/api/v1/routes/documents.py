from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, File, Form, UploadFile, status

from ai_job_finder.api.v1.routes.dependencies import (
    DbSession,
    DocumentStorageDependency,
    ExtractorDependency,
    SettingsDependency,
)
from ai_job_finder.api.v1.schemas import ExtractionRunResponse, SourceDocumentResponse
from ai_job_finder.application.document_services import (
    extract_document_text,
    get_source_document,
    list_extraction_runs,
    list_source_documents,
    rerun_failed_extraction,
    start_extraction_run,
    upload_source_document,
)
from ai_job_finder.application.services import get_current_candidate_profile
from ai_job_finder.domain.enums import SourceDocumentType
from ai_job_finder.domain.errors import NotFoundError

router = APIRouter()


@router.post(
    "/documents",
    response_model=SourceDocumentResponse,
    status_code=status.HTTP_201_CREATED,
)
async def post_source_document(
    session: DbSession,
    storage: DocumentStorageDependency,
    settings: SettingsDependency,
    document_file: Annotated[UploadFile, File()],
    source_type: Annotated[SourceDocumentType, Form()],
    upload_note: Annotated[str | None, Form()] = None,
) -> SourceDocumentResponse:
    candidate = get_current_candidate_profile(session)
    if candidate is None:
        raise NotFoundError("No active candidate profile exists.")
    content = await document_file.read()
    document = upload_source_document(
        session,
        storage,
        candidate_profile_id=candidate.id,
        original_filename=document_file.filename or "document",
        content_type=document_file.content_type or "application/octet-stream",
        content=content,
        source_type=source_type.value,
        max_upload_size_bytes=settings.max_upload_size_bytes,
        upload_note=upload_note,
    )
    return SourceDocumentResponse.model_validate(document)


@router.get("/documents", response_model=list[SourceDocumentResponse])
def get_source_documents(session: DbSession) -> list[SourceDocumentResponse]:
    candidate = get_current_candidate_profile(session)
    if candidate is None:
        raise NotFoundError("No active candidate profile exists.")
    return [
        SourceDocumentResponse.model_validate(document)
        for document in list_source_documents(session, candidate.id)
    ]


@router.get("/documents/{document_id}", response_model=SourceDocumentResponse)
def get_source_document_route(document_id: UUID, session: DbSession) -> SourceDocumentResponse:
    return SourceDocumentResponse.model_validate(get_source_document(session, document_id))


@router.post("/documents/{document_id}/text-extraction", response_model=SourceDocumentResponse)
def post_source_document_text_extraction(
    document_id: UUID,
    session: DbSession,
    storage: DocumentStorageDependency,
    settings: SettingsDependency,
) -> SourceDocumentResponse:
    return SourceDocumentResponse.model_validate(
        extract_document_text(
            session,
            storage,
            document_id=document_id,
            max_extracted_characters=settings.extraction_max_extracted_characters,
        )
    )


@router.post("/documents/{document_id}/extractions", response_model=ExtractionRunResponse)
def post_source_document_extraction(
    document_id: UUID,
    session: DbSession,
    storage: DocumentStorageDependency,
    settings: SettingsDependency,
    extractor: ExtractorDependency,
) -> ExtractionRunResponse:
    run = start_extraction_run(
        session,
        storage,
        extractor,
        document_id=document_id,
        max_extracted_characters=settings.extraction_max_extracted_characters,
        chunk_size=settings.extraction_chunk_size,
        max_chunks=settings.extraction_max_chunks,
    )
    return ExtractionRunResponse.model_validate(run)


@router.post("/documents/{document_id}/extractions/rerun", response_model=ExtractionRunResponse)
def post_source_document_extraction_rerun(
    document_id: UUID,
    session: DbSession,
    storage: DocumentStorageDependency,
    settings: SettingsDependency,
    extractor: ExtractorDependency,
) -> ExtractionRunResponse:
    run = rerun_failed_extraction(
        session,
        storage,
        extractor,
        document_id=document_id,
        max_extracted_characters=settings.extraction_max_extracted_characters,
        chunk_size=settings.extraction_chunk_size,
        max_chunks=settings.extraction_max_chunks,
    )
    return ExtractionRunResponse.model_validate(run)


@router.get("/documents/{document_id}/extraction-runs", response_model=list[ExtractionRunResponse])
def get_source_document_extraction_runs(
    document_id: UUID,
    session: DbSession,
) -> list[ExtractionRunResponse]:
    return [
        ExtractionRunResponse.model_validate(run)
        for run in list_extraction_runs(session, document_id)
    ]


@router.get("/documents/{document_id}/extraction-status", response_model=SourceDocumentResponse)
def get_source_document_extraction_status(
    document_id: UUID,
    session: DbSession,
) -> SourceDocumentResponse:
    return SourceDocumentResponse.model_validate(get_source_document(session, document_id))
