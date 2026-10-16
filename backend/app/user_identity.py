"""Normalization for current internal profiles; archived identities are never rewritten."""


def clean_identity(value: str | None) -> str | None:
    if value is None:
        return None
    return " ".join(value.split()) or None


def full_name(first: str, middle: str | None, last: str) -> str:
    return " ".join(value for value in (first, middle, last) if value)
