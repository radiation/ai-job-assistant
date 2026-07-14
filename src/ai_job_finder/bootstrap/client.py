from __future__ import annotations

import json
import time
from typing import Any

import httpx

from ai_job_finder.bootstrap.contracts import (
    CandidatePayload,
    CandidateResponse,
    CareerFactLifecycle,
    CareerFactPayload,
    CareerFactProposalResponse,
    CareerFactResponse,
    DiscoveredLeadResponse,
    ExtractionRunResponse,
    HarnessError,
    HealthResponse,
    JobEvaluationResponse,
    JobImportRunResponse,
    JobLeadPayload,
    JobLeadResponse,
    JobSourceConfigurationPayload,
    JobSourceConfigurationResponse,
    ResetResponse,
    SourceDetectionApprovalResponse,
    SourceDetectionRunPayload,
    SourceDetectionRunResponse,
    SourceDocumentResponse,
)
from ai_job_finder.bootstrap.fixtures import (
    BOOTSTRAP_OWNER,
    BOOTSTRAP_SOURCE_PREFIX,
    _bootstrap_candidate,
)


def is_localhost_url(base_url: str) -> bool:
    host = httpx.URL(base_url).host or ""
    return host in {"localhost", "127.0.0.1"}


def is_bootstrap_owned_candidate(candidate: CandidateResponse) -> bool:
    return candidate.full_name == _bootstrap_candidate().full_name


def is_bootstrap_owned_fact(fact: CareerFactResponse) -> bool:
    return fact.source_reference.startswith(BOOTSTRAP_SOURCE_PREFIX)


def parse_json_body(response: httpx.Response) -> Any:
    if not response.content:
        return None
    try:
        return response.json()
    except json.JSONDecodeError:
        return response.text


class ApiClient:
    def __init__(self, base_url: str, timeout: float, *, verbose: bool = False) -> None:
        self.base_url = base_url.rstrip("/")
        self.verbose = verbose
        self.client = httpx.Client(base_url=self.base_url, timeout=timeout)

    def close(self) -> None:
        self.client.close()

    def wait_until_ready(self, timeout_seconds: float) -> None:
        deadline = time.monotonic() + timeout_seconds
        last_error: str | None = None
        while time.monotonic() < deadline:
            try:
                response = self.client.get("/api/v1/health")
                body = parse_json_body(response)
                if response.status_code == 200:
                    HealthResponse.model_validate(body)
                    return
                last_error = f"status={response.status_code} body={body}"
            except httpx.HTTPError as exc:
                last_error = str(exc)
            time.sleep(1)
        raise HarnessError(
            "readiness",
            "application readiness check failed",
            endpoint="GET /api/v1/health",
            expected="200 with {status: ok}",
            actual=last_error,
        )

    def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        try:
            response = self.client.request(method, path, **kwargs)
        except httpx.HTTPError as exc:
            raise HarnessError(
                "http",
                "request failed",
                endpoint=f"{method} {path}",
                expected="successful HTTP response",
                actual=str(exc),
            ) from exc
        body = parse_json_body(response)
        if self.verbose:
            print(f"HTTP {method} {path} -> {response.status_code}")
        return response, body

    def get_health(self) -> HealthResponse:
        response, body = self._request("GET", "/api/v1/health")
        self._assert_status("readiness", "health endpoint returns ok", response, 200, body)
        return HealthResponse.model_validate(body)

    def get_candidate(self) -> CandidateResponse | None:
        response, body = self._request("GET", "/api/v1/candidate-profile")
        if response.status_code == 404:
            return None
        self._assert_status("candidate", "candidate lookup succeeds", response, 200, body)
        return CandidateResponse.model_validate(body)

    def create_candidate(self, payload: CandidatePayload) -> CandidateResponse:
        response, body = self._request(
            "POST", "/api/v1/candidate-profile", json=payload.model_dump(mode="json")
        )
        self._assert_status("candidate", "candidate create succeeds", response, 201, body)
        return CandidateResponse.model_validate(body)

    def update_candidate(self, payload: CandidatePayload) -> CandidateResponse:
        response, body = self._request(
            "PUT", "/api/v1/candidate-profile", json=payload.model_dump(mode="json")
        )
        self._assert_status("candidate", "candidate update succeeds", response, 200, body)
        return CandidateResponse.model_validate(body)

    def reset_candidate(self) -> ResetResponse:
        response, body = self._request("POST", "/api/v1/dev/reset-candidate-profile")
        self._assert_status("candidate", "candidate reset succeeds", response, 200, body)
        return ResetResponse.model_validate(body)

    def list_facts(self, **params: Any) -> list[CareerFactResponse]:
        response, body = self._request("GET", "/api/v1/career-facts", params=params)
        self._assert_status("facts", "career facts list succeeds", response, 200, body)
        return [CareerFactResponse.model_validate(item) for item in body]

    def create_fact(self, payload: CareerFactPayload) -> CareerFactResponse:
        response, body = self._request(
            "POST", "/api/v1/career-facts", json=payload.model_dump(mode="json")
        )
        self._assert_status("facts", "career fact create succeeds", response, 201, body)
        return CareerFactResponse.model_validate(body)

    def get_fact(self, fact_id: str) -> CareerFactResponse:
        response, body = self._request("GET", f"/api/v1/career-facts/{fact_id}")
        self._assert_status("facts", "career fact lookup succeeds", response, 200, body)
        return CareerFactResponse.model_validate(body)

    def update_fact(self, fact_id: str, payload: CareerFactPayload) -> CareerFactResponse:
        response, body = self._request(
            "PUT", f"/api/v1/career-facts/{fact_id}", json=payload.model_dump(mode="json")
        )
        self._assert_status("facts", "career fact update succeeds", response, 200, body)
        return CareerFactResponse.model_validate(body)

    def transition_fact(
        self, fact_id: str, lifecycle_status: CareerFactLifecycle
    ) -> CareerFactResponse:
        response, body = self._request(
            "POST",
            f"/api/v1/career-facts/{fact_id}/transitions",
            json={"lifecycle_status": lifecycle_status.value},
        )
        self._assert_status("facts", "career fact transition succeeds", response, 200, body)
        return CareerFactResponse.model_validate(body)

    def list_jobs(self, **params: Any) -> list[JobLeadResponse]:
        response, body = self._request("GET", "/api/v1/job-leads", params=params)
        self._assert_status("jobs", "job list succeeds", response, 200, body)
        return [JobLeadResponse.model_validate(item) for item in body]

    def create_job(self, payload: JobLeadPayload) -> JobLeadResponse:
        response, body = self._request(
            "POST", "/api/v1/job-leads", json=payload.model_dump(mode="json")
        )
        self._assert_status("jobs", "job create succeeds", response, 201, body)
        return JobLeadResponse.model_validate(body)

    def update_job(self, job_id: str, payload: JobLeadPayload) -> JobLeadResponse:
        update_payload = payload.model_dump(mode="json")
        update_payload.pop("source")
        update_payload.pop("external_id")
        response, body = self._request("PUT", f"/api/v1/job-leads/{job_id}", json=update_payload)
        self._assert_status("jobs", "job update succeeds", response, 200, body)
        return JobLeadResponse.model_validate(body)

    def create_evaluation(self, job_id: str, candidate_id: str) -> JobEvaluationResponse:
        response, body = self._request(
            "POST",
            f"/api/v1/job-leads/{job_id}/evaluations",
            json={"candidate_profile_id": candidate_id},
        )
        self._assert_status("evaluations", "evaluation create succeeds", response, 201, body)
        return JobEvaluationResponse.model_validate(body)

    def upload_document(self, filename: str, content: bytes) -> SourceDocumentResponse:
        response, body = self._request(
            "POST",
            "/api/v1/documents",
            data={"source_type": "career_notes", "upload_note": BOOTSTRAP_OWNER},
            files={"document_file": (filename, content, "text/plain")},
        )
        self._assert_status("documents", "document upload succeeds", response, 201, body)
        return SourceDocumentResponse.model_validate(body)

    def extract_document(self, document_id: str) -> ExtractionRunResponse:
        response, body = self._request("POST", f"/api/v1/documents/{document_id}/extractions")
        self._assert_status("documents", "document extraction succeeds", response, 200, body)
        return ExtractionRunResponse.model_validate(body)

    def extract_document_expect_failure(self, document_id: str) -> tuple[int, Any]:
        response, body = self._request("POST", f"/api/v1/documents/{document_id}/extractions")
        return response.status_code, body

    def list_proposals(self, **params: Any) -> list[CareerFactProposalResponse]:
        response, body = self._request("GET", "/api/v1/fact-proposals", params=params)
        self._assert_status("proposals", "proposal list succeeds", response, 200, body)
        return [CareerFactProposalResponse.model_validate(item) for item in body]

    def accept_proposal(self, proposal_id: str) -> CareerFactProposalResponse:
        response, body = self._request("POST", f"/api/v1/fact-proposals/{proposal_id}/accept")
        self._assert_status("proposals", "proposal accept succeeds", response, 200, body)
        return CareerFactProposalResponse.model_validate(body)

    def reject_proposal(self, proposal_id: str) -> CareerFactProposalResponse:
        response, body = self._request("POST", f"/api/v1/fact-proposals/{proposal_id}/reject")
        self._assert_status("proposals", "proposal reject succeeds", response, 200, body)
        return CareerFactProposalResponse.model_validate(body)

    def list_evaluations(self, job_id: str) -> list[JobEvaluationResponse]:
        response, body = self._request("GET", f"/api/v1/job-leads/{job_id}/evaluations")
        self._assert_status("evaluations", "evaluation history succeeds", response, 200, body)
        return [JobEvaluationResponse.model_validate(item) for item in body]

    def list_job_sources(self) -> list[JobSourceConfigurationResponse]:
        response, body = self._request("GET", "/api/v1/job-sources")
        self._assert_status("job_sources", "job source list succeeds", response, 200, body)
        return [JobSourceConfigurationResponse.model_validate(item) for item in body]

    def create_job_source(
        self, payload: JobSourceConfigurationPayload
    ) -> JobSourceConfigurationResponse:
        response, body = self._request(
            "POST", "/api/v1/job-sources", json=payload.model_dump(mode="json")
        )
        self._assert_status("job_sources", "job source create succeeds", response, 201, body)
        return JobSourceConfigurationResponse.model_validate(body)

    def sync_job_source(self, source_id: str) -> JobImportRunResponse:
        response, body = self._request("POST", f"/api/v1/job-sources/{source_id}/imports")
        self._assert_status("job_import", "job source import trigger succeeds", response, 201, body)
        return JobImportRunResponse.model_validate(body)

    def create_source_detection(
        self, payload: SourceDetectionRunPayload
    ) -> SourceDetectionRunResponse:
        response, body = self._request(
            "POST", "/api/v1/source-detections", json=payload.model_dump(mode="json")
        )
        self._assert_status(
            "source_detection", "source detection create succeeds", response, 201, body
        )
        return SourceDetectionRunResponse.model_validate(body)

    def approve_source_detection(
        self,
        run_id: str,
        *,
        selected_token: str | None = None,
        create_and_sync: bool = False,
    ) -> SourceDetectionApprovalResponse:
        response, body = self._request(
            "POST",
            f"/api/v1/source-detections/{run_id}/approve",
            json={"selected_token": selected_token, "create_and_sync": create_and_sync},
        )
        self._assert_status(
            "source_detection",
            "source detection approval succeeds",
            response,
            200,
            body,
        )
        return SourceDetectionApprovalResponse.model_validate(body)

    def list_discovered_leads(self, **params: Any) -> list[DiscoveredLeadResponse]:
        response, body = self._request("GET", "/api/v1/discovered-leads", params=params)
        self._assert_status("discovery", "discovered leads list succeeds", response, 200, body)
        return [DiscoveredLeadResponse.model_validate(item) for item in body]

    def _assert_status(
        self,
        phase: str,
        assertion: str,
        response: httpx.Response,
        expected_status: int,
        body: Any,
    ) -> None:
        if response.status_code != expected_status:
            raise HarnessError(
                phase,
                assertion,
                endpoint=f"{response.request.method} {response.request.url.path}",
                expected=expected_status,
                actual=response.status_code,
                response_body=body,
            )
