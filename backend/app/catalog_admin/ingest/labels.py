"""Bounded combined callout evidence; never creates a BOM position."""

import re

from .values import POSITION


def label_members(raw: str) -> list[str] | None:
    raw = raw.strip()
    if POSITION.fullmatch(raw):
        return [raw]
    if re.fullmatch(r"\d{1,5}\s*[-–]\s*\d{1,5}", raw):
        first, last = (int(value.strip()) for value in re.split(r"[-–]", raw))
        if 0 <= last - first < 50:
            return [str(value) for value in range(first, last + 1)]
        return None
    if len(raw) <= 120 and re.fullmatch(r"[\w.]+(?:\s*[,;]\s*[\w.]+){1,19}", raw):
        members = [value.strip() for value in re.split(r"[,;]", raw)]
        return members if all(POSITION.fullmatch(value) for value in members) else None
    return None
