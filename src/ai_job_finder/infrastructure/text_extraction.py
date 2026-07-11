from __future__ import annotations

import re
from dataclasses import dataclass
from io import BytesIO

from pypdf import PdfReader
from pypdf.errors import PdfReadError

from ai_job_finder.domain.errors import DocumentExtractionError, UnsupportedDocumentTypeError

SUPPORTED_TEXT_TYPES = {"text/plain"}
SUPPORTED_PDF_TYPES = {"application/pdf"}


@dataclass(frozen=True, slots=True)
class ExtractedText:
    text: str
    location_count: int


def normalize_extracted_text(text: str) -> str:
    normalized = re.sub(r"\r\n?", "\n", text)
    normalized = re.sub(r"[ \t]+", " ", normalized)
    normalized = re.sub(r"\n{3,}", "\n\n", normalized)
    return normalized.strip()


def extract_text_from_document(
    *,
    filename: str,
    content_type: str,
    content: bytes,
) -> ExtractedText:
    extension = filename.lower().rsplit(".", maxsplit=1)[-1] if "." in filename else ""
    if extension == "txt" and content_type in SUPPORTED_TEXT_TYPES:
        try:
            return ExtractedText(
                text=normalize_extracted_text(content.decode("utf-8")), location_count=1
            )
        except UnicodeDecodeError as exc:
            msg = "Plain-text documents must be valid UTF-8."
            raise DocumentExtractionError(msg) from exc
    if extension == "pdf" and content_type in SUPPORTED_PDF_TYPES:
        try:
            reader = PdfReader(BytesIO(content))
        except PdfReadError as exc:
            msg = "PDF could not be read."
            raise DocumentExtractionError(msg) from exc
        page_texts: list[str] = []
        for page_index, page in enumerate(reader.pages, start=1):
            text = normalize_extracted_text(page.extract_text() or "")
            if text:
                page_texts.append(f"--- Page {page_index} ---\n{text}")
        if not page_texts:
            msg = (
                "PDF has no embedded text. Scanned or image-only PDFs require OCR, "
                "which is not enabled."
            )
            raise DocumentExtractionError(msg)
        return ExtractedText(text="\n\n".join(page_texts), location_count=len(reader.pages))
    msg = "Only UTF-8 .txt and embedded-text .pdf documents are supported."
    raise UnsupportedDocumentTypeError(msg)
