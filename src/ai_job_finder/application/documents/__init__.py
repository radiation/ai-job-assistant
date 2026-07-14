from __future__ import annotations

from ai_job_finder.application.documents.extraction_runs import (
    extract_document_text,
    list_extraction_runs,
    rerun_failed_extraction,
    start_extraction_run,
)
from ai_job_finder.application.documents.proposals import (
    accept_career_fact_proposal,
    edit_career_fact_proposal,
    get_career_fact_proposal,
    list_career_fact_proposals,
    merge_career_fact_proposal,
    reject_career_fact_proposal,
)
from ai_job_finder.application.documents.service import (
    get_source_document,
    list_source_documents,
    upload_source_document,
)

__all__ = [
    "accept_career_fact_proposal",
    "edit_career_fact_proposal",
    "extract_document_text",
    "get_career_fact_proposal",
    "get_source_document",
    "list_career_fact_proposals",
    "list_extraction_runs",
    "list_source_documents",
    "merge_career_fact_proposal",
    "reject_career_fact_proposal",
    "rerun_failed_extraction",
    "start_extraction_run",
    "upload_source_document",
]
