from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from ai_job_finder.api.dependencies import (
    career_fact_extractor_dependency,
    db_session_dependency,
    document_storage_dependency,
    settings_dependency,
)
from ai_job_finder.api.v1.schemas import (
    CandidateProfileCreateRequest,
    CandidateProfileResponse,
    CandidateProfileUpdateRequest,
    CandidateSliceResetResponse,
    CareerFactCreateRequest,
    CareerFactProposalMergeRequest,
    CareerFactProposalResponse,
    CareerFactProposalUpdateRequest,
    CareerFactResponse,
    CareerFactTransitionRequest,
    CareerFactUpdateRequest,
    ExtractionRunResponse,
    HealthResponse,
    JobEvaluationCreateRequest,
    JobEvaluationResponse,
    JobLeadCreateRequest,
    JobLeadResponse,
    JobLeadStatusPatchRequest,
    JobLeadUpdateRequest,
    SourceDocumentResponse,
)
from ai_job_finder.application.document_services import (
    accept_career_fact_proposal,
    edit_career_fact_proposal,
    extract_document_text,
    get_career_fact_proposal,
    get_source_document,
    list_career_fact_proposals,
    list_extraction_runs,
    list_source_documents,
    merge_career_fact_proposal,
    reject_career_fact_proposal,
    rerun_failed_extraction,
    start_extraction_run,
    upload_source_document,
)
from ai_job_finder.application.extraction import CareerFactExtractor
from ai_job_finder.application.services import (
    create_candidate_profile,
    create_career_fact,
    create_job_evaluation,
    create_job_lead,
    find_job_leads,
    get_career_fact,
    get_current_candidate_profile,
    get_job_lead,
    get_latest_job_evaluation,
    list_career_facts,
    list_job_evaluations,
    reset_current_candidate_profile,
    transition_career_fact,
    update_candidate_profile,
    update_career_fact,
    update_job_lead,
    update_job_lead_status,
)
from ai_job_finder.domain.enums import (
    CareerFactCategory,
    CareerFactLifecycle,
    CareerFactProposalReviewStatus,
    EvidenceTag,
    SourceDocumentType,
)
from ai_job_finder.domain.errors import NotFoundError
from ai_job_finder.infrastructure.storage import DocumentStorage
from ai_job_finder.settings import Settings, get_settings

router = APIRouter(prefix="/api/v1")
DbSession = Annotated[Session, Depends(db_session_dependency)]
DocumentStorageDependency = Annotated[DocumentStorage, Depends(document_storage_dependency)]
SettingsDependency = Annotated[Settings, Depends(settings_dependency)]
ExtractorDependency = Annotated[CareerFactExtractor, Depends(career_fact_extractor_dependency)]


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(status="ok")


@router.post(
    "/candidate-profile",
    response_model=CandidateProfileResponse,
    status_code=status.HTTP_201_CREATED,
)
def post_candidate_profile(
    payload: CandidateProfileCreateRequest, session: DbSession
) -> CandidateProfileResponse:
    candidate = create_candidate_profile(
        session,
        full_name=payload.full_name,
        preferred_locations=payload.preferred_locations,
        remote_preference=payload.remote_preference.value,
        target_levels=payload.target_levels,
        target_functions=payload.target_functions,
    )
    return CandidateProfileResponse.model_validate(candidate)


@router.get("/candidate-profile", response_model=CandidateProfileResponse)
def get_current_candidate_profile_route(session: DbSession) -> CandidateProfileResponse:
    candidate = get_current_candidate_profile(session)
    if candidate is None:
        raise NotFoundError("No active candidate profile exists.")
    return CandidateProfileResponse.model_validate(candidate)


@router.put("/candidate-profile", response_model=CandidateProfileResponse)
def put_candidate_profile(
    payload: CandidateProfileUpdateRequest,
    session: DbSession,
) -> CandidateProfileResponse:
    candidate = get_current_candidate_profile(session)
    if candidate is None:
        raise NotFoundError("No active candidate profile exists.")
    candidate = update_candidate_profile(
        session,
        candidate_profile_id=candidate.id,
        full_name=payload.full_name,
        preferred_locations=payload.preferred_locations,
        remote_preference=payload.remote_preference.value,
        target_levels=payload.target_levels,
        target_functions=payload.target_functions,
    )
    return CandidateProfileResponse.model_validate(candidate)


@router.post(
    "/dev/reset-candidate-profile",
    response_model=CandidateSliceResetResponse,
)
def post_reset_candidate_profile(session: DbSession) -> CandidateSliceResetResponse:
    if not get_settings().enable_dev_reset_api:
        raise HTTPException(status_code=404, detail="Not found")
    return CandidateSliceResetResponse(candidate_deleted=reset_current_candidate_profile(session))


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


@router.get("/fact-proposals", response_model=list[CareerFactProposalResponse])
def get_fact_proposals(
    session: DbSession,
    review_status: CareerFactProposalReviewStatus | None = None,
    document_id: UUID | None = None,
    category: CareerFactCategory | None = None,
    source_organization: str | None = None,
    evidence_tag: EvidenceTag | None = None,
) -> list[CareerFactProposalResponse]:
    candidate = get_current_candidate_profile(session)
    if candidate is None:
        raise NotFoundError("No active candidate profile exists.")
    proposals = list_career_fact_proposals(
        session,
        candidate_profile_id=candidate.id,
        review_status=review_status.value if review_status else None,
        document_id=document_id,
        category=category.value if category else None,
        source_organization=source_organization,
        evidence_tag=evidence_tag.value if evidence_tag else None,
    )
    return [CareerFactProposalResponse.model_validate(proposal) for proposal in proposals]


@router.get("/fact-proposals/{proposal_id}", response_model=CareerFactProposalResponse)
def get_fact_proposal_route(proposal_id: UUID, session: DbSession) -> CareerFactProposalResponse:
    return CareerFactProposalResponse.model_validate(get_career_fact_proposal(session, proposal_id))


@router.put("/fact-proposals/{proposal_id}", response_model=CareerFactProposalResponse)
def put_fact_proposal(
    proposal_id: UUID,
    payload: CareerFactProposalUpdateRequest,
    session: DbSession,
) -> CareerFactProposalResponse:
    proposal = edit_career_fact_proposal(
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
    return CareerFactProposalResponse.model_validate(proposal)


@router.post("/fact-proposals/{proposal_id}/accept", response_model=CareerFactProposalResponse)
def post_fact_proposal_accept(
    proposal_id: UUID,
    session: DbSession,
) -> CareerFactProposalResponse:
    return CareerFactProposalResponse.model_validate(
        accept_career_fact_proposal(session, proposal_id=proposal_id)
    )


@router.post("/fact-proposals/{proposal_id}/reject", response_model=CareerFactProposalResponse)
def post_fact_proposal_reject(
    proposal_id: UUID,
    session: DbSession,
) -> CareerFactProposalResponse:
    return CareerFactProposalResponse.model_validate(
        reject_career_fact_proposal(session, proposal_id=proposal_id)
    )


@router.post("/fact-proposals/{proposal_id}/merge", response_model=CareerFactProposalResponse)
def post_fact_proposal_merge(
    proposal_id: UUID,
    payload: CareerFactProposalMergeRequest,
    session: DbSession,
) -> CareerFactProposalResponse:
    proposal = merge_career_fact_proposal(
        session,
        proposal_id=proposal_id,
        target_fact_id=payload.target_fact_id,
        replace_statement=payload.replace_statement,
        replace_approved_wording=payload.replace_approved_wording,
    )
    return CareerFactProposalResponse.model_validate(proposal)


@router.post(
    "/career-facts",
    response_model=CareerFactResponse,
    status_code=status.HTTP_201_CREATED,
)
def post_career_fact(
    payload: CareerFactCreateRequest,
    session: DbSession,
) -> CareerFactResponse:
    candidate = get_current_candidate_profile(session)
    if candidate is None:
        raise NotFoundError("No active candidate profile exists.")
    fact = create_career_fact(
        session,
        candidate_profile_id=candidate.id,
        category=payload.category.value,
        source_organization=payload.source_organization,
        statement=payload.statement,
        metric=payload.metric,
        technologies=payload.technologies,
        leadership_scope=payload.leadership_scope,
        business_outcome=payload.business_outcome,
        approved_wording=payload.approved_wording,
        evidence_tags=[tag.value for tag in payload.evidence_tags],
        provenance_type=payload.provenance_type.value,
        source_reference=payload.source_reference,
    )
    return CareerFactResponse.model_validate(fact)


@router.get(
    "/career-facts",
    response_model=list[CareerFactResponse],
)
def get_career_facts(
    session: DbSession,
    lifecycle_status: CareerFactLifecycle | None = None,
    category: CareerFactCategory | None = None,
    source_organization: str | None = None,
    evidence_tag: EvidenceTag | None = None,
    include_archived: bool = False,
) -> list[CareerFactResponse]:
    candidate = get_current_candidate_profile(session)
    if candidate is None:
        raise NotFoundError("No active candidate profile exists.")
    return [
        CareerFactResponse.model_validate(fact)
        for fact in list_career_facts(
            session,
            candidate.id,
            lifecycle_status=lifecycle_status.value if lifecycle_status else None,
            category=category.value if category else None,
            source_organization=source_organization,
            evidence_tag=evidence_tag.value if evidence_tag else None,
            include_archived=include_archived,
        )
    ]


@router.get("/career-facts/{fact_id}", response_model=CareerFactResponse)
def get_career_fact_route(fact_id: UUID, session: DbSession) -> CareerFactResponse:
    return CareerFactResponse.model_validate(get_career_fact(session, fact_id))


@router.put("/career-facts/{fact_id}", response_model=CareerFactResponse)
def put_career_fact(
    fact_id: UUID,
    payload: CareerFactUpdateRequest,
    session: DbSession,
) -> CareerFactResponse:
    fact = update_career_fact(
        session,
        fact_id=fact_id,
        category=payload.category.value,
        source_organization=payload.source_organization,
        statement=payload.statement,
        metric=payload.metric,
        technologies=payload.technologies,
        leadership_scope=payload.leadership_scope,
        business_outcome=payload.business_outcome,
        approved_wording=payload.approved_wording,
        evidence_tags=[tag.value for tag in payload.evidence_tags],
        provenance_type=payload.provenance_type.value,
        source_reference=payload.source_reference,
    )
    return CareerFactResponse.model_validate(fact)


@router.post("/career-facts/{fact_id}/transitions", response_model=CareerFactResponse)
def post_career_fact_transition(
    fact_id: UUID,
    payload: CareerFactTransitionRequest,
    session: DbSession,
) -> CareerFactResponse:
    fact = transition_career_fact(
        session,
        fact_id=fact_id,
        lifecycle_status=payload.lifecycle_status.value,
    )
    return CareerFactResponse.model_validate(fact)


@router.post("/job-leads", response_model=JobLeadResponse, status_code=status.HTTP_201_CREATED)
def post_job_lead(payload: JobLeadCreateRequest, session: DbSession) -> JobLeadResponse:
    job_lead = create_job_lead(
        session,
        source=payload.source.value,
        source_url=payload.source_url,
        external_id=payload.external_id,
        company_name=payload.company_name,
        title=payload.title,
        location_text=payload.location_text,
        workplace_type=payload.workplace_type.value if payload.workplace_type else None,
        description_raw=payload.description_raw,
        description_normalized=payload.description_normalized,
        compensation_text=payload.compensation_text,
    )
    return JobLeadResponse.model_validate(job_lead)


@router.get("/job-leads", response_model=list[JobLeadResponse])
def get_job_leads(
    session: DbSession,
    posting_status: str | None = None,
    source: str | None = None,
    external_id: str | None = None,
) -> list[JobLeadResponse]:
    return [
        JobLeadResponse.model_validate(job_lead)
        for job_lead in find_job_leads(
            session,
            posting_status=posting_status,
            source=source,
            external_id=external_id,
        )
    ]


@router.get("/job-leads/{job_lead_id}", response_model=JobLeadResponse)
def get_job_lead_route(job_lead_id: UUID, session: DbSession) -> JobLeadResponse:
    return JobLeadResponse.model_validate(get_job_lead(session, job_lead_id))


@router.put("/job-leads/{job_lead_id}", response_model=JobLeadResponse)
def put_job_lead(
    job_lead_id: UUID,
    payload: JobLeadUpdateRequest,
    session: DbSession,
) -> JobLeadResponse:
    job_lead = update_job_lead(
        session,
        job_lead_id=job_lead_id,
        source_url=payload.source_url,
        company_name=payload.company_name,
        title=payload.title,
        location_text=payload.location_text,
        workplace_type=payload.workplace_type.value if payload.workplace_type else None,
        description_raw=payload.description_raw,
        description_normalized=payload.description_normalized,
        compensation_text=payload.compensation_text,
    )
    return JobLeadResponse.model_validate(job_lead)


@router.patch("/job-leads/{job_lead_id}/status", response_model=JobLeadResponse)
def patch_job_lead_status(
    job_lead_id: UUID,
    payload: JobLeadStatusPatchRequest,
    session: DbSession,
) -> JobLeadResponse:
    job_lead = update_job_lead_status(session, job_lead_id, payload.posting_status.value)
    return JobLeadResponse.model_validate(job_lead)


@router.post(
    "/job-leads/{job_lead_id}/evaluations",
    response_model=JobEvaluationResponse,
    status_code=status.HTTP_201_CREATED,
)
def post_job_evaluation(
    job_lead_id: UUID,
    payload: JobEvaluationCreateRequest,
    session: DbSession,
) -> JobEvaluationResponse:
    evaluation = create_job_evaluation(
        session,
        job_lead_id=job_lead_id,
        candidate_profile_id=payload.candidate_profile_id,
    )
    return JobEvaluationResponse.model_validate(evaluation)


@router.get("/job-leads/{job_lead_id}/evaluations/latest", response_model=JobEvaluationResponse)
def get_latest_evaluation(job_lead_id: UUID, session: DbSession) -> JobEvaluationResponse:
    return JobEvaluationResponse.model_validate(get_latest_job_evaluation(session, job_lead_id))


@router.get(
    "/job-leads/{job_lead_id}/evaluations",
    response_model=list[JobEvaluationResponse],
)
def get_job_evaluations(job_lead_id: UUID, session: DbSession) -> list[JobEvaluationResponse]:
    return [
        JobEvaluationResponse.model_validate(evaluation)
        for evaluation in list_job_evaluations(session, job_lead_id)
    ]
