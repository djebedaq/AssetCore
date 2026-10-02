"""Exact-value validation shared by schema inference and row normalization."""

import re
from decimal import Decimal, InvalidOperation

POSITION = re.compile(r"^(?:[A-Za-zА-Яа-я]?\d+(?:\.\d+)?[A-Za-zА-Яа-я]?|[A-Za-zА-Яа-я]\d+)$")
PLACEHOLDERS = {"", "-", "/", "?", "—"}


def quantity(raw: str) -> str | None:
    if not re.fullmatch(r"\d{1,10}(?:[.,]\d{1,4})?", raw.strip()):
        return None
    try:
        return str(Decimal(raw.replace(",", ".")))
    except InvalidOperation:
        return None
