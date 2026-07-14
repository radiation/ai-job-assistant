from __future__ import annotations

from ai_job_finder.domain.enums import ProvenanceType, SourceDocumentType
from ai_job_finder.domain.errors import DocumentTooLargeError, UnsupportedDocumentTypeError

SUPPORTED_UPLOADS = {
    ".txt": {"text/plain"},
    ".pdf": {"application/pdf"},
}


def _normalize_list(values: list[str]) -> list[str]:
    normalized: list[str] = []
    for value in values:
        item = value.strip()
        if item and item not in normalized:
            normalized.append(item)
    return normalized


def _normalize_optional_str(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    return normalized or None


def _extension(filename: str) -> str:
    return f".{filename.rsplit('.', maxsplit=1)[-1].lower()}" if "." in filename else ""


def _validate_upload(filename: str, content_type: str, content: bytes, max_size: int) -> None:
    extension = _extension(filename)
    if extension not in SUPPORTED_UPLOADS or content_type not in SUPPORTED_UPLOADS[extension]:
        msg = "Only UTF-8 .txt and embedded-text .pdf uploads are supported."
        raise UnsupportedDocumentTypeError(msg)
    if len(content) > max_size:
        msg = f"Uploaded document exceeds the configured {max_size} byte limit."
        raise DocumentTooLargeError(msg)


def _source_type_to_provenance(source_type: str) -> str:
    if source_type == SourceDocumentType.RESUME.value:
        return ProvenanceType.RESUME.value
    if source_type == SourceDocumentType.PERFORMANCE_REVIEW.value:
        return ProvenanceType.PERFORMANCE_REVIEW.value
    if source_type == SourceDocumentType.PROJECT_NOTES.value:
        return ProvenanceType.PROJECT_NOTES.value
    if source_type == SourceDocumentType.CAREER_NOTES.value:
        return ProvenanceType.PERSONAL_RECOLLECTION.value
    return ProvenanceType.OTHER.value
