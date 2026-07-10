from __future__ import annotations


class DomainError(Exception):
    code = "domain_error"


class NotFoundError(DomainError):
    code = "not_found"


class InvalidStatusTransitionError(DomainError):
    code = "invalid_status_transition"


class EvaluationPreconditionError(DomainError):
    code = "evaluation_precondition_failed"
