"""Validated correlation context for governance and document audit entries."""

from __future__ import annotations

import re

from fastapi import Request


def _correlation_id(request: Request) -> str | None:
    value = request.headers.get("X-Request-ID", "")
    return value if re.fullmatch(r"[A-Za-z0-9._:-]{1,80}", value) else None
