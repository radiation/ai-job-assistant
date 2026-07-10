from __future__ import annotations

from uuid import UUID

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from ai_job_finder.application.services import (
    create_candidate_profile,
    create_job_lead,
)
from ai_job_finder.domain.common import new_uuid, utc_now
from ai_job_finder.domain.enums import (
    CareerFactCategory,
    JobLeadSource,
    RemotePreference,
    VerificationStatus,
    WorkplaceType,
)
from ai_job_finder.infrastructure.database.models import CareerFactModel


def test_job_lead_uniqueness_constraint(session_factory: sessionmaker[Session]) -> None:
    with session_factory() as session:
        create_job_lead(
            session,
            source=JobLeadSource.MANUAL.value,
            source_url=None,
            external_id="duplicate-id",
            company_name="Example",
            title="Director",
            location_text=None,
            workplace_type=WorkplaceType.REMOTE.value,
            description_raw="raw",
            description_normalized="normalized",
            compensation_text=None,
        )
        with pytest.raises(IntegrityError):
            create_job_lead(
                session,
                source=JobLeadSource.MANUAL.value,
                source_url=None,
                external_id="duplicate-id",
                company_name="Example",
                title="Director",
                location_text=None,
                workplace_type=WorkplaceType.REMOTE.value,
                description_raw="raw",
                description_normalized="normalized",
                compensation_text=None,
            )


def test_foreign_key_behavior_on_missing_candidate(session_factory: sessionmaker[Session]) -> None:
    with session_factory() as session:
        fact = CareerFactModel(
            id=new_uuid(),
            candidate_profile_id=UUID("00000000-0000-0000-0000-000000000000"),
            category=CareerFactCategory.PLATFORM.value,
            source_organization=None,
            statement="fact",
            metric=None,
            technologies=[],
            leadership_scope=None,
            business_outcome=None,
            approved_wording="fact",
            verification_status=VerificationStatus.VERIFIED.value,
            source_reference="doc",
            created_at=utc_now(),
            updated_at=utc_now(),
        )

        session.add(fact)
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()


def test_candidate_creation_and_fetch(session_factory: sessionmaker[Session]) -> None:
    with session_factory() as session:
        candidate = create_candidate_profile(
            session,
            full_name="Jordan Lee",
            preferred_locations=["Seattle"],
            remote_preference=RemotePreference.FLEXIBLE.value,
            target_levels=["director"],
            target_functions=["platform engineering"],
        )

        session.refresh(candidate)
        assert candidate.full_name == "Jordan Lee"
