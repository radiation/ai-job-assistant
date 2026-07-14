from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from ai_job_finder.application.job_sources._common import _normalize_optional_str
from ai_job_finder.domain.job_sources import NormalizedJobPosting


def _sha256_json(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _normalize_for_key(value: str | None) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (value or "").casefold()).strip()


def _normalized_payload(job: NormalizedJobPosting) -> dict[str, Any]:
    return {
        "provider": job.provider.value,
        "company_name": job.company_name.strip(),
        "title": job.title.strip(),
        "location_text": _normalize_optional_str(job.location_text),
        "workplace_type": job.workplace_type.value if job.workplace_type else None,
        "description_raw": job.description_raw.strip(),
        "description_normalized": job.description_normalized.strip(),
        "compensation_text": _normalize_optional_str(job.compensation_text),
        "source_url": _normalize_optional_str(job.source_url),
        "external_id": job.external_id.strip(),
        "internal_job_id": _normalize_optional_str(job.internal_job_id),
        "source_updated_at": job.source_updated_at.isoformat() if job.source_updated_at else None,
        "departments": sorted(job.departments),
        "offices": sorted(job.offices),
        "metadata": job.metadata,
        "posting_status": job.posting_status,
    }


def _stored_normalized_payload(job: NormalizedJobPosting) -> dict[str, Any]:
    payload = _normalized_payload(job)
    description_normalized = payload.pop("description_normalized")
    payload.pop("description_raw")
    payload["description_normalized_sha256"] = hashlib.sha256(
        description_normalized.encode("utf-8")
    ).hexdigest()
    payload["description_normalized_length"] = len(description_normalized)
    return payload


def _scoring_payload(job: NormalizedJobPosting) -> dict[str, Any]:
    return {
        "company_name": job.company_name.strip(),
        "title": job.title.strip(),
        "location_text": _normalize_optional_str(job.location_text),
        "workplace_type": job.workplace_type.value if job.workplace_type else None,
        "description_normalized": job.description_normalized.strip(),
        "compensation_text": _normalize_optional_str(job.compensation_text),
    }


def duplicate_hint_key(job: NormalizedJobPosting) -> str:
    payload = {
        "company": _normalize_for_key(job.company_name),
        "title": _normalize_for_key(job.title),
        "location": _normalize_for_key(job.location_text),
        "url": _normalize_for_key(job.source_url),
        "description": hashlib.sha256(
            _normalize_for_key(job.description_normalized).encode("utf-8")
        ).hexdigest(),
        "internal_job_id": _normalize_for_key(job.internal_job_id),
    }
    return _sha256_json(payload)
