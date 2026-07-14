from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Request, Response, status
from fastapi.responses import RedirectResponse
from starlette.datastructures import UploadFile as StarletteUploadFile

from ai_job_finder.api.dependencies import career_fact_extractor_dependency
from ai_job_finder.application.documents import (
    extract_document_text,
    get_source_document,
    list_source_documents,
    start_extraction_run,
    upload_source_document,
)
from ai_job_finder.application.services import (
    get_primary_candidate_profile,
)
from ai_job_finder.domain.enums import (
    SourceDocumentType,
)
from ai_job_finder.domain.errors import DomainError
from ai_job_finder.infrastructure.storage import LocalDocumentStorage
from ai_job_finder.settings import get_settings
from ai_job_finder.web.dependencies import (
    DbSession,
    optional_str,
    render_template,
)

router = APIRouter(tags=["web"])


def _storage() -> LocalDocumentStorage:
    return LocalDocumentStorage(get_settings().local_document_storage_dir)


def _flash_messages(flash: str | None) -> list[dict[str, str]]:
    messages = {
        "document-uploaded": "Document uploaded.",
        "text-extracted": "Document text extracted.",
        "facts-extracted": "Fact proposals extracted.",
        "proposal-updated": "Proposal updated.",
        "proposal-accepted": "Proposal accepted as a draft career fact.",
        "proposal-rejected": "Proposal rejected.",
        "proposal-merged": "Proposal merged into the selected career fact.",
    }
    if flash in messages:
        return [{"level": "success", "message": messages[flash]}]
    return []


def _domain_error_status(exc: DomainError) -> int:
    status_by_code = {
        "unsupported_document_type": 415,
        "document_too_large": 413,
        "duplicate_source_document": 409,
        "document_extraction_failed": 422,
        "document_extraction_limit_exceeded": 422,
        "extraction_provider_unavailable": 503,
        "malformed_extraction_output": 502,
        "invalid_proposal_edit": 422,
        "invalid_proposal_transition": 409,
        "merge_target_mismatch": 409,
    }
    return status_by_code.get(exc.code, 409)


@router.get("/documents")
def documents_list(request: Request, session: DbSession, flash: str | None = None) -> Response:
    candidate = get_primary_candidate_profile(session)
    if candidate is None:
        return RedirectResponse(url="/candidate", status_code=status.HTTP_303_SEE_OTHER)
    documents = list_source_documents(session, candidate.id)
    return render_template(
        request,
        "documents/list.html",
        {
            "page_title": "Source Documents",
            "documents": documents,
            "flash_messages": _flash_messages(flash),
        },
    )


@router.get("/documents/new")
def documents_new(request: Request) -> Response:
    return render_template(
        request,
        "documents/new.html",
        {
            "page_title": "Upload Document",
            "source_type_options": list(SourceDocumentType),
            "form_values": {"source_type": SourceDocumentType.RESUME.value, "upload_note": ""},
            "form_errors": {},
        },
    )


@router.post("/documents")
async def documents_create(request: Request, session: DbSession) -> Response:
    candidate = get_primary_candidate_profile(session)
    if candidate is None:
        return RedirectResponse(url="/candidate", status_code=status.HTTP_303_SEE_OTHER)
    form = await request.form()
    values = {
        "source_type": str(form.get("source_type", "")),
        "upload_note": str(form.get("upload_note", "")),
    }
    document_file = form.get("document_file")
    errors: dict[str, str] = {}
    if not isinstance(document_file, StarletteUploadFile) or not document_file.filename:
        errors["document_file"] = "Choose a document to upload."
    try:
        source_type = SourceDocumentType(values["source_type"])
    except ValueError:
        errors["source_type"] = "Choose a supported source type."
        source_type = SourceDocumentType.OTHER
    if errors:
        return render_template(
            request,
            "documents/new.html",
            {
                "page_title": "Upload Document",
                "source_type_options": list(SourceDocumentType),
                "form_values": values,
                "form_errors": errors,
            },
            status_code=422,
        )
    assert isinstance(document_file, StarletteUploadFile)
    settings = get_settings()
    try:
        document = upload_source_document(
            session,
            _storage(),
            candidate_profile_id=candidate.id,
            original_filename=document_file.filename or "document",
            content_type=document_file.content_type or "application/octet-stream",
            content=await document_file.read(),
            source_type=source_type.value,
            max_upload_size_bytes=settings.max_upload_size_bytes,
            upload_note=optional_str(values["upload_note"]),
        )
    except DomainError as exc:
        errors["document_file"] = str(exc)
        return render_template(
            request,
            "documents/new.html",
            {
                "page_title": "Upload Document",
                "source_type_options": list(SourceDocumentType),
                "form_values": values,
                "form_errors": errors,
            },
            status_code=_domain_error_status(exc),
        )
    return RedirectResponse(
        url=f"/documents/{document.id}?flash=document-uploaded",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.get("/documents/{document_id}")
def documents_detail(
    request: Request,
    document_id: UUID,
    session: DbSession,
    flash: str | None = None,
    action_error: str | None = None,
) -> Response:
    document = get_source_document(session, document_id)
    return render_template(
        request,
        "documents/detail.html",
        {
            "page_title": document.original_filename,
            "document": document,
            "flash_messages": _flash_messages(flash),
            "action_error": action_error,
        },
    )


@router.post("/documents/{document_id}/text-extraction")
def documents_extract_text(request: Request, document_id: UUID, session: DbSession) -> Response:
    settings = get_settings()
    try:
        extract_document_text(
            session,
            _storage(),
            document_id=document_id,
            max_extracted_characters=settings.extraction_max_extracted_characters,
        )
    except DomainError as exc:
        return render_template(
            request,
            "documents/detail.html",
            {
                "page_title": get_source_document(session, document_id).original_filename,
                "document": get_source_document(session, document_id),
                "flash_messages": _flash_messages(None),
                "action_error": str(exc),
            },
            status_code=_domain_error_status(exc),
        )
    return RedirectResponse(
        url=f"/documents/{document_id}?flash=text-extracted",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.post("/documents/{document_id}/extractions")
def documents_extract_facts(request: Request, document_id: UUID, session: DbSession) -> Response:
    settings = get_settings()
    try:
        extractor = career_fact_extractor_dependency(settings)
        start_extraction_run(
            session,
            _storage(),
            extractor,
            document_id=document_id,
            max_extracted_characters=settings.extraction_max_extracted_characters,
            chunk_size=settings.extraction_chunk_size,
            max_chunks=settings.extraction_max_chunks,
        )
    except DomainError as exc:
        return render_template(
            request,
            "documents/detail.html",
            {
                "page_title": get_source_document(session, document_id).original_filename,
                "document": get_source_document(session, document_id),
                "flash_messages": _flash_messages(None),
                "action_error": str(exc),
            },
            status_code=_domain_error_status(exc),
        )
    return RedirectResponse(
        url=f"/documents/{document_id}?flash=facts-extracted",
        status_code=status.HTTP_303_SEE_OTHER,
    )
