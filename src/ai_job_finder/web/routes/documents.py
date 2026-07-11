from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Request, Response, status
from fastapi.responses import RedirectResponse
from pydantic import ValidationError
from starlette.datastructures import UploadFile as StarletteUploadFile

from ai_job_finder.api.dependencies import career_fact_extractor_dependency
from ai_job_finder.api.v1.schemas import CareerFactProposalUpdateRequest
from ai_job_finder.application.document_services import (
    accept_career_fact_proposal,
    edit_career_fact_proposal,
    extract_document_text,
    get_career_fact_proposal,
    get_source_document,
    list_career_fact_proposals,
    list_source_documents,
    merge_career_fact_proposal,
    reject_career_fact_proposal,
    start_extraction_run,
    upload_source_document,
)
from ai_job_finder.application.services import (
    get_primary_candidate_profile,
    list_career_facts,
)
from ai_job_finder.domain.enums import (
    CareerFactCategory,
    CareerFactProposalReviewStatus,
    EvidenceTag,
    SourceDocumentType,
)
from ai_job_finder.domain.errors import DomainError
from ai_job_finder.infrastructure.storage import LocalDocumentStorage
from ai_job_finder.settings import get_settings
from ai_job_finder.web.dependencies import (
    DbSession,
    optional_str,
    render_template,
    split_multivalue,
)

router = APIRouter(tags=["web"])


def _storage() -> LocalDocumentStorage:
    return LocalDocumentStorage(get_settings().local_document_storage_dir)


def _validation_errors(exc: ValidationError) -> dict[str, str]:
    errors: dict[str, str] = {}
    for error in exc.errors():
        location = error.get("loc", [])
        if location:
            errors.setdefault(str(location[-1]), error["msg"])
    return errors


def _proposal_values(proposal: Any) -> dict[str, Any]:
    return {
        "proposed_category": proposal.proposed_category,
        "proposed_source_organization": proposal.proposed_source_organization or "",
        "proposed_statement": proposal.proposed_statement,
        "proposed_metric": proposal.proposed_metric or "",
        "proposed_technologies": "\n".join(proposal.proposed_technologies),
        "proposed_leadership_scope": proposal.proposed_leadership_scope or "",
        "proposed_business_outcome": proposal.proposed_business_outcome or "",
        "proposed_approved_wording": proposal.proposed_approved_wording or "",
        "proposed_evidence_tags": list(proposal.proposed_evidence_tags),
        "supporting_excerpt": proposal.supporting_excerpt,
        "source_location": proposal.source_location or "",
        "confidence": str(proposal.confidence),
    }


def _proposal_context(
    session: DbSession,
    proposal_id: UUID,
    *,
    errors: dict[str, str] | None = None,
    action_error: str | None = None,
    flash: str | None = None,
) -> dict[str, Any]:
    proposal = get_career_fact_proposal(session, proposal_id)
    facts = list_career_facts(session, proposal.candidate_profile_id, include_archived=False)
    return {
        "page_title": "Fact Proposal Review",
        "proposal": proposal,
        "facts": facts,
        "form_values": _proposal_values(proposal),
        "form_errors": errors or {},
        "action_error": action_error,
        "category_options": list(CareerFactCategory),
        "evidence_tag_options": list(EvidenceTag),
        "flash_messages": _flash_messages(flash),
    }


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


@router.get("/fact-proposals")
def proposals_list(
    request: Request,
    session: DbSession,
    review_status: str | None = None,
    document_id: UUID | None = None,
    category: str | None = None,
    source_organization: str | None = None,
    evidence_tag: str | None = None,
) -> Response:
    candidate = get_primary_candidate_profile(session)
    if candidate is None:
        return RedirectResponse(url="/candidate", status_code=status.HTTP_303_SEE_OTHER)
    selected_status = None
    selected_category = None
    selected_tag = None
    if review_status:
        try:
            selected_status = CareerFactProposalReviewStatus(review_status)
        except ValueError:
            selected_status = None
    if category:
        try:
            selected_category = CareerFactCategory(category)
        except ValueError:
            selected_category = None
    if evidence_tag:
        try:
            selected_tag = EvidenceTag(evidence_tag)
        except ValueError:
            selected_tag = None
    proposals = list_career_fact_proposals(
        session,
        candidate_profile_id=candidate.id,
        review_status=selected_status.value if selected_status else None,
        document_id=document_id,
        category=selected_category.value if selected_category else None,
        source_organization=optional_str(source_organization),
        evidence_tag=selected_tag.value if selected_tag else None,
    )
    documents = list_source_documents(session, candidate.id)
    organizations = sorted(
        {
            proposal.proposed_source_organization
            for proposal in proposals
            if proposal.proposed_source_organization
        }
    )
    return render_template(
        request,
        "proposals/list.html",
        {
            "page_title": "Fact Proposals",
            "proposals": proposals,
            "documents": documents,
            "review_status_options": list(CareerFactProposalReviewStatus),
            "category_options": list(CareerFactCategory),
            "evidence_tag_options": list(EvidenceTag),
            "organization_options": organizations,
            "selected_filters": {
                "review_status": selected_status.value if selected_status else "",
                "document_id": str(document_id) if document_id else "",
                "category": selected_category.value if selected_category else "",
                "source_organization": optional_str(source_organization) or "",
                "evidence_tag": selected_tag.value if selected_tag else "",
            },
        },
    )


@router.get("/fact-proposals/{proposal_id}")
def proposal_detail(
    request: Request,
    proposal_id: UUID,
    session: DbSession,
    flash: str | None = None,
) -> Response:
    return render_template(
        request,
        "proposals/detail.html",
        _proposal_context(session, proposal_id, flash=flash),
    )


@router.post("/fact-proposals/{proposal_id}")
async def proposal_update(request: Request, proposal_id: UUID, session: DbSession) -> Response:
    form = await request.form()
    values: dict[str, Any] = {
        "proposed_category": str(form.get("proposed_category", "")),
        "proposed_source_organization": str(form.get("proposed_source_organization", "")),
        "proposed_statement": str(form.get("proposed_statement", "")),
        "proposed_metric": str(form.get("proposed_metric", "")),
        "proposed_technologies": str(form.get("proposed_technologies", "")),
        "proposed_leadership_scope": str(form.get("proposed_leadership_scope", "")),
        "proposed_business_outcome": str(form.get("proposed_business_outcome", "")),
        "proposed_approved_wording": str(form.get("proposed_approved_wording", "")),
        "proposed_evidence_tags": [str(value) for value in form.getlist("proposed_evidence_tags")],
        "supporting_excerpt": str(form.get("supporting_excerpt", "")),
        "source_location": str(form.get("source_location", "")),
        "confidence": str(form.get("confidence", "")),
    }
    try:
        payload = CareerFactProposalUpdateRequest.model_validate(
            {
                **values,
                "proposed_source_organization": optional_str(
                    values["proposed_source_organization"]
                ),
                "proposed_metric": optional_str(values["proposed_metric"]),
                "proposed_technologies": split_multivalue(values["proposed_technologies"]),
                "proposed_leadership_scope": optional_str(values["proposed_leadership_scope"]),
                "proposed_business_outcome": optional_str(values["proposed_business_outcome"]),
                "proposed_approved_wording": optional_str(values["proposed_approved_wording"]),
                "source_location": optional_str(values["source_location"]),
            }
        )
    except ValidationError as exc:
        context = _proposal_context(session, proposal_id, errors=_validation_errors(exc))
        context["form_values"] = values
        return render_template(request, "proposals/detail.html", context, status_code=422)
    try:
        edit_career_fact_proposal(
            session,
            proposal_id=proposal_id,
            category=payload.proposed_category.value,
            source_organization=payload.proposed_source_organization,
            statement=payload.proposed_statement,
            metric=payload.proposed_metric,
            technologies=payload.proposed_technologies,
            leadership_scope=payload.proposed_leadership_scope,
            business_outcome=payload.proposed_business_outcome,
            approved_wording=payload.proposed_approved_wording,
            evidence_tags=[tag.value for tag in payload.proposed_evidence_tags],
            supporting_excerpt=payload.supporting_excerpt,
            source_location=payload.source_location,
            confidence=payload.confidence,
        )
    except DomainError as exc:
        context = _proposal_context(session, proposal_id, action_error=str(exc))
        context["form_values"] = values
        return render_template(
            request,
            "proposals/detail.html",
            context,
            status_code=_domain_error_status(exc),
        )
    return RedirectResponse(
        url=f"/fact-proposals/{proposal_id}?flash=proposal-updated",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.post("/fact-proposals/{proposal_id}/accept")
def proposal_accept(request: Request, proposal_id: UUID, session: DbSession) -> Response:
    try:
        accept_career_fact_proposal(session, proposal_id=proposal_id)
    except DomainError as exc:
        return render_template(
            request,
            "proposals/detail.html",
            _proposal_context(session, proposal_id, action_error=str(exc)),
            status_code=409,
        )
    return RedirectResponse(
        url=f"/fact-proposals/{proposal_id}?flash=proposal-accepted",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.post("/fact-proposals/{proposal_id}/reject")
def proposal_reject(request: Request, proposal_id: UUID, session: DbSession) -> Response:
    try:
        reject_career_fact_proposal(session, proposal_id=proposal_id)
    except DomainError as exc:
        return render_template(
            request,
            "proposals/detail.html",
            _proposal_context(session, proposal_id, action_error=str(exc)),
            status_code=409,
        )
    return RedirectResponse(
        url=f"/fact-proposals/{proposal_id}?flash=proposal-rejected",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.post("/fact-proposals/{proposal_id}/merge")
async def proposal_merge(request: Request, proposal_id: UUID, session: DbSession) -> Response:
    form = await request.form()
    try:
        merge_career_fact_proposal(
            session,
            proposal_id=proposal_id,
            target_fact_id=UUID(str(form.get("target_fact_id", ""))),
            replace_statement=str(form.get("replace_statement", "")) == "on",
            replace_approved_wording=str(form.get("replace_approved_wording", "")) == "on",
        )
    except (DomainError, ValueError) as exc:
        return render_template(
            request,
            "proposals/detail.html",
            _proposal_context(session, proposal_id, action_error=str(exc)),
            status_code=409,
        )
    return RedirectResponse(
        url=f"/fact-proposals/{proposal_id}?flash=proposal-merged",
        status_code=status.HTTP_303_SEE_OTHER,
    )
