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
