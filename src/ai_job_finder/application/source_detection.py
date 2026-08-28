from __future__ import annotations

import json
import re
from collections import OrderedDict
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urljoin, urlsplit
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from ai_job_finder.application.job_sources import (
    create_job_source_configuration,
    run_job_source_import,
)
from ai_job_finder.domain.common import new_uuid, utc_now
from ai_job_finder.domain.enums import JobSourceProvider, SourceDetectionRunStatus
from ai_job_finder.domain.errors import (
    AmbiguousSourceDetectionError,
    DomainError,
    DuplicateJobSourceError,
    GreenhouseValidationUnavailableError,
    NoProviderDetectedError,
    NotFoundError,
    SourceDetectionApprovalError,
    SourceSyncAfterCreationError,
)
from ai_job_finder.domain.job_discovery.targeting import (
    GREENHOUSE_HOSTS,
    parse_supported_ats_url,
)
from ai_job_finder.domain.job_sources import JobSourceConnector
from ai_job_finder.domain.source_detection import (
    JobSourceBoardValidation,
    JobSourceBoardValidator,
    PublicPage,
    PublicPageFetcher,
)
from ai_job_finder.infrastructure.database.models import (
    JobImportRunModel,
    JobSourceConfigurationModel,
    SourceDetectionRunModel,
)

TOKEN_PATTERN = r"[A-Za-z0-9][A-Za-z0-9_-]{1,199}"
EXCLUDED_TOKENS = {
    "api",
    "boards",
    "departments",
    "embed",
    "greenhouse",
    "jobs",
    "offices",
    "v1",
}
LEGAL_SUFFIXES = {
    "co",
    "company",
    "corp",
    "corporation",
    "gmbh",
    "inc",
    "incorporated",
    "llc",
    "ltd",
    "limited",
    "plc",
}


class _PublicPageSignalParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.urls: list[tuple[str, str]] = []
        self.json_ld_documents: list[str] = []
        self._in_json_ld_script = False
        self._json_ld_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = {name.casefold(): value for name, value in attrs if value is not None}
        if tag.casefold() == "script":
            script_type = (attributes.get("type") or "").casefold().split(";", 1)[0].strip()
            self._in_json_ld_script = script_type == "application/ld+json"
            self._json_ld_parts = []
            return
        for attribute in ("href", "action"):
            value = attributes.get(attribute)
            if value:
                category = "supported_ats_link"
                if (
                    tag.casefold() == "link"
                    and "canonical" in (attributes.get("rel") or "").casefold().split()
                ):
                    category = "canonical_supported_ats_url"
                elif tag.casefold() == "form":
                    category = "application_supported_ats_url"
                self.urls.append((value, category))
        if tag.casefold() == "meta":
            value = attributes.get("content")
            if value:
                self.urls.append((value, "metadata_supported_ats_url"))

    def handle_data(self, data: str) -> None:
        if self._in_json_ld_script:
            self._json_ld_parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.casefold() == "script" and self._in_json_ld_script:
            self.json_ld_documents.append("".join(self._json_ld_parts))
            self._in_json_ld_script = False
            self._json_ld_parts = []


@dataclass(frozen=True, slots=True)
class SourceDetectionApprovalResult:
    run: SourceDetectionRunModel
    source: JobSourceConfigurationModel
    import_run: JobImportRunModel | None = None
    existing_source: bool = False


@dataclass(frozen=True, slots=True)
class SourceDetectionConfig:
    max_linked_scripts: int
    max_script_bytes: int
    total_script_bytes: int


def create_source_detection_run(
    session: Session,
    *,
    company_name: str | None,
    input_url: str | None,
    brand_alias: str | None,
    fetcher: PublicPageFetcher,
    board_validator: JobSourceBoardValidator,
    config: SourceDetectionConfig,
) -> SourceDetectionRunModel:
    company = _optional_str(company_name)
    url = _optional_str(input_url)
    alias = _optional_str(brand_alias)
    if company is None and url is None:
        raise NoProviderDetectedError("Provide at least a company name or careers URL.")

    run = SourceDetectionRunModel(
        id=new_uuid(),
        company_name=company,
        input_url=url,
        normalized_url=None,
        final_url=None,
        status=SourceDetectionRunStatus.RUNNING.value,
        candidate_tokens=[],
        evidence=[],
        started_at=utc_now(),
    )
    session.add(run)
    session.commit()

    try:
        outcome = _detect(
            session,
            company_name=company,
            input_url=url,
            brand_alias=alias,
            fetcher=fetcher,
            board_validator=board_validator,
            config=config,
        )
        _finalize_run(session, run, **outcome)
    except DomainError as exc:
        session.rollback()
        run = session.get(SourceDetectionRunModel, run.id) or run
        _finalize_run(
            session,
            run,
            status=SourceDetectionRunStatus.FAILED,
            normalized_url=None,
            final_url=None,
            detected_provider=None,
            candidate_tokens=[],
            evidence=[],
            validated_token=None,
            validated_company_name=None,
            validated_job_count=None,
            error_message=str(exc),
        )
    except Exception as exc:
        session.rollback()
        run = session.get(SourceDetectionRunModel, run.id) or run
        _finalize_run(
            session,
            run,
            status=SourceDetectionRunStatus.FAILED,
            normalized_url=None,
            final_url=None,
            detected_provider=None,
            candidate_tokens=[],
            evidence=[],
            validated_token=None,
            validated_company_name=None,
            validated_job_count=None,
            error_message="Unexpected source detection failure.",
        )
        exc.add_note(f"source_detection_run_id={run.id}")
    session.refresh(run)
    return run


def list_source_detection_runs(session: Session) -> list[SourceDetectionRunModel]:
    return list(
        session.scalars(
            select(SourceDetectionRunModel).order_by(SourceDetectionRunModel.created_at.desc())
        )
    )


def get_source_detection_run(session: Session, run_id: UUID) -> SourceDetectionRunModel:
    run = session.get(SourceDetectionRunModel, run_id)
    if run is None:
        raise NotFoundError(f"Source detection run {run_id} was not found.")
    return run


def validate_greenhouse_token(
    session: Session,
    *,
    board_token: str,
    board_validator: JobSourceBoardValidator,
) -> dict[str, Any]:
    token = _normalize_token(board_token)
    if token is None:
        raise NoProviderDetectedError("Provide a Greenhouse board token to validate.")
    validation = board_validator.validate(JobSourceProvider.GREENHOUSE, token)
    if validation.status == "unavailable":
        raise GreenhouseValidationUnavailableError(
            validation.error_message or "Greenhouse validation is unavailable."
        )
    return _candidate_payload(
        provider=JobSourceProvider.GREENHOUSE,
        token=token,
        source="manual",
        evidence_categories=["manual_token"],
        validation=validation,
        existing_source=_source_by_token(session, token),
        selected_external_posting_id=None,
    )


def approve_source_detection_run(
    session: Session,
    *,
    run_id: UUID,
    selected_token: str | None,
    selected_provider: JobSourceProvider | None = None,
    create_and_sync: bool,
    connector: JobSourceConnector,
    retain_raw_payload: bool,
    close_on_empty: bool,
    stale_after_seconds: int,
) -> SourceDetectionApprovalResult:
    run = get_source_detection_run(session, run_id)
    selected_candidate = _selected_valid_candidate(run, selected_token, selected_provider)
    token = str(selected_candidate["token"])
    provider = JobSourceProvider(
        str(
            selected_candidate.get("provider")
            or run.detected_provider
            or JobSourceProvider.GREENHOUSE.value
        )
    )
    existing_source = _source_by_token(session, token, provider=provider)
    source_existed = existing_source is not None
    source = existing_source
    if source is None:
        try:
            source = create_job_source_configuration(
                session,
                provider=provider.value,
                display_name=_display_name(run, token),
                company_name=run.validated_company_name or run.company_name or token,
                board_token=token,
                source_url=run.final_url or run.input_url,
                enabled=True,
            )
        except DuplicateJobSourceError:
            source = _source_by_token(session, token, provider=provider)
            if source is None:
                raise
            source_existed = True
    run.created_source_configuration_id = source.id
    run.status = SourceDetectionRunStatus.SOURCE_CREATED.value
    run.completed_at = run.completed_at or utc_now()
    session.add(run)
    session.commit()
    session.refresh(run)

    import_run = None
    if create_and_sync:
        try:
            import_run = run_job_source_import(
                session,
                source_id=source.id,
                connector=connector,
                retain_raw_payload=retain_raw_payload,
                close_on_empty=close_on_empty,
                stale_after_seconds=stale_after_seconds,
            )
        except Exception as exc:
            raise SourceSyncAfterCreationError(
                "Source was created, but the immediate sync failed."
            ) from exc
    return SourceDetectionApprovalResult(
        run=run,
        source=source,
        import_run=import_run,
        existing_source=source_existed,
    )


def _detect(
    session: Session,
    *,
    company_name: str | None,
    input_url: str | None,
    brand_alias: str | None,
    fetcher: PublicPageFetcher,
    board_validator: JobSourceBoardValidator,
    config: SourceDetectionConfig,
) -> dict[str, Any]:
    evidence: list[dict[str, Any]] = []
    observed_candidates: OrderedDict[tuple[JobSourceProvider, str], set[str]] = OrderedDict()
    normalized_url = None
    final_url = None
    page: PublicPage | None = None
    if input_url:
        canonical_url = parse_supported_ats_url(input_url)
        if canonical_url is not None:
            provider = canonical_url.provider
            validation = board_validator.validate(provider, canonical_url.board_token)
            candidate = _candidate_payload(
                provider=provider,
                token=canonical_url.board_token,
                source="canonical_url",
                evidence_categories=[f"canonical_{provider.value}_url"],
                validation=validation,
                existing_source=_source_by_token(
                    session, canonical_url.board_token, provider=provider
                ),
                selected_external_posting_id=canonical_url.external_posting_id,
            )
            return {
                "status": (
                    SourceDetectionRunStatus.DETECTED
                    if validation.valid
                    else SourceDetectionRunStatus.NOT_DETECTED
                ),
                "normalized_url": input_url,
                "final_url": input_url,
                "detected_provider": provider.value if validation.valid else None,
                "candidate_tokens": [candidate],
                "evidence": [
                    {
                        "category": f"canonical_{provider.value}_url",
                        "token": canonical_url.board_token,
                        "external_posting_id": canonical_url.external_posting_id,
                        "source": "url",
                        "source_url": input_url,
                    }
                ],
                "validated_token": canonical_url.board_token if validation.valid else None,
                "validated_company_name": validation.company_name or company_name,
                "validated_job_count": validation.job_count,
                "error_message": validation.error_message,
            }
        page = fetcher.fetch(input_url)
        normalized_url = page.requested_url
        final_url = page.final_url
        redirect_target = parse_supported_ats_url(page.final_url)
        if redirect_target is not None:
            _merge_candidate_evidence(
                observed_candidates,
                evidence,
                [
                    _supported_url_evidence(
                        redirect_target,
                        category="redirected_supported_ats_url",
                        source="redirect",
                        source_url=page.final_url,
                    )
                ],
            )
        _merge_candidate_evidence(
            observed_candidates,
            evidence,
            _extract_public_page_supported_candidates(page),
        )
        _merge_candidate_evidence(
            observed_candidates,
            evidence,
            _greenhouse_token_candidates(
                _extract_greenhouse_tokens(page.text, source_url=page.final_url, source="html")
            ),
        )

    candidates = _validate_observed_candidates(
        session, observed_candidates, evidence, board_validator
    )
    valid_candidates = [candidate for candidate in candidates if candidate["validation"]["valid"]]
    if page is not None and not valid_candidates:
        linked_tokens = _tokens_from_linked_scripts(page, fetcher, config)
        _merge_candidate_evidence(
            observed_candidates,
            evidence,
            _greenhouse_token_candidates(linked_tokens[0]),
        )
        candidates = _validate_observed_candidates(
            session, observed_candidates, evidence, board_validator
        )
        valid_candidates = [
            candidate for candidate in candidates if candidate["validation"]["valid"]
        ]

    if not valid_candidates and company_name:
        generated_candidates = _validate_generated_candidates(
            session,
            company_name=company_name,
            brand_alias=brand_alias,
            board_validator=board_validator,
        )
        candidates.extend(generated_candidates)
        valid_candidates = [
            candidate for candidate in candidates if candidate["validation"]["valid"]
        ]
        for candidate in generated_candidates:
            evidence.append(
                {
                    "category": "generated_candidate_validated",
                    "token": candidate["token"],
                    "source": "generated",
                }
            )

    status = _status_for_valid_candidates(valid_candidates)
    selected = valid_candidates[0] if status is SourceDetectionRunStatus.DETECTED else None
    validation = selected["validation"] if selected else {}
    return {
        "status": status,
        "normalized_url": normalized_url,
        "final_url": final_url,
        "detected_provider": selected["provider"] if selected else None,
        "candidate_tokens": candidates,
        "evidence": evidence,
        "validated_token": selected["token"] if selected else None,
        "validated_company_name": validation.get("company_name") or company_name,
        "validated_job_count": validation.get("job_count"),
        "error_message": None,
    }


def _finalize_run(
    session: Session,
    run: SourceDetectionRunModel,
    *,
    status: SourceDetectionRunStatus,
    normalized_url: str | None,
    final_url: str | None,
    detected_provider: str | None,
    candidate_tokens: list[dict[str, Any]],
    evidence: list[dict[str, Any]],
    validated_token: str | None,
    validated_company_name: str | None,
    validated_job_count: int | None,
    error_message: str | None,
) -> None:
    run.status = status.value
    run.normalized_url = normalized_url
    run.final_url = final_url
    run.detected_provider = detected_provider
    run.candidate_tokens = candidate_tokens
    run.evidence = evidence
    run.validated_token = validated_token
    run.validated_company_name = validated_company_name
    run.validated_job_count = validated_job_count
    run.error_message = error_message
    run.completed_at = utc_now()
    session.add(run)
    session.commit()


def _validate_observed_candidates(
    session: Session,
    candidates_by_identity: OrderedDict[tuple[JobSourceProvider, str], set[str]],
    evidence: list[dict[str, Any]],
    board_validator: JobSourceBoardValidator,
) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for (provider, token), categories in candidates_by_identity.items():
        validation = board_validator.validate(provider, token)
        candidates.append(
            _candidate_payload(
                provider=provider,
                token=token,
                source="observed",
                evidence_categories=sorted(categories),
                validation=validation,
                existing_source=_source_by_token(session, token, provider=provider),
                selected_external_posting_id=_selected_external_posting_id(
                    evidence, provider=provider, token=token
                ),
            )
        )
    return candidates


def _validate_generated_candidates(
    session: Session,
    *,
    company_name: str,
    brand_alias: str | None,
    board_validator: JobSourceBoardValidator,
) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for token in _generated_tokens(company_name, brand_alias):
        validation = board_validator.validate(JobSourceProvider.GREENHOUSE, token)
        if not validation.valid:
            continue
        candidates.append(
            _candidate_payload(
                provider=JobSourceProvider.GREENHOUSE,
                token=token,
                source="generated",
                evidence_categories=["generated_candidate_validated"],
                validation=validation,
                existing_source=_source_by_token(session, token),
                selected_external_posting_id=None,
            )
        )
    return candidates


def _candidate_payload(
    *,
    provider: JobSourceProvider,
    token: str,
    source: str,
    evidence_categories: list[str],
    validation: JobSourceBoardValidation,
    existing_source: JobSourceConfigurationModel | None,
    selected_external_posting_id: str | None,
) -> dict[str, Any]:
    return {
        "provider": provider.value,
        "token": token,
        "source": source,
        "evidence_categories": evidence_categories,
        "validation": {
            "status": validation.status,
            "valid": validation.valid,
            "job_count": validation.job_count,
            "sample_titles": validation.sample_titles,
            "company_name": validation.company_name,
            "error_message": validation.error_message,
        },
        "existing_source_configuration_id": str(existing_source.id) if existing_source else None,
        "selected_external_posting_id": selected_external_posting_id,
    }


def _tokens_from_linked_scripts(
    page: PublicPage,
    fetcher: PublicPageFetcher,
    config: SourceDetectionConfig,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    tokens: list[dict[str, Any]] = []
    evidence: list[dict[str, Any]] = []
    total_bytes = 0
    for script_url in _script_urls(page.text, page.final_url)[: config.max_linked_scripts]:
        script_page = fetcher.fetch(script_url)
        script_bytes = len(script_page.text.encode("utf-8"))
        total_bytes += script_bytes
        if script_bytes > config.max_script_bytes or total_bytes > config.total_script_bytes:
            continue
        script_tokens = _extract_greenhouse_tokens(
            script_page.text,
            source_url=script_page.final_url,
            source="linked_script",
        )
        for item in script_tokens:
            item["category"] = "linked_script"
            tokens.append(item)
            evidence.append(item)
    return tokens, evidence


def _extract_public_page_supported_candidates(page: PublicPage) -> list[dict[str, Any]]:
    parser = _PublicPageSignalParser()
    parser.feed(page.text)
    parser.close()
    evidence: list[dict[str, Any]] = []
    for value, category in parser.urls:
        candidate = parse_supported_ats_url(urljoin(page.final_url, value.strip()))
        if candidate is not None:
            evidence.append(
                _supported_url_evidence(
                    candidate,
                    category=category,
                    source="html",
                    source_url=page.final_url,
                )
            )
    for document in parser.json_ld_documents:
        try:
            payload = json.loads(document)
        except json.JSONDecodeError:
            continue
        for value in _string_values(payload):
            candidate = parse_supported_ats_url(urljoin(page.final_url, value.strip()))
            if candidate is not None:
                evidence.append(
                    _supported_url_evidence(
                        candidate,
                        category="structured_data_supported_ats_url",
                        source="json_ld",
                        source_url=page.final_url,
                    )
                )
    supported_url_pattern = re.compile(
        r"https?://(?:boards(?:-api)?\.greenhouse\.io|job-boards\.greenhouse\.io|"
        r"jobs\.ashbyhq\.com|jobs\.lever\.co)/[^\s\"'<>]+",
        flags=re.IGNORECASE,
    )
    for match in supported_url_pattern.finditer(page.text):
        candidate = parse_supported_ats_url(match.group(0).rstrip(".,;:)]}"))
        if candidate is not None:
            evidence.append(
                _supported_url_evidence(
                    candidate,
                    category="embedded_supported_ats_url",
                    source="html",
                    source_url=page.final_url,
                    snippet=_bounded_snippet(page.text, match.start(), match.end()),
                )
            )
    return evidence


def _string_values(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [item for child in value for item in _string_values(child)]
    if isinstance(value, dict):
        return [item for child in value.values() for item in _string_values(child)]
    return []


def _supported_url_evidence(
    candidate: Any,
    *,
    category: str,
    source: str,
    source_url: str,
    snippet: str | None = None,
) -> dict[str, Any]:
    evidence = {
        "category": category,
        "provider": candidate.provider.value,
        "token": candidate.board_token,
        "external_posting_id": candidate.external_posting_id,
        "source": source,
        "source_url": source_url,
    }
    if snippet is not None:
        evidence["snippet"] = snippet
    return evidence


def _greenhouse_token_candidates(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{**item, "provider": JobSourceProvider.GREENHOUSE.value} for item in items]


def _selected_external_posting_id(
    evidence: list[dict[str, Any]], *, provider: JobSourceProvider, token: str
) -> str | None:
    priority = {
        "application_supported_ats_url": 0,
        "redirected_supported_ats_url": 1,
        "canonical_supported_ats_url": 2,
        "structured_data_supported_ats_url": 3,
        "supported_ats_link": 4,
        "metadata_supported_ats_url": 5,
        "embedded_supported_ats_url": 6,
    }
    matching = [
        (priority.get(str(item.get("category")), len(priority)), index, item)
        for index, item in enumerate(evidence)
        if item.get("provider") == provider.value
        and item.get("token") == token
        and isinstance(item.get("external_posting_id"), str)
    ]
    if not matching:
        return None
    selected = min(matching, key=lambda item: (item[0], item[1]))[2].get("external_posting_id")
    return selected if isinstance(selected, str) else None


def _extract_greenhouse_tokens(text: str, *, source_url: str, source: str) -> list[dict[str, Any]]:
    patterns = [
        (
            "direct_api_reference",
            rf"boards-api\.greenhouse\.io/v1/boards/({TOKEN_PATTERN})/"
            r"(?:jobs|departments|offices)",
        ),
        ("direct_board_link", rf"boards\.greenhouse\.io/({TOKEN_PATTERN})(?=[/?#\"'\s<>]|$)"),
        ("direct_board_link", rf"job-boards\.greenhouse\.io/({TOKEN_PATTERN})(?=[/?#\"'\s<>]|$)"),
        (
            "embedded_config",
            rf"(?:board[_-]?token|boardToken|greenhouseBoardToken)[\"']?\s*[:=]\s*"
            rf"[\"']({TOKEN_PATTERN})[\"']",
        ),
    ]
    evidence: list[dict[str, Any]] = []
    for category, pattern in patterns:
        for match in re.finditer(pattern, text, flags=re.IGNORECASE):
            token = _normalize_token(match.group(1))
            if token is None:
                continue
            evidence.append(
                {
                    "category": category,
                    "token": token,
                    "source": source,
                    "source_url": source_url,
                    "snippet": _bounded_snippet(text, match.start(), match.end()),
                }
            )
    return evidence


def _merge_candidate_evidence(
    candidates_by_identity: OrderedDict[tuple[JobSourceProvider, str], set[str]],
    evidence: list[dict[str, Any]],
    items: list[dict[str, Any]],
) -> None:
    for item in items:
        provider = JobSourceProvider(str(item["provider"]))
        token = str(item["token"])
        candidates_by_identity.setdefault((provider, token), set()).add(str(item["category"]))
        evidence.append(item)


def _script_urls(html: str, base_url: str) -> list[str]:
    urls: list[str] = []
    base_parts = urlsplit(base_url)
    script_pattern = r"<script\b[^>]*\bsrc=[\"']([^\"']+)[\"'][^>]*>"
    for match in re.finditer(script_pattern, html, flags=re.IGNORECASE):
        candidate = urljoin(base_url, match.group(1).strip())
        parts = urlsplit(candidate)
        same_origin = parts.scheme == base_parts.scheme and parts.netloc == base_parts.netloc
        greenhouse_asset = parts.hostname in GREENHOUSE_HOSTS
        if same_origin or greenhouse_asset:
            urls.append(candidate)
    return urls


def _generated_tokens(company_name: str, brand_alias: str | None) -> list[str]:
    seeds = [company_name]
    if brand_alias:
        seeds.insert(0, brand_alias)
    tokens: OrderedDict[str, None] = OrderedDict()
    for seed in seeds:
        words = _company_words(seed)
        suffixless = [word for word in words if word not in LEGAL_SUFFIXES]
        for candidate_words in (words, suffixless):
            if not candidate_words:
                continue
            variants = {
                "".join(candidate_words),
                "-".join(candidate_words),
                "_".join(candidate_words),
            }
            for variant in variants:
                token = _normalize_token(variant)
                if token:
                    tokens[token] = None
        if len(tokens) >= 8:
            break
    return list(tokens.keys())[:8]


def _company_words(value: str) -> list[str]:
    normalized = re.sub(r"[^a-z0-9]+", " ", value.casefold()).strip()
    return [word for word in normalized.split() if word]


def _normalize_token(value: str) -> str | None:
    token = value.strip().strip("/").casefold()
    if not re.fullmatch(TOKEN_PATTERN, token, flags=re.IGNORECASE):
        return None
    if token in EXCLUDED_TOKENS:
        return None
    return token


def _status_for_valid_candidates(candidates: list[dict[str, Any]]) -> SourceDetectionRunStatus:
    if not candidates:
        return SourceDetectionRunStatus.NOT_DETECTED
    if len(candidates) > 1:
        return SourceDetectionRunStatus.AMBIGUOUS
    return SourceDetectionRunStatus.DETECTED


def _selected_valid_candidate(
    run: SourceDetectionRunModel,
    selected_token: str | None,
    selected_provider: JobSourceProvider | None,
) -> dict[str, Any]:
    valid_candidates = [
        candidate
        for candidate in run.candidate_tokens
        if isinstance(candidate, dict)
        and isinstance(candidate.get("validation"), dict)
        and candidate["validation"].get("valid") is True
    ]
    if not valid_candidates:
        raise SourceDetectionApprovalError("The detection run does not have a validated token.")
    if len(valid_candidates) > 1 and (not selected_token or selected_provider is None):
        raise AmbiguousSourceDetectionError(
            "Select both a provider and token before approving this detection run."
        )
    selected_value = selected_token or run.validated_token or ""
    normalized_selected: str | None
    candidate_provider = selected_provider or JobSourceProvider(
        run.detected_provider or JobSourceProvider.GREENHOUSE.value
    )
    if candidate_provider in {
        JobSourceProvider.ASHBY.value,
        JobSourceProvider.LEVER.value,
    }:
        normalized_selected = selected_value.strip().strip("/")
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,199}", normalized_selected):
            normalized_selected = None
    else:
        normalized_selected = _normalize_token(selected_value)
    if normalized_selected is None:
        raise SourceDetectionApprovalError(
            "Selected token was not validated by this detection run."
        )
    for candidate in valid_candidates:
        if (
            candidate.get("provider") == candidate_provider.value
            and candidate.get("token") == normalized_selected
        ):
            return candidate
    raise SourceDetectionApprovalError("Selected token was not validated by this detection run.")


def _source_by_token(
    session: Session,
    token: str,
    *,
    provider: JobSourceProvider = JobSourceProvider.GREENHOUSE,
) -> JobSourceConfigurationModel | None:
    return session.scalar(
        select(JobSourceConfigurationModel).where(
            JobSourceConfigurationModel.provider == provider.value,
            JobSourceConfigurationModel.board_token == token,
        )
    )


def _display_name(run: SourceDetectionRunModel, token: str) -> str:
    company = run.validated_company_name or run.company_name or token
    provider = JobSourceProvider(run.detected_provider or JobSourceProvider.GREENHOUSE.value)
    return f"{company} {provider.value.title()}"


def _bounded_snippet(text: str, start: int, end: int) -> str:
    low = max(start - 60, 0)
    high = min(end + 60, len(text))
    snippet = re.sub(r"\s+", " ", text[low:high]).strip()
    return snippet[:180]


def _optional_str(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    return normalized or None
