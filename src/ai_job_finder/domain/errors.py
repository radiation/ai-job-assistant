from __future__ import annotations


class DomainError(Exception):
    code = "domain_error"


class NotFoundError(DomainError):
    code = "not_found"


class InvalidStatusTransitionError(DomainError):
    code = "invalid_status_transition"


class InvalidCareerFactTransitionError(DomainError):
    code = "invalid_career_fact_transition"


class EvaluationPreconditionError(DomainError):
    code = "evaluation_precondition_failed"


class SingleCandidateViolationError(DomainError):
    code = "single_candidate_violation"


class ArchivedCareerFactModificationError(DomainError):
    code = "archived_career_fact_requires_restore"


class UnsupportedDocumentTypeError(DomainError):
    code = "unsupported_document_type"


class DocumentTooLargeError(DomainError):
    code = "document_too_large"


class DuplicateSourceDocumentError(DomainError):
    code = "duplicate_source_document"


class DocumentExtractionError(DomainError):
    code = "document_extraction_failed"


class DocumentExtractionLimitError(DomainError):
    code = "document_extraction_limit_exceeded"


class ExtractionProviderUnavailableError(DomainError):
    code = "extraction_provider_unavailable"


class MalformedExtractionOutputError(DomainError):
    code = "malformed_extraction_output"


class InvalidProposalEditError(DomainError):
    code = "invalid_proposal_edit"


class InvalidProposalTransitionError(DomainError):
    code = "invalid_proposal_transition"


class MergeTargetMismatchError(DomainError):
    code = "merge_target_mismatch"


class DuplicateJobSourceError(DomainError):
    code = "duplicate_job_source"


class UnsafeUrlError(DomainError):
    code = "unsafe_url"


class BlockedRedirectError(DomainError):
    code = "blocked_redirect"


class UnavailablePageError(DomainError):
    code = "unavailable_page"


class UnsupportedContentTypeError(DomainError):
    code = "unsupported_content_type"


class OversizedResponseError(DomainError):
    code = "oversized_response"


class NoProviderDetectedError(DomainError):
    code = "no_provider_detected"


class AmbiguousSourceDetectionError(DomainError):
    code = "ambiguous_candidates"


class GreenhouseValidationUnavailableError(DomainError):
    code = "greenhouse_validation_unavailable"


class SourceDetectionApprovalError(DomainError):
    code = "source_detection_approval_failed"


class SourceSyncAfterCreationError(DomainError):
    code = "sync_failure_after_source_creation"


class InvalidJobSourceError(DomainError):
    code = "invalid_job_source"


class JobSourceDisabledError(DomainError):
    code = "job_source_disabled"


class JobSourceProviderError(DomainError):
    code = "job_source_provider_failure"


class JobSourceTimeoutError(JobSourceProviderError):
    code = "job_source_timeout"


class MalformedJobSourcePayloadError(JobSourceProviderError):
    code = "malformed_job_source_payload"


class SuspiciousEmptyJobSourceResultError(DomainError):
    code = "suspicious_empty_job_source_result"


class OverlappingJobImportError(DomainError):
    code = "overlapping_job_import"


class MissingCandidateError(DomainError):
    code = "missing_candidate"
