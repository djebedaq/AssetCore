"""Structural worker contract only; partial readings remain human review work.

Validate fields used by ledger identity, mapping, context and review before any
durable write. Do not normalize values, discard rows or infer missing parts.
Unknown diagnostic fields are retained, but must be finite, bounded-depth JSON.
"""

import math

from .schema import ROLES


def number(value):
    try:
        return type(value) in (int, float) and math.isfinite(value)
    except OverflowError:
        return False


def index(value):
    return type(value) is int and value >= 0


def text(value):
    return isinstance(value, str)


def texts(value):
    return isinstance(value, list) and all(text(item) for item in value)


def sequence(check):
    return lambda value: isinstance(value, list) and all(check(item) for item in value)


def vector(value, size=None):
    return isinstance(value, list) and (size is None or len(value) == size) and all(number(v) for v in value)


def box(value):
    return vector(value, 4)


def fields(value, required, optional=None):
    return (isinstance(value, dict)
        and all(key in value and check(value[key]) for key, check in required.items())
        and all(key not in value or check(value[key]) for key, check in (optional or {}).items()))


def finite_json(value, depth=0):
    if depth > 32:
        return False
    if value is None or type(value) in (str, bool, int):
        return True
    if isinstance(value, float):
        return math.isfinite(value)
    if isinstance(value, list):
        return all(finite_json(item, depth + 1) for item in value)
    return isinstance(value, dict) and all(text(k) and finite_json(v, depth + 1) for k, v in value.items())


def payload(value):
    def nullable(item):
        return item is None or text(item)
    return fields(value, {"position": text, "part_number": text, "description": nullable,
        "quantity": nullable, "quantity_raw": nullable},
        {"technical_notes": nullable, "technical_specification": nullable}) and set(value) <= {
            "position", "part_number", "description", "quantity", "quantity_raw",
            "technical_notes", "technical_specification"}


def mapping(value, columns):
    return isinstance(value, dict) and all(text(k) and len(k) <= 10 and k.isascii() and k.isdecimal()
        and str(int(k)) == k and int(k) < columns and text(v) and v in (*ROLES, "unknown")
        for k, v in value.items())


def schema(value, columns, *, table=False):
    required = {"mapping": lambda v: mapping(v, columns), "score": number}
    if table:
        required.update(state=text, warnings=texts)
    else:
        required["headers"] = texts
    return fields(value, required, {"warnings": texts, "margin": lambda v: v is None or number(v),
        "alternatives": sequence(lambda v: fields(v, {"score": number, "mapping": lambda m: mapping(m, columns)})),
        "profiles": sequence(lambda v: isinstance(v, dict))})


def quality(value, *, page=False):
    required = {"state": text, "basis": text, "observed_rows": index, "candidate_rows": index,
        "missing_rows": index, "partial_rows": index}
    if page:
        required["needs_context"] = lambda v: type(v) is bool
    else:
        required.update(warnings=texts, covered_rows=index, rank=vector)
    return fields(value, required, {"warnings": texts, "physical_coverage": lambda v: fields(v,
        {"observed_rows": index, "covered_rows": index, "missing_rows": index,
         "truncated": lambda item: type(item) is bool})})


def geometry(value):
    return fields(value, {"state": text, "warnings": texts},
        {"boundaries": vector, "normalized_boundaries": lambda v: v is None or vector(v)})


def table(value):
    if not fields(value, {"bbox": box, "headers": texts, "columns": texts, "method": text,
            "cells": sequence(texts), "sample_cells": sequence(texts), "row_boxes": sequence(box),
            "row_count": index, "anchors": vector, "table_index": index,
            "quality": quality}, {"geometry": geometry, "page_width": lambda v: number(v) and v > 0,
            "header_geometry": sequence(lambda v: fields(v, {"text": text, "bbox": box})),
            "excluded_rows": sequence(lambda v: fields(v, {"reason": text, "bbox": box},
                {"index": index, "raw_cells": texts})), "strategy_warnings": texts,
            "human_mapping": lambda v: type(v) is bool}):
        return False
    return (schema(value.get("schema"), len(value["headers"]), table=True)
        and len(value["cells"]) == len(value["row_boxes"]) == value["row_count"])


def row(value):
    if not fields(value, {"payload": payload, "bbox": box, "warnings": texts,
            "confidence": number, "raw_text": text, "method": text, "raw_cells": texts,
            "raw_values": lambda v: isinstance(v, dict) and all(text(k) and text(t) for k, t in v.items()),
            "source_row_index": index, "source_row_indices": sequence(index), "table_index": index},
            {"occurrence_key": lambda v: isinstance(v, list) and len(v) == 2 and all(index(i) for i in v),
            "continuation_cells": sequence(texts), "reconciliation_required": lambda v: type(v) is bool,
            "source_region": lambda v: fields(v, {"table": index, "row": index, "bbox": box})}):
        return False
    return (schema(value.get("schema"), len(value["raw_cells"])) and fields(value.get("provenance"),
        {"sha256": text, "physical_page": lambda v: index(v) and v > 0, "pipeline_version": text}))


def page(value):
    return fields(value, {"rows": sequence(row), "tables": sequence(table),
        "words": sequence(lambda v: fields(v, {"text": text, "bbox": box},
            {"block": index, "line": index, "word": index})),
        "quality": lambda v: quality(v, page=True), "warnings": texts, "raw_text": text,
        "method": text, "pipeline_version": text, "ocr_used": lambda v: type(v) is bool},
        {"width": lambda v: number(v) and v > 0, "height": lambda v: number(v) and v > 0,
         "rotation_matrix": lambda v: vector(v, 6)}) and finite_json(value)
