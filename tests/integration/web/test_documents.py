from __future__ import annotations

from datetime import datetime
from uuid import UUID

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from ai_job_finder.application.services import create_candidate_profile
from ai_job_finder.domain.common import new_uuid, utc_now
from ai_job_finder.domain.enums import (
    CareerFactCategory,
    CareerFactProposalReviewStatus,
    ExtractionRunStatus,
    RemotePreference,
    SourceDocumentType,
)
from ai_job_finder.infrastructure.database.models import (
    CareerFactProposalModel,
    ExtractionRunModel,
    SourceDocumentModel,
)


def _seed_proposal_queue(session: Session) -> tuple[UUID, UUID, dict[str, UUID]]:
    candidate = create_candidate_profile(
        session,
        full_name="Jordan Lee",
        preferred_locations=["Remote"],
        remote_preference=RemotePreference.FLEXIBLE.value,
        target_levels=["director"],
        target_functions=["platform engineering"],
    )
    now = utc_now()
    first_document = SourceDocumentModel(
        id=new_uuid(),
        candidate_profile_id=candidate.id,
        original_filename="resume.txt",
        content_type="text/plain",
        byte_size=10,
        checksum_sha256="a" * 64,
        source_type=SourceDocumentType.RESUME.value,
        storage_key="documents/resume.txt",
        extracted_text="Led platform work.",
        extraction_error=None,
        upload_note=None,
        uploaded_at=now,
        processed_at=now,
        created_at=now,
        updated_at=now,
    )
    second_document = SourceDocumentModel(
        id=new_uuid(),
        candidate_profile_id=candidate.id,
        original_filename="review.txt",
        content_type="text/plain",
        byte_size=10,
        checksum_sha256="b" * 64,
        source_type=SourceDocumentType.PERFORMANCE_REVIEW.value,
        storage_key="documents/review.txt",
        extracted_text="Improved engineering delivery.",
        extraction_error=None,
        upload_note=None,
        uploaded_at=now,
        processed_at=now,
        created_at=now,
        updated_at=now,
    )
    first_run = _extraction_run(first_document.id, now)
    second_run = _extraction_run(second_document.id, now)
    pending = _proposal(
        candidate.id,
        first_document.id,
        first_run.id,
        "Pending resume proposal",
        "Acme",
        CareerFactProposalReviewStatus.PENDING,
        now,
    )
    accepted = _proposal(
        candidate.id,
        first_document.id,
        first_run.id,
        "Accepted resume proposal",
        "Acme",
        CareerFactProposalReviewStatus.ACCEPTED,
        now,
    )
    rejected = _proposal(
        candidate.id,
        second_document.id,
        second_run.id,
        "Rejected review proposal",
        "Northstar",
        CareerFactProposalReviewStatus.REJECTED,
        now,
    )
    pending_rejection = _proposal(
        candidate.id,
        second_document.id,
        second_run.id,
        "Pending review proposal",
        "Northstar",
        CareerFactProposalReviewStatus.PENDING,
        now,
    )
    session.add_all(
        [
            first_document,
            second_document,
            first_run,
            second_run,
            pending,
            accepted,
            rejected,
            pending_rejection,
        ]
    )
    session.commit()
    return (
        first_document.id,
        second_document.id,
        {
            "pending": pending.id,
            "accepted": accepted.id,
            "rejected": rejected.id,
            "pending_rejection": pending_rejection.id,
        },
    )


def _extraction_run(document_id: UUID, now: datetime) -> ExtractionRunModel:
    return ExtractionRunModel(
        id=new_uuid(),
        source_document_id=document_id,
        provider="fake",
        model_id="queue-fixture",
        prompt_version="test",
        schema_version="test",
        status=ExtractionRunStatus.SUCCEEDED.value,
        started_at=now,
        completed_at=now,
        input_character_count=10,
        input_token_count=None,
        output_token_count=None,
        chunk_count=1,
        temperature=0.0,
        raw_response=None,
        error_message=None,
        created_at=now,
    )


def _proposal(
    candidate_id: UUID,
    document_id: UUID,
    run_id: UUID,
    statement: str,
    organization: str,
    review_status: CareerFactProposalReviewStatus,
    now: datetime,
) -> CareerFactProposalModel:
    return CareerFactProposalModel(
        id=new_uuid(),
        source_document_id=document_id,
        extraction_run_id=run_id,
        candidate_profile_id=candidate_id,
        proposed_category=CareerFactCategory.PLATFORM.value,
        proposed_source_organization=organization,
        proposed_statement=statement,
        proposed_metric=None,
        proposed_technologies=[],
        proposed_leadership_scope=None,
        proposed_business_outcome=None,
        proposed_approved_wording=None,
        proposed_evidence_tags=[],
        supporting_excerpt=statement,
        source_location=None,
        confidence=1.0,
        review_status=review_status.value,
        duplicate_candidate_fact_id=None,
        accepted_career_fact_id=None,
        reviewed_at=now if review_status != CareerFactProposalReviewStatus.PENDING else None,
        created_at=now,
        updated_at=now,
    )


def test_fact_proposal_queue_defaults_to_pending_and_preserves_history_filters(
    client: TestClient,
    session_factory: sessionmaker[Session],
) -> None:
    with session_factory() as session:
        first_document_id, second_document_id, _ = _seed_proposal_queue(session)

    default_queue = client.get("/fact-proposals")
    assert default_queue.status_code == 200
    assert "Pending resume proposal" in default_queue.text
    assert "Accepted resume proposal" not in default_queue.text
    assert "Rejected review proposal" not in default_queue.text
    assert 'option value="pending" selected' in default_queue.text

    accepted_history = client.get("/fact-proposals?review_status=accepted")
    assert "Accepted resume proposal" in accepted_history.text
    assert "Pending resume proposal" not in accepted_history.text

    rejected_history = client.get("/fact-proposals?review_status=rejected")
    assert "Rejected review proposal" in rejected_history.text
    assert "Pending resume proposal" not in rejected_history.text

    all_history = client.get("/fact-proposals?review_status=all")
    assert "Pending resume proposal" in all_history.text
    assert "Accepted resume proposal" in all_history.text
    assert "Rejected review proposal" in all_history.text

    document_queue = client.get(f"/fact-proposals?document_id={second_document_id}")
    assert "Pending review proposal" in document_queue.text
    assert "Rejected review proposal" not in document_queue.text
    assert "Pending resume proposal" not in document_queue.text

    source_history = client.get(
        f"/fact-proposals?review_status=all&document_id={first_document_id}&source_organization=Acme"
    )
    assert "Pending resume proposal" in source_history.text
    assert "Accepted resume proposal" in source_history.text
    assert "Rejected review proposal" not in source_history.text


def test_review_actions_return_to_pending_queue_and_preserve_proposals(
    client: TestClient,
    session_factory: sessionmaker[Session],
) -> None:
    with session_factory() as session:
        _first_document_id, _second_document_id, proposal_ids = _seed_proposal_queue(session)

    accepted = client.post(
        f"/fact-proposals/{proposal_ids['pending']}/accept", follow_redirects=False
    )
    assert accepted.status_code == 303
    assert accepted.headers["location"] == "/fact-proposals?flash=proposal-accepted"
    pending_after_accept = client.get(accepted.headers["location"])
    assert "Pending resume proposal" not in pending_after_accept.text
    assert "Accepted resume proposal" not in pending_after_accept.text
    assert "Pending review proposal" in pending_after_accept.text

    rejected = client.post(
        f"/fact-proposals/{proposal_ids['pending_rejection']}/reject", follow_redirects=False
    )
    assert rejected.status_code == 303
    assert rejected.headers["location"] == "/fact-proposals?flash=proposal-rejected"
    pending_after_rejection = client.get(rejected.headers["location"])
    assert "Pending review proposal" not in pending_after_rejection.text

    with session_factory() as session:
        accepted_proposal = session.get(CareerFactProposalModel, proposal_ids["pending"])
        rejected_proposal = session.get(CareerFactProposalModel, proposal_ids["pending_rejection"])
        proposal_count = len(list(session.scalars(select(CareerFactProposalModel))))

    assert accepted_proposal is not None
    assert accepted_proposal.review_status == CareerFactProposalReviewStatus.ACCEPTED.value
    assert accepted_proposal.accepted_career_fact_id is not None
    assert rejected_proposal is not None
    assert rejected_proposal.review_status == CareerFactProposalReviewStatus.REJECTED.value
    assert proposal_count == 4
