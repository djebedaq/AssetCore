from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

_DIAGNOSTIC_PREFIX = re.compile(r"[^A-Z0-9]+")


def new_diagnostic_id(prefix: str = "APPERR") -> str:
    """Return a short, log-searchable identifier without embedding business data."""
    normalized = _DIAGNOSTIC_PREFIX.sub("", prefix.upper()) or "APPERR"
    return f"{normalized}-{uuid4().hex[:12].upper()}"


@dataclass
class ApplicationError(Exception):
    """Safe API error contract shared by critical application workflows."""

    status_code: int
    code: str
    message: str
    data: dict[str, Any] = field(default_factory=dict)
    operation: str | None = None
    stage: str | None = None
    diagnostic_id: str | None = None

    def __post_init__(self) -> None:
        Exception.__init__(self, self.message)

    def as_detail(self) -> dict[str, Any]:
        detail: dict[str, Any] = {"code": self.code, "message": self.message}
        if self.operation:
            detail["operation"] = self.operation
        if self.stage:
            detail["stage"] = self.stage
        if self.diagnostic_id:
            detail["diagnostic_id"] = self.diagnostic_id
        detail.update(self.data)
        return detail


def unexpected_workflow_error(
    logger: logging.Logger,
    exc: Exception,
    *,
    code: str,
    message: str,
    operation: str,
    stage: str,
    diagnostic_prefix: str,
    context: dict[str, int | str | None] | None = None,
) -> ApplicationError:
    """Log traceback plus allow-listed workflow context and return a safe API error."""
    diagnostic_id = new_diagnostic_id(diagnostic_prefix)
    structured_context = {
        "code": code,
        "operation": operation,
        "stage": stage,
        "diagnostic_id": diagnostic_id,
        **{key: value for key, value in (context or {}).items() if value is not None},
    }
    logger.exception(
        "assetcore_workflow_error",
        exc_info=exc,
        extra={"assetcore": structured_context},
    )
    return ApplicationError(
        status_code=500,
        code=code,
        message=f"{message} Диагностичен код: {diagnostic_id}.",
        operation=operation,
        stage=stage,
        diagnostic_id=diagnostic_id,
    )
