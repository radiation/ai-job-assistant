from __future__ import annotations

import json
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ai_job_finder.bootstrap.client import ApiClient, is_bootstrap_owned_candidate, is_localhost_url
from ai_job_finder.bootstrap.contracts import (
    CandidateResponse,
    CareerFactLifecycle,
    CareerFactResponse,
    HarnessError,
    JobEvaluationResponse,
    JobLeadResponse,
    JobSourceConfigurationPayload,
    JobSourceConfigurationResponse,
    RunMetadata,
    SourceDetectionRunPayload,
)
from ai_job_finder.bootstrap.fixtures import (
    BOOTSTRAP_OWNER,
    SCORING_VERSION,
    _bootstrap_candidate,
    _fact_definitions,
    _job_definitions,
)

if TYPE_CHECKING:
    from ai_job_finder.bootstrap.cli import HarnessConfig


class BootstrapHarness:
    def __init__(self, client: ApiClient, config: HarnessConfig) -> None:
        self.client = client
        self.config = config
        self.metadata = RunMetadata(base_url=config.base_url, reset_requested=config.reset)

    def run(self) -> RunMetadata:
        self._enforce_safety()
        self.client.wait_until_ready(self.config.readiness_timeout)
        candidate = self._phase_candidate_setup()
        facts = self._phase_draft_fact_creation()
        strong_job = self._ensure_job("strong")
        draft_evaluation = self._phase_draft_evidence_exclusion(candidate.id, strong_job.id)
        self._phase_verification(candidate.id, strong_job.id, facts, draft_evaluation)
        self._phase_verified_edit_behavior(candidate.id, strong_job.id, facts)
        self._phase_reverification(candidate.id, strong_job.id, facts)
        self._phase_archive_behavior(candidate.id, strong_job.id, facts)
        self._phase_restore_behavior(candidate.id, strong_job.id, facts)
        self._phase_filtering(facts)
        if self.config.document_ingestion:
            self._phase_document_ingestion()
        self._phase_comparative_evaluation(candidate.id)
        if self.config.fake_greenhouse:
            self._phase_fake_greenhouse_import()
        return self.metadata

    def _enforce_safety(self) -> None:
        if self.config.reset and not self.config.allow_destructive:
            raise HarnessError(
                "safety",
                "destructive reset requires explicit destructive confirmation",
                endpoint="cli",
                expected="--allow-destructive with --reset",
                actual="--reset without destructive confirmation",
            )
        if self.config.reset and not is_localhost_url(self.config.base_url):
            if not self.config.allow_non_localhost_destructive:
                raise HarnessError(
                    "safety",
                    "destructive reset refused for non-localhost target",
                    endpoint="cli",
                    expected="localhost target or --allow-non-localhost-destructive",
                    actual=self.config.base_url,
                )

    def _record_pass(self, phase: str, summary: str) -> None:
        self.metadata.passed += 1
        self.metadata.phases.append({"phase": phase, "summary": summary, "passed": True})
        print(f"PASS {summary}")

    def _record_failure(self, error: HarnessError) -> None:
        self.metadata.failed += 1
        self.metadata.phases.append(
            {
                "phase": error.phase,
                "summary": error.assertion,
                "passed": False,
                "endpoint": error.endpoint,
                "expected": error.expected,
                "actual": error.actual,
                "response": error.response_body,
            }
        )

    def _assert(
        self,
        condition: bool,
        phase: str,
        assertion: str,
        *,
        endpoint: str,
        expected: Any,
        actual: Any,
        response: Any | None = None,
    ) -> None:
        if not condition:
            raise HarnessError(
                phase,
                assertion,
                endpoint=endpoint,
                expected=expected,
                actual=actual,
                response_body=response,
            )

    def _phase_candidate_setup(self) -> CandidateResponse:
        phase = "phase_1_candidate_setup"
        if self.config.reset:
            self.client.reset_candidate()
        existing = self.client.get_candidate()
        desired = _bootstrap_candidate()
        if existing is None:
            candidate = self.client.create_candidate(desired)
            self.metadata.created_ids["candidate"] = candidate.id
            self._record_pass(phase, "candidate created")
        else:
            if not is_bootstrap_owned_candidate(existing):
                raise HarnessError(
                    phase,
                    "non-bootstrap candidate exists without safe replacement",
                    endpoint="GET /api/v1/candidate-profile",
                    expected="no candidate or bootstrap-owned candidate",
                    actual=existing.model_dump(mode="json"),
                )
            if existing.model_dump(
                exclude={"id", "created_at", "updated_at"}, mode="json"
            ) != desired.model_dump(mode="json"):
                candidate = self.client.update_candidate(desired)
            else:
                candidate = existing
            self.metadata.reused_ids["candidate"] = candidate.id
            self._record_pass(phase, "candidate created")

        duplicate_response, duplicate_body = self.client._request(
            "POST", "/api/v1/candidate-profile", json=desired.model_dump(mode="json")
        )
        self._assert(
            duplicate_response.status_code == 409,
            phase,
            "second candidate creation is rejected",
            endpoint="POST /api/v1/candidate-profile",
            expected=409,
            actual=duplicate_response.status_code,
            response=duplicate_body,
        )
        self._record_pass(phase, "second candidate rejected")
        return candidate

    def _phase_draft_fact_creation(self) -> dict[str, CareerFactResponse]:
        phase = "phase_2_draft_fact_creation"
        existing = {
            fact.source_reference: fact for fact in self.client.list_facts(include_archived=True)
        }
        facts: dict[str, CareerFactResponse] = {}
        for key, payload in _fact_definitions().items():
            fact = existing.get(payload.source_reference)
            if fact is None:
                fact = self.client.create_fact(payload)
                self.metadata.created_ids[f"fact:{key}"] = fact.id
            else:
                fact = self.client.update_fact(fact.id, payload)
                self.metadata.reused_ids[f"fact:{key}"] = fact.id
            facts[key] = fact
            roundtrip = self.client.get_fact(fact.id)
            self._assert(
                roundtrip.source_reference == payload.source_reference,
                phase,
                "fact provenance round-trips correctly",
                endpoint=f"GET /api/v1/career-facts/{fact.id}",
                expected=payload.source_reference,
                actual=roundtrip.source_reference,
                response=roundtrip.model_dump(mode="json"),
            )
            self._assert(
                set(roundtrip.evidence_tags) == set(payload.evidence_tags),
                phase,
                "fact evidence tags round-trip correctly",
                endpoint=f"GET /api/v1/career-facts/{fact.id}",
                expected=payload.evidence_tags,
                actual=roundtrip.evidence_tags,
                response=roundtrip.model_dump(mode="json"),
            )
        self._record_pass(phase, f"{len(facts)} draft facts created")
        return facts

    def _drive_bootstrap_facts_to_draft(
        self, facts: dict[str, CareerFactResponse], phase: str
    ) -> dict[str, CareerFactResponse]:
        drafted: dict[str, CareerFactResponse] = {}
        for key, fact in facts.items():
            if fact.lifecycle_status == CareerFactLifecycle.DRAFT:
                drafted[key] = fact
                continue
            drafted[key] = self.client.transition_fact(fact.id, CareerFactLifecycle.DRAFT)
            self._assert(
                drafted[key].lifecycle_status == CareerFactLifecycle.DRAFT,
                phase,
                "bootstrap fact can be driven back to draft for draft-exclusion checks",
                endpoint=f"POST /api/v1/career-facts/{fact.id}/transitions",
                expected=CareerFactLifecycle.DRAFT.value,
                actual=drafted[key].lifecycle_status.value,
                response=drafted[key].model_dump(mode="json"),
            )
        return drafted

    def _ensure_job(self, key: str) -> JobLeadResponse:
        payload = _job_definitions()[key]
        matches = self.client.list_jobs(
            source=payload.source.value, external_id=payload.external_id
        )
        if not matches:
            job = self.client.create_job(payload)
            self.metadata.created_ids[f"job:{key}"] = job.id
            return job
        job = self.client.update_job(matches[0].id, payload)
        self.metadata.reused_ids[f"job:{key}"] = job.id
        return job

    def _phase_draft_evidence_exclusion(
        self, candidate_id: str, job_id: str
    ) -> JobEvaluationResponse:
        phase = "phase_3_draft_evidence_exclusion"
        draft_facts = self._drive_bootstrap_facts_to_draft(
            {key: self._fact_by_key(key) for key in _fact_definitions()},
            phase,
        )
        self._assert(
            all(
                fact.lifecycle_status == CareerFactLifecycle.DRAFT for fact in draft_facts.values()
            ),
            phase,
            "all bootstrap facts are draft before draft-exclusion evaluation",
            endpoint="POST /api/v1/career-facts/{fact_id}/transitions",
            expected="all lifecycle statuses draft",
            actual={key: fact.lifecycle_status.value for key, fact in draft_facts.items()},
            response={key: fact.model_dump(mode="json") for key, fact in draft_facts.items()},
        )
        evaluation = self.client.create_evaluation(job_id, candidate_id)
        self._assert(
            "No verified evidence matched the job signals." in evaluation.explanation,
            phase,
            "draft facts do not appear as matched evidence",
            endpoint=f"POST /api/v1/job-leads/{job_id}/evaluations",
            expected="no matched verified evidence",
            actual=evaluation.explanation,
        )
        self._assert(
            evaluation.technical_alignment_score <= 40 and evaluation.leadership_scope_score <= 35,
            phase,
            "no verified-evidence credit is applied while all facts are draft",
            endpoint=f"POST /api/v1/job-leads/{job_id}/evaluations",
            expected="base scores without verified evidence uplift",
            actual={
                "technical_alignment_score": evaluation.technical_alignment_score,
                "leadership_scope_score": evaluation.leadership_scope_score,
            },
            response=evaluation.model_dump(mode="json"),
        )
        self.metadata.created_ids["evaluation:strong:draft"] = evaluation.id
        self._record_pass(phase, "draft facts excluded from scoring")
        return evaluation

    def _phase_verification(
        self,
        candidate_id: str,
        job_id: str,
        facts: dict[str, CareerFactResponse],
        previous: JobEvaluationResponse,
    ) -> None:
        phase = "phase_4_verification"
        verified_platform = self.client.transition_fact(
            facts["platform"].id, CareerFactLifecycle.VERIFIED
        )
        verified_cicd = self.client.transition_fact(facts["cicd"].id, CareerFactLifecycle.VERIFIED)
        self._assert(
            verified_platform.verified_at is not None and verified_cicd.verified_at is not None,
            phase,
            "verified facts set verified_at",
            endpoint="POST /api/v1/career-facts/{fact_id}/transitions",
            expected="verified_at timestamp",
            actual={
                "platform": verified_platform.verified_at,
                "cicd": verified_cicd.verified_at,
            },
        )
        evaluation = self.client.create_evaluation(job_id, candidate_id)
        history = self.client.list_evaluations(job_id)
        self._assert(
            evaluation.id != previous.id and len(history) >= 2,
            phase,
            "verification creates a new immutable evaluation",
            endpoint=f"POST /api/v1/job-leads/{job_id}/evaluations",
            expected="new evaluation id and history growth",
            actual={
                "new_id": evaluation.id,
                "previous_id": previous.id,
                "history_count": len(history),
            },
            response=[item.model_dump(mode="json") for item in history],
        )
        self._assert(
            evaluation.technical_alignment_score > previous.technical_alignment_score
            and evaluation.leadership_scope_score >= previous.leadership_scope_score,
            phase,
            "verified evidence increases technical or leadership contribution",
            endpoint=f"POST /api/v1/job-leads/{job_id}/evaluations",
            expected="scores increase directionally",
            actual={
                "previous_technical": previous.technical_alignment_score,
                "current_technical": evaluation.technical_alignment_score,
                "previous_leadership": previous.leadership_scope_score,
                "current_leadership": evaluation.leadership_scope_score,
            },
            response=evaluation.model_dump(mode="json"),
        )
        self._assert(
            "Scaled a self-service developer platform" in evaluation.explanation
            and "Built CI/CD and observability foundations" in evaluation.explanation,
            phase,
            "explanation references matched verified evidence",
            endpoint=f"POST /api/v1/job-leads/{job_id}/evaluations",
            expected="verified fact wording in explanation",
            actual=evaluation.explanation,
        )
        self._record_pass(phase, "verified evidence increased platform alignment")

    def _phase_verified_edit_behavior(
        self, candidate_id: str, job_id: str, facts: dict[str, CareerFactResponse]
    ) -> None:
        phase = "phase_5_verified_edit_behavior"
        edited_payload = _fact_definitions()["platform"].model_copy(
            update={
                "statement": (
                    "Led a refactored developer platform program spanning developer "
                    "tooling and self-service infrastructure."
                ),
                "approved_wording": (
                    "Refreshed platform narrative after updating the verified fact."
                ),
            }
        )
        updated = self.client.update_fact(facts["platform"].id, edited_payload)
        self._assert(
            updated.lifecycle_status == CareerFactLifecycle.DRAFT and updated.verified_at is None,
            phase,
            "material edit returns verified fact to draft and clears verified_at",
            endpoint=f"PUT /api/v1/career-facts/{facts['platform'].id}",
            expected={"lifecycle_status": "draft", "verified_at": None},
            actual={
                "lifecycle_status": updated.lifecycle_status.value,
                "verified_at": updated.verified_at,
            },
            response=updated.model_dump(mode="json"),
        )
        evaluation = self.client.create_evaluation(job_id, candidate_id)
        self._assert(
            "Refreshed platform narrative" not in evaluation.explanation
            and "Built CI/CD and observability foundations" in evaluation.explanation,
            phase,
            "edited draft fact no longer contributes while other verified facts still do",
            endpoint=f"POST /api/v1/job-leads/{job_id}/evaluations",
            expected="edited fact excluded, CI/CD fact retained",
            actual=evaluation.explanation,
        )
        self._record_pass(phase, "verified edit returned fact to draft")

    def _phase_reverification(
        self, candidate_id: str, job_id: str, facts: dict[str, CareerFactResponse]
    ) -> None:
        phase = "phase_6_reverification"
        self.client.transition_fact(facts["platform"].id, CareerFactLifecycle.VERIFIED)
        evaluation = self.client.create_evaluation(job_id, candidate_id)
        self._assert(
            "Refreshed platform narrative" in evaluation.explanation,
            phase,
            "reverified fact contributes again",
            endpoint=f"POST /api/v1/job-leads/{job_id}/evaluations",
            expected="reverified fact wording present",
            actual=evaluation.explanation,
        )
        self._record_pass(phase, "reverified fact contribution returned")

    def _phase_archive_behavior(
        self, candidate_id: str, job_id: str, facts: dict[str, CareerFactResponse]
    ) -> None:
        phase = "phase_7_archive_behavior"
        archived = self.client.transition_fact(facts["platform"].id, CareerFactLifecycle.ARCHIVED)
        self._assert(
            archived.lifecycle_status == CareerFactLifecycle.ARCHIVED
            and archived.archived_at is not None,
            phase,
            "archive transition sets archived state",
            endpoint=f"POST /api/v1/career-facts/{facts['platform'].id}/transitions",
            expected={"lifecycle_status": "archived", "archived_at": "timestamp"},
            actual={
                "lifecycle_status": archived.lifecycle_status.value,
                "archived_at": archived.archived_at,
            },
            response=archived.model_dump(mode="json"),
        )
        evaluation = self.client.create_evaluation(job_id, candidate_id)
        self._assert(
            "Refreshed platform narrative" not in evaluation.explanation,
            phase,
            "archived fact no longer contributes",
            endpoint=f"POST /api/v1/job-leads/{job_id}/evaluations",
            expected="archived fact absent from explanation",
            actual=evaluation.explanation,
        )
        default_list = self.client.list_facts()
        archived_list = self.client.list_facts(lifecycle_status="archived")
        self._assert(
            facts["platform"].id not in {fact.id for fact in default_list}
            and facts["platform"].id in {fact.id for fact in archived_list},
            phase,
            "default list excludes archived facts and archived filter includes them",
            endpoint="GET /api/v1/career-facts",
            expected="archived fact hidden by default and visible with archived filter",
            actual={
                "default_ids": [fact.id for fact in default_list],
                "archived_ids": [fact.id for fact in archived_list],
            },
        )
        self._record_pass(phase, "archived fact excluded")

    def _phase_restore_behavior(
        self, candidate_id: str, job_id: str, facts: dict[str, CareerFactResponse]
    ) -> None:
        phase = "phase_8_restore_behavior"
        restored = self.client.transition_fact(facts["platform"].id, CareerFactLifecycle.DRAFT)
        self._assert(
            restored.lifecycle_status == CareerFactLifecycle.DRAFT and restored.verified_at is None,
            phase,
            "restored archived fact returns to draft without verification",
            endpoint=f"POST /api/v1/career-facts/{facts['platform'].id}/transitions",
            expected={"lifecycle_status": "draft", "verified_at": None},
            actual={
                "lifecycle_status": restored.lifecycle_status.value,
                "verified_at": restored.verified_at,
            },
            response=restored.model_dump(mode="json"),
        )
        evaluation = self.client.create_evaluation(job_id, candidate_id)
        self._assert(
            "Refreshed platform narrative" not in evaluation.explanation,
            phase,
            "restored draft fact still does not contribute until reverified",
            endpoint=f"POST /api/v1/job-leads/{job_id}/evaluations",
            expected="restored fact absent from explanation",
            actual=evaluation.explanation,
        )
        self._record_pass(phase, "restored draft fact still excluded")

    def _phase_filtering(self, facts: dict[str, CareerFactResponse]) -> None:
        phase = "phase_9_filtering"
        self.client.transition_fact(facts["platform"].id, CareerFactLifecycle.VERIFIED)
        self.client.transition_fact(facts["ai"].id, CareerFactLifecycle.VERIFIED)
        verified = self.client.list_facts(lifecycle_status="verified")
        platform = self.client.list_facts(category="platform")
        organization = self.client.list_facts(source_organization="Northstar Platforms")
        evidence = self.client.list_facts(evidence_tag="ai_enablement")
        self._assert(
            {fact.id for fact in verified} >= {facts["platform"].id, facts["ai"].id},
            phase,
            "verified filter returns expected verified facts",
            endpoint="GET /api/v1/career-facts?lifecycle_status=verified",
            expected="verified bootstrap facts included",
            actual=[fact.id for fact in verified],
        )
        self._assert(
            [fact.id for fact in platform] == [facts["platform"].id],
            phase,
            "category filter returns only platform fact",
            endpoint="GET /api/v1/career-facts?category=platform",
            expected=[facts["platform"].id],
            actual=[fact.id for fact in platform],
        )
        self._assert(
            {facts["platform"].id, facts["cicd"].id, facts["business"].id}.issubset(
                {fact.id for fact in organization}
            ),
            phase,
            "source organization filter returns expected facts",
            endpoint="GET /api/v1/career-facts?source_organization=Northstar%20Platforms",
            expected="Northstar-owned facts subset",
            actual=[fact.id for fact in organization],
        )
        self._assert(
            [fact.id for fact in evidence] == [facts["ai"].id],
            phase,
            "evidence tag filter returns only AI fact",
            endpoint="GET /api/v1/career-facts?evidence_tag=ai_enablement",
            expected=[facts["ai"].id],
            actual=[fact.id for fact in evidence],
        )
        self._record_pass(phase, "filters validated")

    def _phase_comparative_evaluation(self, candidate_id: str) -> None:
        phase = "phase_10_comparative_evaluation"
        self.client.transition_fact(self._fact_by_key("cicd").id, CareerFactLifecycle.VERIFIED)
        self.client.transition_fact(self._fact_by_key("business").id, CareerFactLifecycle.VERIFIED)
        strong_job = self._ensure_job("strong")
        partial_job = self._ensure_job("partial")
        weak_job = self._ensure_job("weak")
        strong_eval = self.client.create_evaluation(strong_job.id, candidate_id)
        partial_eval = self.client.create_evaluation(partial_job.id, candidate_id)
        weak_eval = self.client.create_evaluation(weak_job.id, candidate_id)
        self._assert(
            strong_eval.overall_score > weak_eval.overall_score,
            phase,
            "strong platform role ranks above unrelated role",
            endpoint="POST /api/v1/job-leads/{job_id}/evaluations",
            expected="strong overall score > weak overall score",
            actual={"strong": strong_eval.overall_score, "weak": weak_eval.overall_score},
        )
        self._assert(
            partial_eval.technical_alignment_score >= weak_eval.technical_alignment_score
            and "AI" in partial_eval.explanation,
            phase,
            "AI or data-platform role receives relevant partial evidence",
            endpoint="POST /api/v1/job-leads/{job_id}/evaluations",
            expected="partial role gets AI-related support",
            actual={
                "partial_technical": partial_eval.technical_alignment_score,
                "weak_technical": weak_eval.technical_alignment_score,
                "partial_explanation": partial_eval.explanation,
            },
        )
        self._assert(
            "platform engineering" not in weak_eval.explanation.lower()
            or "No verified evidence matched the job signals." in weak_eval.explanation,
            phase,
            "unrelated role does not receive unsupported technical matches",
            endpoint="POST /api/v1/job-leads/{job_id}/evaluations",
            expected="no unsupported platform-specific match on weak role",
            actual=weak_eval.explanation,
        )
        self._assert(
            all(
                evaluation.scoring_version == SCORING_VERSION
                for evaluation in [strong_eval, partial_eval, weak_eval]
            ),
            phase,
            "expected scoring version is used",
            endpoint="POST /api/v1/job-leads/{job_id}/evaluations",
            expected=SCORING_VERSION,
            actual=[
                strong_eval.scoring_version,
                partial_eval.scoring_version,
                weak_eval.scoring_version,
            ],
        )
        self._record_pass(phase, "comparative evaluations validated")

    def _phase_document_ingestion(self) -> None:
        phase = "phase_11_document_ingestion"
        content = (
            f"{BOOTSTRAP_OWNER} document fixture. Led platform work with Kubernetes and "
            f"developer productivity improvements at {time.time_ns()}."
        ).encode()
        document = self.client.upload_document("bootstrap-career-notes.txt", content)
        self.metadata.created_ids["document:accepted"] = document.id

        duplicate_response, duplicate_body = self.client._request(
            "POST",
            "/api/v1/documents",
            data={"source_type": "career_notes", "upload_note": BOOTSTRAP_OWNER},
            files={"document_file": ("bootstrap-career-notes-copy.txt", content, "text/plain")},
        )
        self._assert(
            duplicate_response.status_code == 409,
            phase,
            "duplicate document upload is rejected",
            endpoint="POST /api/v1/documents",
            expected=409,
            actual=duplicate_response.status_code,
            response=duplicate_body,
        )

        run = self.client.extract_document(document.id)
        self._assert(
            run.status == "succeeded" and run.prompt_version == "career_fact_extraction_v1",
            phase,
            "fake extraction run succeeds and records prompt version",
            endpoint=f"POST /api/v1/documents/{document.id}/extractions",
            expected="succeeded with prompt version",
            actual=run.model_dump(mode="json"),
        )
        pending = self.client.list_proposals(review_status="pending")
        self._assert(
            bool(pending),
            phase,
            "extraction creates pending proposals",
            endpoint="GET /api/v1/fact-proposals?review_status=pending",
            expected="at least one pending proposal",
            actual=[],
        )
        accepted = self.client.accept_proposal(pending[0].id)
        self._assert(
            accepted.review_status == "accepted" and accepted.accepted_career_fact_id is not None,
            phase,
            "accepted proposal links to draft career fact",
            endpoint=f"POST /api/v1/fact-proposals/{pending[0].id}/accept",
            expected="accepted with career fact linkage",
            actual=accepted.model_dump(mode="json"),
        )
        accepted_fact_id = accepted.accepted_career_fact_id
        if accepted_fact_id is None:
            raise HarnessError(
                phase,
                "accepted proposal did not include career fact linkage",
                endpoint=f"POST /api/v1/fact-proposals/{pending[0].id}/accept",
                expected="accepted_career_fact_id",
                actual=None,
                response_body=accepted.model_dump(mode="json"),
            )
        accepted_fact = self.client.get_fact(accepted_fact_id)
        self._assert(
            accepted_fact.lifecycle_status == CareerFactLifecycle.DRAFT,
            phase,
            "accepted proposal creates a draft fact, not verified evidence",
            endpoint=f"GET /api/v1/career-facts/{accepted.accepted_career_fact_id}",
            expected="draft",
            actual=accepted_fact.lifecycle_status.value,
            response=accepted_fact.model_dump(mode="json"),
        )

        reject_content = f"{BOOTSTRAP_OWNER} reject fixture {time.time_ns()}.".encode()
        reject_document = self.client.upload_document("bootstrap-reject-notes.txt", reject_content)
        self.client.extract_document(reject_document.id)
        reject_pending = self.client.list_proposals(review_status="pending")
        self._assert(
            bool(reject_pending),
            phase,
            "second extraction creates a proposal for rejection",
            endpoint="GET /api/v1/fact-proposals?review_status=pending",
            expected="at least one pending proposal",
            actual=[],
        )
        rejected = self.client.reject_proposal(reject_pending[0].id)
        self._assert(
            rejected.review_status == "rejected",
            phase,
            "proposal rejection persists review state",
            endpoint=f"POST /api/v1/fact-proposals/{reject_pending[0].id}/reject",
            expected="rejected",
            actual=rejected.review_status,
            response=rejected.model_dump(mode="json"),
        )

        chunk_limit_content = b"\n\n".join([b"A" * 7000 for _ in range(9)])
        chunk_limit_document = self.client.upload_document(
            "bootstrap-chunk-limit.txt", chunk_limit_content
        )
        status_code, failure_body = self.client.extract_document_expect_failure(
            chunk_limit_document.id
        )
        self._assert(
            status_code == 422
            and failure_body["error"]["code"] == "document_extraction_limit_exceeded",
            phase,
            "chunk limit failure returns a structured error without partial extraction",
            endpoint=f"POST /api/v1/documents/{chunk_limit_document.id}/extractions",
            expected={"status": 422, "code": "document_extraction_limit_exceeded"},
            actual={"status": status_code, "body": failure_body},
        )
        self._record_pass(phase, "document ingestion acceptance flow validated")

    def _phase_fake_greenhouse_import(self) -> None:
        phase = "phase_12_fake_greenhouse_import"
        fixture_path = self.config.fake_greenhouse_fixture_path
        if fixture_path is None:
            raise HarnessError(
                phase,
                "fake Greenhouse phase requires a fixture path shared with the server",
                endpoint="cli",
                expected="--fake-greenhouse-fixture-path or GREENHOUSE_FAKE_FIXTURE_PATH",
                actual=None,
            )
        self._write_greenhouse_fixture(
            fixture_path,
            [self._fake_job("strong")],
            board_token="bootstrap-detect",
            company_name="Bootstrap Detect",
        )
        detection = self.client.create_source_detection(
            SourceDetectionRunPayload(company_name="Bootstrap Detect LLC")
        )
        self._assert(
            detection.status == "detected"
            and detection.validated_token == "bootstrap-detect"
            and detection.validated_job_count == 1,
            phase,
            "fake detection validates generated Greenhouse token and previews job count",
            endpoint="POST /api/v1/source-detections",
            expected={"status": "detected", "token": "bootstrap-detect", "jobs": 1},
            actual=detection.model_dump(mode="json"),
        )
        approval = self.client.approve_source_detection(detection.id)
        self._assert(
            approval.source.board_token == "bootstrap-detect"
            and approval.run.status == "source_created",
            phase,
            "fake detection approval creates source explicitly",
            endpoint=f"POST /api/v1/source-detections/{detection.id}/approve",
            expected={"source_token": "bootstrap-detect", "run_status": "source_created"},
            actual=approval.model_dump(mode="json"),
        )
        rerun_detection = self.client.create_source_detection(
            SourceDetectionRunPayload(company_name="Bootstrap Detect LLC")
        )
        existing_ids = {
            candidate.get("existing_source_configuration_id")
            for candidate in rerun_detection.candidate_tokens
        }
        self._assert(
            approval.source.id in existing_ids,
            phase,
            "rerun detection identifies existing source",
            endpoint="POST /api/v1/source-detections",
            expected=approval.source.id,
            actual=rerun_detection.model_dump(mode="json"),
        )
        ambiguous_fixture = {
            "ambiguousco": {"company_name": "Ambiguous Co", "jobs": [self._fake_job("strong")]},
            "ambiguous-co": {"company_name": "Ambiguous Co", "jobs": [self._fake_job("weak")]},
        }
        self._write_greenhouse_fixture(
            fixture_path,
            [self._fake_job("strong")],
            valid_tokens=ambiguous_fixture,
        )
        ambiguous = self.client.create_source_detection(
            SourceDetectionRunPayload(company_name="Ambiguous Co")
        )
        self._assert(
            ambiguous.status == "ambiguous"
            and len([c for c in ambiguous.candidate_tokens if c.get("validation", {}).get("valid")])
            > 1,
            phase,
            "ambiguous fake detection returns multiple validated candidates",
            endpoint="POST /api/v1/source-detections",
            expected="ambiguous with multiple valid candidates",
            actual=ambiguous.model_dump(mode="json"),
        )
        unsafe = self.client.create_source_detection(
            SourceDetectionRunPayload(input_url="http://127.0.0.1/careers")
        )
        self._assert(
            unsafe.status == "failed" and bool(unsafe.error_message),
            phase,
            "unsafe URL detection is rejected and persisted terminally",
            endpoint="POST /api/v1/source-detections",
            expected="failed terminal detection",
            actual=unsafe.model_dump(mode="json"),
        )
        self._write_greenhouse_fixture(
            fixture_path,
            [self._fake_job("strong")],
            board_token="bootstrap-sync-detect",
            company_name="Bootstrap Sync Detect",
        )
        sync_detection = self.client.create_source_detection(
            SourceDetectionRunPayload(company_name="Bootstrap Sync Detect")
        )
        sync_approval = self.client.approve_source_detection(
            sync_detection.id, create_and_sync=True
        )
        self._assert(
            sync_approval.import_run is not None and sync_approval.import_run.jobs_fetched == 1,
            phase,
            "create-and-sync detection approval invokes fake Greenhouse import",
            endpoint=f"POST /api/v1/source-detections/{sync_detection.id}/approve",
            expected={"import_jobs_fetched": 1},
            actual=sync_approval.model_dump(mode="json"),
        )

        source = self._ensure_fake_greenhouse_source()

        self._write_greenhouse_fixture(
            fixture_path,
            [self._fake_job("strong"), self._fake_job("weak")],
            board_token="bootstrap-fake-greenhouse",
        )
        first_run = self.client.sync_job_source(source.id)
        self._assert(
            first_run.status == "succeeded"
            and first_run.jobs_fetched == 2
            and first_run.jobs_created + first_run.jobs_updated + first_run.jobs_unchanged == 2,
            phase,
            "first fake import materializes jobs",
            endpoint=f"POST /api/v1/job-sources/{source.id}/imports",
            expected={"status": "succeeded", "jobs_fetched": 2, "materialized": 2},
            actual=first_run.model_dump(mode="json"),
        )

        identical_run = self.client.sync_job_source(source.id)
        self._assert(
            identical_run.jobs_unchanged == 2 and identical_run.evaluations_created == 0,
            phase,
            "identical fake import creates no duplicates",
            endpoint=f"POST /api/v1/job-sources/{source.id}/imports",
            expected={"jobs_unchanged": 2, "evaluations_created": 0},
            actual=identical_run.model_dump(mode="json"),
        )

        changed_strong = self._fake_job("strong")
        changed_strong["description_normalized"] += (
            " Own developer productivity, observability, and manager-of-managers scope."
        )
        self._write_greenhouse_fixture(
            fixture_path,
            [changed_strong, self._fake_job("weak")],
            board_token="bootstrap-fake-greenhouse",
        )
        changed_run = self.client.sync_job_source(source.id)
        self._assert(
            changed_run.jobs_updated == 1 and changed_run.evaluations_created == 1,
            phase,
            "changed fake job updates and reevaluates",
            endpoint=f"POST /api/v1/job-sources/{source.id}/imports",
            expected={"jobs_updated": 1, "evaluations_created": 1},
            actual=changed_run.model_dump(mode="json"),
        )

        self._write_greenhouse_fixture(
            fixture_path,
            [changed_strong],
            board_token="bootstrap-fake-greenhouse",
        )
        closure_run = self.client.sync_job_source(source.id)
        self._assert(
            closure_run.jobs_closed == 1,
            phase,
            "missing fake job closes after successful import",
            endpoint=f"POST /api/v1/job-sources/{source.id}/imports",
            expected={"jobs_closed": 1},
            actual=closure_run.model_dump(mode="json"),
        )

        self._write_greenhouse_fixture(
            fixture_path,
            [],
            error="simulated fake Greenhouse outage",
            board_token="bootstrap-fake-greenhouse",
        )
        failed_run = self.client.sync_job_source(source.id)
        active_after_failure = self.client.list_discovered_leads(source_id=source.id)
        self._assert(
            failed_run.status == "failed" and len(active_after_failure) == 1,
            phase,
            "failed fake import closes nothing",
            endpoint=f"POST /api/v1/job-sources/{source.id}/imports",
            expected={"status": "failed", "active_count": 1},
            actual={
                "run": failed_run.model_dump(mode="json"),
                "active_count": len(active_after_failure),
            },
        )

        self._write_greenhouse_fixture(
            fixture_path,
            [changed_strong, self._fake_job("weak")],
            board_token="bootstrap-fake-greenhouse",
        )
        reappear_run = self.client.sync_job_source(source.id)
        queue = self.client.list_discovered_leads(source_id=source.id)
        self._assert(
            reappear_run.jobs_updated == 1 and len(queue) == 2,
            phase,
            "reappearing fake job reactivates",
            endpoint=f"POST /api/v1/job-sources/{source.id}/imports",
            expected={"jobs_updated": 1, "active_count": 2},
            actual={"run": reappear_run.model_dump(mode="json"), "active_count": len(queue)},
        )
        self._assert(
            queue[0].external_post_id == "strong"
            and queue[0].latest_evaluation is not None
            and (
                queue[1].latest_evaluation is None
                or queue[0].latest_evaluation.overall_score
                >= queue[1].latest_evaluation.overall_score
            ),
            phase,
            "ranked queue places strong fake match above weak match",
            endpoint="GET /api/v1/discovered-leads",
            expected="strong before weak",
            actual=[
                {
                    "external_post_id": item.external_post_id,
                    "score": (
                        item.latest_evaluation.overall_score if item.latest_evaluation else None
                    ),
                }
                for item in queue
            ],
        )
        self._record_pass(phase, "fake Greenhouse import acceptance flow validated")

    def _ensure_fake_greenhouse_source(self) -> JobSourceConfigurationResponse:
        board_token = "bootstrap-fake-greenhouse"
        for source in self.client.list_job_sources():
            if source.provider == "greenhouse" and source.board_token == board_token:
                return source
        source = self.client.create_job_source(
            JobSourceConfigurationPayload(
                display_name="Bootstrap Fake Greenhouse",
                company_name="Bootstrap Greenhouse",
                board_token=board_token,
                source_url="https://boards.greenhouse.io/bootstrap-fake-greenhouse",
            )
        )
        self.metadata.created_ids["job_source:fake_greenhouse"] = source.id
        return source

    def _write_greenhouse_fixture(
        self,
        fixture_path: Path,
        jobs: list[dict[str, Any]],
        *,
        error: str | None = None,
        board_token: str | None = None,
        company_name: str | None = None,
        valid_tokens: dict[str, dict[str, Any]] | None = None,
    ) -> None:
        fixture_path.parent.mkdir(parents=True, exist_ok=True)
        payload: dict[str, Any] = {"jobs": jobs}
        if board_token is not None:
            payload["board_token"] = board_token
        if company_name is not None:
            payload["company_name"] = company_name
        if valid_tokens is not None:
            payload["valid_tokens"] = valid_tokens
        if error is not None:
            payload["error"] = error
        fixture_path.write_text(json.dumps(payload), encoding="utf-8")

    def _fake_job(self, key: str) -> dict[str, Any]:
        if key == "strong":
            return {
                "external_id": "strong",
                "internal_job_id": "req-strong",
                "company_name": "Bootstrap Greenhouse",
                "title": "Senior Director, Platform Engineering",
                "location_text": "Remote",
                "workplace_type": "remote",
                "description_raw": "Lead platform engineering and developer experience.",
                "description_normalized": (
                    "Lead platform engineering, developer platform strategy, Kubernetes, "
                    "CI/CD, observability, cloud reliability, and engineering managers."
                ),
                "compensation_text": "$280k",
                "source_url": "https://boards.greenhouse.io/bootstrap/jobs/strong",
            }
        return {
            "external_id": "weak",
            "internal_job_id": "req-weak",
            "company_name": "Bootstrap Greenhouse",
            "title": "Finance Operations Manager",
            "location_text": "Austin, TX",
            "workplace_type": "onsite",
            "description_raw": "Own finance operations reporting.",
            "description_normalized": (
                "Own finance operations reporting and vendor invoice workflows."
            ),
            "compensation_text": "$160k",
            "source_url": "https://boards.greenhouse.io/bootstrap/jobs/weak",
        }

    def _fact_by_key(self, key: str) -> CareerFactResponse:
        for fact in self.client.list_facts(include_archived=True):
            if fact.source_reference == _fact_definitions()[key].source_reference:
                return fact
        raise HarnessError(
            "facts",
            "expected bootstrap fact not found",
            endpoint="GET /api/v1/career-facts",
            expected=_fact_definitions()[key].source_reference,
            actual="missing",
        )
