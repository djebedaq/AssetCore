"""Bounded, manufacturer-neutral table schema inference from headers AND cells."""

import re

from .values import POSITION, quantity

SCHEMA_VERSION = 2
ROLES = ("position", "part_number", "description", "quantity", "technical_notes", "technical_specification")
ALIASES = {
    "position": {"pos", "position", "index", "позиция", "поз", "позиц", "позномер"},
    "part_number": {"part no", "part number", "spare part no", "article no", "art nr", "teile nr", "teil nr", "part nr", "stock code", "номер детали", "номер част", "кат номер", "артикул", "номенклатурен номер"},
    "description": {"description", "designation", "part name", "benennung", "beschreibung", "bezeichnung", "описание", "наименование", "название", "обозначение"},
    "quantity": {"qty", "quantity", "pieces", "pcs", "menge", "anzahl", "количество", "кол", "бр", "кол во"},
    "technical_notes": {"remark", "remarks", "note", "notes", "comment", "comments", "bemerkung", "bemerkungen", "забележка", "забележки", "примечание", "примечания"},
    "technical_specification": {"specification", "spec", "технически данни", "спецификация"},
}
AMBIGUOUS = {
    "item": {"position": 1.3, "description": 1.3},
    "no": {"position": 1.7, "part_number": .7},
    "nr": {"position": 1.7, "part_number": .7},
    "number": {"position": 1., "part_number": 1.},
    "ref": {"position": 1.6, "part_number": .8},
    "reference": {"position": 1.6, "part_number": .8},
    "code": {"part_number": 1.2, "position": .8},
    "id": {"part_number": 1., "position": 1.},
    "name": {"description": 1.7, "technical_notes": .4},
    "type": {"description": .8, "part_number": .8, "technical_specification": .8},
    "номер": {"position": 1., "part_number": 1.},
}


def normalize_header(text: str) -> str:
    return " ".join(re.sub(r"[.№#:_\-/]+", " ", text.casefold()).split())


def header_candidates(text: str) -> dict[str, float]:
    clean = normalize_header(text)
    explicit = {role: 2.5 for role, aliases in ALIASES.items() if clean in aliases}
    return explicit or AMBIGUOUS.get(clean, {})


def field_name(text: str) -> str | None:
    """Recognition only. Ambiguous tokens have no global semantic meaning."""
    roles = header_candidates(text)
    return next(iter(roles)) if len(roles) == 1 else None


def column_profile(cells: list[str]) -> dict:
    values = [str(cell).strip() for cell in cells[:32] if str(cell).strip() not in {"", "-", "/", "?", "—"}]
    count = max(1, len(values))
    def compact(value):
        return len(value) <= 120 and not re.search(r"\s", value)

    def language(value):
        return bool(re.search(r"[^\W\d_]", value, re.UNICODE)) and not (compact(value) and bool(re.search(r"\d", value)))
    shapes = [re.sub(r"[a-zа-я]", "A", re.sub(r"\d", "0", value.casefold())) for value in values]
    return {"samples": values[:8], "nonempty": len(values),
        "position": sum(bool(POSITION.fullmatch(value)) for value in values) / count,
        "identifier": sum(compact(value) for value in values) / count,
        "description": sum(language(value) or " " in value for value in values) / count,
        "quantity": sum(quantity(value) is not None for value in values) / count,
        "unique": len(set(values)) / count,
        "format_consistency": max((shapes.count(shape) for shape in set(shapes)), default=0) / count}


def role_score(header: str, profile: dict, role: str) -> float:
    hint = header_candidates(header).get(role, 0.)
    explicit_other = bool(header_candidates(header)) and role not in header_candidates(header)
    penalty = 3. if explicit_other else 0.
    if role == "position":
        data = 3 * profile["position"] + .3 * profile["unique"] - 2 * profile["description"]
    elif role == "part_number":
        data = 2 * profile["identifier"] + .4 * profile["unique"] + .3 * profile["format_consistency"] - profile["description"]
    elif role == "description":
        data = 3 * profile["description"] - 2 * profile["quantity"]
    elif role == "quantity":
        data = 3 * profile["quantity"] - 2 * profile["description"]
    else:
        data = .5 * profile["description"] if hint else -2.
    return round(2 * hint + data - penalty, 4)


def infer_schema(headers: list[str], rows: list[list[str]]) -> dict:
    """64-beam search, <=12 columns, <=32 sampled rows; never factorial search."""
    if not 3 <= len(headers) <= 12:
        return {"state": "NEEDS_REVIEW", "mapping": {}, "alternatives": [], "score": 0., "profiles": [], "warnings": ["SCHEMA_UNRESOLVED"]}
    profiles = [column_profile([row[col] if col < len(row) else "" for row in rows[:32]]) for col in range(len(headers))]
    beam = [(0., {})]
    for col, (header, profile) in enumerate(zip(headers, profiles, strict=True)):
        scores = {role: role_score(header, profile, role) for role in ROLES}
        choices = sorted(scores, key=scores.get, reverse=True)[:4]
        expanded = []
        for score, mapping in beam:
            expanded.append((score, {**mapping, col: "unknown"}))
            for role in choices:
                if role not in mapping.values():
                    expanded.append((score + scores[role], {**mapping, col: role}))
        beam = sorted(expanded, key=lambda item: item[0], reverse=True)[:64]
    viable = [(score, mapping) for score, mapping in beam if {"position", "part_number", "description"} <= set(mapping.values())]
    if not viable:
        return {"state": "NEEDS_REVIEW", "mapping": {}, "alternatives": [], "score": 0., "profiles": profiles, "warnings": ["SCHEMA_UNRESOLVED"]}
    # Alternatives differing only in an optional unknown column do not make the
    # required part identity ambiguous; uncertainty of that column is retained.
    best_score, best = viable[0]
    def signature(mapping):
        return tuple(next((col for col, value in mapping.items() if value == role), None)
                     for role in ("position", "part_number", "description", "quantity"))
    second = next((score for score, mapping in viable[1:] if signature(mapping) != signature(best)), None)
    pos = next(col for col, role in best.items() if role == "position")
    desc = next(col for col, role in best.items() if role == "description")
    plausible = profiles[pos]["position"] >= .5 and profiles[desc]["description"] >= .4
    ambiguous = not plausible or best_score < 10 or second is not None and best_score - second < 1.
    warnings = ["SCHEMA_AMBIGUOUS"] if ambiguous else []
    if "unknown" in best.values():
        warnings.append("UNKNOWN_COLUMN")
    return {"state": "NEEDS_REVIEW" if ambiguous else "RESOLVED", "mapping": {str(col): role for col, role in best.items()},
        "score": round(best_score, 4), "margin": None if second is None else round(best_score - second, 4),
        "alternatives": [{"score": round(score, 4), "mapping": {str(col): role for col, role in mapping.items()}} for score, mapping in viable[:5]],
        "profiles": profiles, "warnings": warnings}
