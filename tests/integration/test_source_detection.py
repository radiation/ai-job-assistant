from __future__ import annotations

from typing import Any, cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from ai_job_finder.api.dependencies import (
    greenhouse_board_validator_dependency,
    job_source_connector_dependency,
    public_page_fetcher_dependency,
)
from ai_job_finder.application.job_sources import create_job_source_configuration
from ai_job_finder.application.services import create_candidate_profile, create_career_fact
from ai_job_finder.application.source_detection import (
    SourceDetectionConfig,
    approve_source_detection_run,
    create_source_detection_run,
)
from ai_job_finder.domain.enums import (
    CareerFactCategory,
    EvidenceTag,
    JobSourceProvider,
    ProvenanceType,
    RemotePreference,
    WorkplaceType,
)
from ai_job_finder.domain.errors import AmbiguousSourceDetectionError, UnsafeUrlError
from ai_job_finder.domain.source_detection import GreenhouseBoardValidation, PublicPage
from ai_job_finder.infrastructure.job_sources.fake import FakeJobSourceConnector


class FakeFetcher:
    def __init__(self, pages: dict[str, PublicPage] | None = None, error: Exception | None = None):
        self.pages = pages or {}
        self.error = error

    def fetch(self, url: str) -> PublicPage:
        if self.error is not None:
            raise self.error
        return self.pages[url]


class FakeValidator:
    def __init__(self, valid: dict[str, GreenhouseBoardValidation]):
        self.valid = valid

    def validate_board_token(self, board_token: str) -> GreenhouseBoardValidation:
        token = board_token.strip().lower()
        return self.valid.get(token) or GreenhouseBoardValidation(
            token=token,
            status="invalid",
            valid=False,
        )


class DetectionConnector(FakeJobSourceConnector):
    def __init__(self, validation: GreenhouseBoardValidation) -> None:
        super().__init__(jobs=[])
        self.validation = validation

    def validate_board_token(self, board_token: str) -> GreenhouseBoardValidation:
        if board_token == self.validation.token:
            return self.validation
        return GreenhouseBoardValidation(token=board_token, status="invalid", valid=False)


def _config() -> SourceDetectionConfig:
    return SourceDetectionConfig(
        max_linked_scripts=2,
        max_script_bytes=100_000,
        total_script_bytes=200_000,
    )


def _page(html: str, *, url: str = "https://example.com/careers") -> PublicPage:
    return PublicPage(requested_url=url, final_url=url, content_type="text/html", text=html)


def _valid(token: str, *, jobs: int = 2) -> GreenhouseBoardValidation:
    return GreenhouseBoardValidation(
        token=token,
        status="valid_empty" if jobs == 0 else "valid",
        valid=True,
        job_count=jobs,
        sample_titles=["Director, Platform Engineering"] if jobs else [],
        company_name="Acme",
    )


def _seed_candidate(session: Session) -> None:
    candidate = create_candidate_profile(
        session,
        full_name="Jordan Lee",
        preferred_locations=["Remote"],
        remote_preference=RemotePreference.FLEXIBLE.value,
        target_levels=["director"],
        target_functions=["platform engineering"],
    )
    create_career_fact(
        session,
        candidate_profile_id=candidate.id,
        category=CareerFactCategory.PLATFORM.value,
        source_organization="Example",
        statement="Built platform teams.",
        metric="40% faster delivery",
        technologies=["Python"],
        leadership_scope="20 engineers",
        business_outcome="Faster delivery",
        approved_wording="Built platform teams with measurable impact.",
        evidence_tags=[EvidenceTag.PLATFORM_ENGINEERING.value],
        provenance_type=ProvenanceType.PROJECT_NOTES.value,
        source_reference="notes",
    )


def test_direct_html_detection_persists_terminal_preview(
    session_factory: sessionmaker[Session],
) -> None:
    with session_factory() as session:
        run = create_source_detection_run(
            session,
            company_name="Acme",
            input_url="https://example.com/careers",
            brand_alias=None,
            fetcher=FakeFetcher(
                {
                    "https://example.com/careers": _page(
                        "https://boards-api.greenhouse.io/v1/boards/acme/jobs"
                    )
                }
            ),
            validator=FakeValidator({"acme": _valid("acme", jobs=3)}),
            config=_config(),
        )

        assert run.status == "detected"
        assert run.completed_at is not None
        assert run.validated_token == "acme"
        assert run.validated_job_count == 3
        assert run.candidate_tokens[0]["source"] == "observed"
        assert run.evidence[0]["category"] == "direct_api_reference"


def test_ambiguous_detection_requires_explicit_token_selection(
    session_factory: sessionmaker[Session],
) -> None:
    with session_factory() as session:
        run = create_source_detection_run(
            session,
            company_name="Acme",
            input_url="https://example.com/careers",
            brand_alias=None,
            fetcher=FakeFetcher(
                {
                    "https://example.com/careers": _page(
                        '<a href="https://boards.greenhouse.io/acme">A</a>'
                        '<a href="https://job-boards.greenhouse.io/beta">B</a>'
                    )
                }
            ),
            validator=FakeValidator({"acme": _valid("acme"), "beta": _valid("beta")}),
            config=_config(),
        )

        assert run.status == "ambiguous"
        with pytest.raises(AmbiguousSourceDetectionError):
            approve_source_detection_run(
                session,
                run_id=run.id,
                selected_token=None,
                create_and_sync=False,
                connector=DetectionConnector(_valid("acme")),
                retain_raw_payload=True,
                close_on_empty=False,
                stale_after_seconds=3600,
            )
        result = approve_source_detection_run(
            session,
            run_id=run.id,
            selected_token="beta",
            create_and_sync=False,
            connector=DetectionConnector(_valid("beta")),
            retain_raw_payload=True,
            close_on_empty=False,
            stale_after_seconds=3600,
        )
        assert result.source.board_token == "beta"
        assert result.run.status == "source_created"


def test_generated_candidate_is_presented_only_after_validation(
    session_factory: sessionmaker[Session],
) -> None:
    with session_factory() as session:
        run = create_source_detection_run(
            session,
            company_name="Acme, Inc.",
            input_url=None,
            brand_alias=None,
            fetcher=FakeFetcher(),
            validator=FakeValidator({"acme": _valid("acme", jobs=0)}),
            config=_config(),
        )

        assert run.status == "detected"
        assert run.candidate_tokens == [
            {
                "token": "acme",
                "source": "generated",
                "evidence_categories": ["generated_candidate_validated"],
                "validation": {
                    "status": "valid_empty",
                    "valid": True,
                    "job_count": 0,
                    "sample_titles": [],
                    "company_name": "Acme",
                    "error_message": None,
                },
                "existing_source_configuration_id": None,
            }
        ]


def test_unsafe_url_records_failed_terminal_run(session_factory: sessionmaker[Session]) -> None:
    with session_factory() as session:
        run = create_source_detection_run(
            session,
            company_name=None,
            input_url="http://127.0.0.1/careers",
            brand_alias=None,
            fetcher=FakeFetcher(error=UnsafeUrlError("URL host resolved to a non-public address.")),
            validator=FakeValidator({}),
            config=_config(),
        )

        assert run.status == "failed"
        assert run.completed_at is not None
        assert "non-public" in (run.error_message or "")


def test_approval_links_existing_source_without_duplicate(
    session_factory: sessionmaker[Session],
) -> None:
    with session_factory() as session:
        existing = create_job_source_configuration(
            session,
            provider=JobSourceProvider.GREENHOUSE.value,
            display_name="Acme Greenhouse",
            company_name="Acme",
            board_token="acme",
            source_url="https://boards.greenhouse.io/acme",
        )
        run = create_source_detection_run(
            session,
            company_name="Acme",
            input_url=None,
            brand_alias=None,
            fetcher=FakeFetcher(),
            validator=FakeValidator({"acme": _valid("acme")}),
            config=_config(),
        )
        result = approve_source_detection_run(
            session,
            run_id=run.id,
            selected_token=None,
            create_and_sync=False,
            connector=DetectionConnector(_valid("acme")),
            retain_raw_payload=True,
            close_on_empty=False,
            stale_after_seconds=3600,
        )

        assert result.existing_source is True
        assert result.source.id == existing.id
        assert result.run.created_source_configuration_id == existing.id


def test_create_and_sync_invokes_import(session_factory: sessionmaker[Session]) -> None:
    with session_factory() as session:
        _seed_candidate(session)
        run = create_source_detection_run(
            session,
            company_name="Acme",
            input_url=None,
            brand_alias=None,
            fetcher=FakeFetcher(),
            validator=FakeValidator({"acme": _valid("acme")}),
            config=_config(),
        )
        connector = DetectionConnector(_valid("acme"))
        connector.jobs = [
            _posting(
                source_url="https://boards.greenhouse.io/acme/jobs/1",
                external_id="1",
            )
        ]

        result = approve_source_detection_run(
            session,
            run_id=run.id,
            selected_token=None,
            create_and_sync=True,
            connector=connector,
            retain_raw_payload=True,
            close_on_empty=False,
            stale_after_seconds=3600,
        )

        assert result.import_run is not None
        assert result.import_run.jobs_fetched == 1


def test_api_detection_and_approval(client: TestClient) -> None:
    app = cast(FastAPI, client.app)
    app.dependency_overrides[public_page_fetcher_dependency] = lambda: FakeFetcher(
        {
            "https://example.com/careers": _page(
                '<a href="https://boards.greenhouse.io/acme">Jobs</a>'
            )
        }
    )
    app.dependency_overrides[greenhouse_board_validator_dependency] = lambda: FakeValidator(
        {"acme": _valid("acme")}
    )
    app.dependency_overrides[job_source_connector_dependency] = lambda: DetectionConnector(
        _valid("acme")
    )

    response = client.post(
        "/api/v1/source-detections",
        json={"company_name": "Acme", "input_url": "https://example.com/careers"},
    )
    assert response.status_code == 201
    run = response.json()
    assert run["status"] == "detected"
    approval = client.post(f"/api/v1/source-detections/{run['id']}/approve", json={})
    assert approval.status_code == 200
    assert approval.json()["source"]["board_token"] == "acme"


def test_web_detection_pages_render(client: TestClient) -> None:
    app = cast(FastAPI, client.app)
    app.dependency_overrides[public_page_fetcher_dependency] = lambda: FakeFetcher(
        {
            "https://example.com/careers": _page(
                '<a href="https://boards.greenhouse.io/acme">Jobs</a>'
            )
        }
    )
    app.dependency_overrides[greenhouse_board_validator_dependency] = lambda: FakeValidator(
        {"acme": _valid("acme")}
    )

    form = client.get("/job-sources/detect")
    assert form.status_code == 200
    response = client.post(
        "/job-sources/detect",
        data={"company_name": "Acme", "input_url": "https://example.com/careers"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    detail = client.get(response.headers["location"])
    assert detail.status_code == 200
    assert "acme" in detail.text


def _posting(*, source_url: str, external_id: str) -> Any:
    from ai_job_finder.domain.job_sources import NormalizedJobPosting

    return NormalizedJobPosting(
        provider=JobSourceProvider.GREENHOUSE,
        company_name="Acme",
        title="Director, Platform Engineering",
        location_text="Remote",
        workplace_type=WorkplaceType.REMOTE,
        description_raw="Lead platform engineering.",
        description_normalized="Lead platform engineering.",
        compensation_text=None,
        source_url=source_url,
        external_id=external_id,
        internal_job_id=None,
        source_updated_at=None,
        raw_payload={"id": external_id},
    )
