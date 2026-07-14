from __future__ import annotations

from collections.abc import Iterator
from typing import Any, cast
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from ai_job_finder.api.dependencies import (
    career_fact_extractor_dependency,
    db_session_dependency,
    document_storage_dependency,
    settings_dependency,
)
from ai_job_finder.application.documents import (
    extract_document_text,
    start_extraction_run,
    upload_source_document,
)
from ai_job_finder.application.extraction import (
    CareerFactExtractionResult,
    ExtractedDocument,
)
from ai_job_finder.application.services import create_candidate_profile
from ai_job_finder.infrastructure.database.base import Base
from ai_job_finder.infrastructure.database.models import (
    CareerFactProposalModel,
    ExtractionRunModel,
    SourceDocumentModel,
)
from ai_job_finder.infrastructure.database.session import create_engine_from_url
from ai_job_finder.infrastructure.llm.fake import FakeCareerFactExtractor
from ai_job_finder.infrastructure.storage import InMemoryDocumentStorage
from ai_job_finder.main import create_app
from ai_job_finder.settings import Settings


class RecordingExtractor(FakeCareerFactExtractor):
    def __init__(self) -> None:
        super().__init__()
        self.calls = 0

    def extract(self, document: ExtractedDocument) -> CareerFactExtractionResult:
        self.calls += 1
        return super().extract(document)


class ExplodingExtractor:
    provider = "fake"
    model_id = "exploding-extractor"
    prompt_version = "career_fact_extraction_v1"
    schema_version = "career_fact_extraction_v1"
    temperature = 0.0

    def extract(self, document: ExtractedDocument) -> CareerFactExtractionResult:
        raise RuntimeError("provider boom")


class TrackingStorage(InMemoryDocumentStorage):
    def __init__(self) -> None:
        super().__init__()
        self.saved_keys: list[str] = []
        self.deleted_keys: list[str] = []

    def save(
        self,
        *,
        candidate_profile_id: UUID,
        document_id: UUID,
        original_filename: str,
        content: bytes,
    ) -> str:
        key = super().save(
            candidate_profile_id=candidate_profile_id,
            document_id=document_id,
            original_filename=original_filename,
            content=content,
        )
        self.saved_keys.append(key)
        return key

    def delete(self, storage_key: str) -> None:
        self.deleted_keys.append(storage_key)
        super().delete(storage_key)


def _document_client(
    session_factory: sessionmaker[Session],
    *,
    extraction_enabled: bool = True,
    extractor: object | None = None,
    settings_overrides: dict[str, Any] | None = None,
    raise_server_exceptions: bool = True,
) -> TestClient:
    app = create_app()
    storage = InMemoryDocumentStorage()
    settings_kwargs: dict[str, Any] = {
        "database_url": "sqlite+pysqlite:///:memory:",
        "extraction_enabled": extraction_enabled,
        "extraction_provider": "fake",
        "max_upload_size_bytes": 1024 * 1024,
    }
    if settings_overrides:
        settings_kwargs.update(settings_overrides)
    settings = Settings(**settings_kwargs)

    def override_db() -> Iterator[Session]:
        with session_factory() as session:
            yield session

    app.dependency_overrides[db_session_dependency] = override_db
    app.dependency_overrides[document_storage_dependency] = lambda: storage
    app.dependency_overrides[settings_dependency] = lambda: settings
    app.dependency_overrides[career_fact_extractor_dependency] = (
        (lambda: extractor) if extractor is not None else (lambda: FakeCareerFactExtractor())
    )
    if not extraction_enabled:
        app.dependency_overrides.pop(career_fact_extractor_dependency)
    return TestClient(app, raise_server_exceptions=raise_server_exceptions)


def _create_candidate(client: TestClient) -> str:
    response = client.post(
        "/api/v1/candidate-profile",
        json={
            "full_name": "Jordan Lee",
            "preferred_locations": ["Remote"],
            "remote_preference": "flexible",
            "target_levels": ["director"],
            "target_functions": ["platform engineering"],
        },
    )
    assert response.status_code == 201
    return str(response.json()["id"])


def _upload_document(
    client: TestClient,
    content: bytes = b"Led platform work with Kubernetes.",
) -> dict[str, Any]:
    response = client.post(
        "/api/v1/documents",
        data={"source_type": "resume", "upload_note": "fixture"},
        files={"document_file": ("resume.txt", content, "text/plain")},
    )
    assert response.status_code == 201
    return cast(dict[str, Any], response.json())


def test_document_upload_extraction_accept_and_reject_flow(
    session_factory: sessionmaker[Session],
) -> None:
    with _document_client(session_factory) as client:
        _create_candidate(client)
        document = _upload_document(client)

        duplicate = client.post(
            "/api/v1/documents",
            data={"source_type": "resume"},
            files={
                "document_file": ("copy.txt", b"Led platform work with Kubernetes.", "text/plain")
            },
        )
        assert duplicate.status_code == 409
        assert duplicate.json()["error"]["code"] == "duplicate_source_document"

        extraction = client.post(f"/api/v1/documents/{document['id']}/extractions")
        assert extraction.status_code == 200
        assert extraction.json()["status"] == "succeeded"
        assert extraction.json()["prompt_version"] == "career_fact_extraction_v1"

        proposals = client.get("/api/v1/fact-proposals")
        assert proposals.status_code == 200
        proposal_id = proposals.json()[0]["id"]
        assert proposals.json()[0]["review_status"] == "pending"

        accept = client.post(f"/api/v1/fact-proposals/{proposal_id}/accept")
        assert accept.status_code == 200
        assert accept.json()["review_status"] == "accepted"
        facts = client.get("/api/v1/career-facts")
        assert facts.status_code == 200
        assert facts.json()[0]["lifecycle_status"] == "draft"

        second_document = _upload_document(client, b"Led another platform initiative.")
        second_extraction = client.post(f"/api/v1/documents/{second_document['id']}/extractions")
        assert second_extraction.status_code == 200
        pending = client.get("/api/v1/fact-proposals", params={"review_status": "pending"})
        second_proposal_id = pending.json()[0]["id"]
        reject = client.post(f"/api/v1/fact-proposals/{second_proposal_id}/reject")
        assert reject.status_code == 200
        assert reject.json()["review_status"] == "rejected"


def test_extraction_disabled_returns_structured_error(
    session_factory: sessionmaker[Session],
) -> None:
    with _document_client(session_factory, extraction_enabled=False) as client:
        _create_candidate(client)
        document = _upload_document(client)

        response = client.post(f"/api/v1/documents/{document['id']}/extractions")

        assert response.status_code == 503
        assert response.json()["error"]["code"] == "extraction_provider_unavailable"


@pytest.mark.parametrize(
    ("content", "chunk_size", "max_chunks", "expected_calls"),
    [
        (b"alpha\n\nbeta", 7, 2, 2),
        (b"alpha\n\nbeta\n\ngamma", 7, 3, 3),
    ],
)
def test_chunk_limit_allows_documents_at_or_below_limit(
    session_factory: sessionmaker[Session],
    content: bytes,
    chunk_size: int,
    max_chunks: int,
    expected_calls: int,
) -> None:
    extractor = RecordingExtractor()
    with _document_client(
        session_factory,
        extractor=extractor,
        settings_overrides={
            "extraction_chunk_size": chunk_size,
            "extraction_max_chunks": max_chunks,
        },
    ) as client:
        _create_candidate(client)
        document = _upload_document(client, content)

        extraction = client.post(f"/api/v1/documents/{document['id']}/extractions")

        assert extraction.status_code == 200
        assert extraction.json()["status"] == "succeeded"
        assert extractor.calls == expected_calls


def test_chunk_limit_failure_is_terminal_and_skips_provider(
    session_factory: sessionmaker[Session],
) -> None:
    extractor = RecordingExtractor()
    with _document_client(
        session_factory,
        extractor=extractor,
        settings_overrides={
            "extraction_chunk_size": 8,
            "extraction_max_chunks": 2,
        },
    ) as client:
        _create_candidate(client)
        document = _upload_document(client, b"alpha\n\nbeta\n\ngamma")

        extraction = client.post(f"/api/v1/documents/{document['id']}/extractions")

        assert extraction.status_code == 422
        assert extraction.json()["error"]["code"] == "document_extraction_limit_exceeded"
        assert extractor.calls == 0

        runs = client.get(f"/api/v1/documents/{document['id']}/extraction-runs")
        assert runs.status_code == 200
        assert runs.json()[0]["status"] == "failed"
        assert runs.json()[0]["chunk_count"] == 3

        status = client.get(f"/api/v1/documents/{document['id']}/extraction-status")
        assert status.status_code == 200
        assert status.json()["extraction_status"] == "extraction_failed"

        proposals = client.get("/api/v1/fact-proposals")
        assert proposals.status_code == 200
        assert proposals.json() == []


def test_unexpected_extractor_failure_marks_run_failed(
    session_factory: sessionmaker[Session],
) -> None:
    with _document_client(
        session_factory,
        extractor=ExplodingExtractor(),
        raise_server_exceptions=False,
    ) as client:
        _create_candidate(client)
        document = _upload_document(client)

        extraction = client.post(f"/api/v1/documents/{document['id']}/extractions")

        assert extraction.status_code == 500
        assert extraction.json()["error"]["code"] == "internal_server_error"

        runs = client.get(f"/api/v1/documents/{document['id']}/extraction-runs")
        assert runs.status_code == 200
        assert runs.json()[0]["status"] == "failed"
        assert runs.json()[0]["error_message"] == (
            "Extraction failed due to an unexpected RuntimeError."
        )

        status = client.get(f"/api/v1/documents/{document['id']}/extraction-status")
        assert status.status_code == 200
        assert status.json()["extraction_status"] == "extraction_failed"


def test_unexpected_post_processing_failure_marks_run_failed(
    session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "ai_job_finder.application.documents.proposals._find_duplicate_fact",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("post-processing boom")),
    )
    with _document_client(session_factory, raise_server_exceptions=False) as client:
        _create_candidate(client)
        document = _upload_document(client)

        extraction = client.post(f"/api/v1/documents/{document['id']}/extractions")

        assert extraction.status_code == 500
        runs = client.get(f"/api/v1/documents/{document['id']}/extraction-runs")
        assert runs.status_code == 200
        assert runs.json()[0]["status"] == "failed"

        status = client.get(f"/api/v1/documents/{document['id']}/extraction-status")
        assert status.status_code == 200
        assert status.json()["extraction_status"] == "extraction_failed"


def test_supporting_excerpt_is_immutable_after_extraction(
    session_factory: sessionmaker[Session],
) -> None:
    with _document_client(session_factory) as client:
        _create_candidate(client)
        document = _upload_document(client)
        extraction = client.post(f"/api/v1/documents/{document['id']}/extractions")
        assert extraction.status_code == 200

        proposals = client.get("/api/v1/fact-proposals")
        proposal = proposals.json()[0]
        payload = {
            "proposed_category": proposal["proposed_category"],
            "proposed_source_organization": proposal["proposed_source_organization"],
            "proposed_statement": "Refined statement",
            "proposed_metric": proposal["proposed_metric"],
            "proposed_technologies": proposal["proposed_technologies"],
            "proposed_leadership_scope": proposal["proposed_leadership_scope"],
            "proposed_business_outcome": proposal["proposed_business_outcome"],
            "proposed_approved_wording": proposal["proposed_approved_wording"],
            "proposed_evidence_tags": proposal["proposed_evidence_tags"],
            "supporting_excerpt": proposal["supporting_excerpt"],
            "source_location": proposal["source_location"],
            "confidence": proposal["confidence"],
        }

        accepted_edit = client.put(f"/api/v1/fact-proposals/{proposal['id']}", json=payload)
        assert accepted_edit.status_code == 200
        assert accepted_edit.json()["supporting_excerpt"] == proposal["supporting_excerpt"]

        rejected_edit = client.put(
            f"/api/v1/fact-proposals/{proposal['id']}",
            json={**payload, "supporting_excerpt": "Changed excerpt"},
        )
        assert rejected_edit.status_code == 422
        assert rejected_edit.json()["error"]["code"] == "invalid_proposal_edit"


def test_commit_failure_after_proposal_build_marks_run_failed(tmp_path) -> None:  # type: ignore[no-untyped-def]
    class CommitFailingSession(Session):
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            super().__init__(*args, **kwargs)
            self._commit_count = 0

        def commit(self) -> None:
            self._commit_count += 1
            if self._commit_count == 2:
                raise RuntimeError("commit boom")
            super().commit()

    engine = create_engine_from_url(f"sqlite+pysqlite:///{tmp_path / 'commit-failure.db'}")
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    setup_session_factory = sessionmaker(
        bind=engine,
        autoflush=False,
        expire_on_commit=False,
        class_=Session,
    )
    session_factory = sessionmaker(
        bind=engine,
        autoflush=False,
        expire_on_commit=False,
        class_=CommitFailingSession,
    )
    try:
        storage = InMemoryDocumentStorage()
        with setup_session_factory() as session:
            candidate = create_candidate_profile(
                session,
                full_name="Jordan Lee",
                preferred_locations=["Remote"],
                remote_preference="flexible",
                target_levels=["director"],
                target_functions=["platform engineering"],
            )
            document = upload_source_document(
                session,
                storage,
                candidate_profile_id=candidate.id,
                original_filename="resume.txt",
                content_type="text/plain",
                content=b"Led platform work with Kubernetes.",
                source_type="resume",
                max_upload_size_bytes=1024 * 1024,
            )
            extract_document_text(
                session,
                storage,
                document_id=document.id,
                max_extracted_characters=10000,
            )

        with session_factory() as session:
            persisted_document = session.get(SourceDocumentModel, document.id)
            assert persisted_document is not None

            with pytest.raises(RuntimeError, match="commit boom"):
                start_extraction_run(
                    session,
                    storage,
                    FakeCareerFactExtractor(),
                    document_id=persisted_document.id,
                    max_extracted_characters=10000,
                    chunk_size=1000,
                    max_chunks=4,
                )

        with sessionmaker(bind=engine, expire_on_commit=False, class_=Session)() as verify_session:
            run = verify_session.scalar(select(ExtractionRunModel))
            document_row = verify_session.get(SourceDocumentModel, document.id)
            proposal_count = len(list(verify_session.scalars(select(CareerFactProposalModel))))

            assert run is not None
            assert run.status == "failed"
            assert run.completed_at is not None
            assert document_row is not None
            assert document_row.extraction_status == "extraction_failed"
            assert proposal_count == 0
    finally:
        Base.metadata.drop_all(engine)
        engine.dispose()


def test_upload_persistence_failure_cleans_up_newly_stored_file(tmp_path) -> None:  # type: ignore[no-untyped-def]
    class UploadFailingSession(Session):
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            super().__init__(*args, **kwargs)
            self._commit_count = 0

        def commit(self) -> None:
            self._commit_count += 1
            if self._commit_count == 2:
                raise RuntimeError("upload commit boom")
            super().commit()

    engine = create_engine_from_url(f"sqlite+pysqlite:///{tmp_path / 'upload-failure.db'}")
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(
        bind=engine,
        autoflush=False,
        expire_on_commit=False,
        class_=UploadFailingSession,
    )
    try:
        storage = TrackingStorage()
        with session_factory() as session:
            candidate = create_candidate_profile(
                session,
                full_name="Jordan Lee",
                preferred_locations=["Remote"],
                remote_preference="flexible",
                target_levels=["director"],
                target_functions=["platform engineering"],
            )

            with pytest.raises(RuntimeError, match="upload commit boom"):
                upload_source_document(
                    session,
                    storage,
                    candidate_profile_id=candidate.id,
                    original_filename="resume.txt",
                    content_type="text/plain",
                    content=b"Led platform work with Kubernetes.",
                    source_type="resume",
                    max_upload_size_bytes=1024 * 1024,
                )

        assert storage.saved_keys
        assert storage.deleted_keys == storage.saved_keys
    finally:
        Base.metadata.drop_all(engine)
        engine.dispose()
