"""Stable evidence identities, review queries and coordinate hotspot matching."""

import hashlib
import json

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ...models import (
    CatalogIngestCandidate,
    CatalogIngestPage,
    CatalogIngestRun,
    CatalogRevisionPart,
)
from .association import relationship
from .geometry import match_position, normalized_geometry

EXTRACTOR_VERSION = "CATALOG_INGEST_1"


def fingerprint(*values) -> str:
    return hashlib.sha256(json.dumps(values, sort_keys=True, ensure_ascii=False,
                                    separators=(",", ":")).encode()).hexdigest()


def propose(db: Session, run_id: int, key: str, kind: str, payload: dict, evidence: dict,
            confidence: float, warnings: list, number: int | None = None) -> CatalogIngestCandidate:
    existing = db.scalar(select(CatalogIngestCandidate).where(
        CatalogIngestCandidate.run_id == run_id, CatalogIngestCandidate.source_key == key))
    if existing is not None:
        # Re-analysis never touches a reviewed decision or human correction.
        if (existing.reviewed_by_id is None
                and existing.state in {"PROPOSED", "NEEDS_REVIEW"}):
            if (existing.payload, existing.evidence, existing.confidence, existing.warnings) != (payload, evidence, confidence, warnings):
                existing.payload, existing.evidence, existing.confidence = payload, evidence, confidence
                existing.warnings = warnings
                existing.state = "NEEDS_REVIEW" if warnings or confidence < .9 else "PROPOSED"
                existing.version += 1
        return existing
    candidate = CatalogIngestCandidate(run_id=run_id, source_key=key, kind=kind,
        payload=payload, evidence=evidence, confidence=confidence, warnings=warnings,
        page_number=number, state="NEEDS_REVIEW" if warnings or confidence < .9 else "PROPOSED")
    db.add(candidate)
    db.flush()
    return candidate


def store_page(db: Session, run: CatalogIngestRun, number: int, layout: dict) -> None:
    context = dict(run.context)
    heading = layout.get("heading")
    previous = db.scalar(select(CatalogIngestPage).where(CatalogIngestPage.run_id == run.id,
        CatalogIngestPage.page_number == number - 1))
    association = relationship(previous.evidence if previous else None, layout)
    if not association:
        context.pop("group_key", None)
    if heading and layout["role"] in {"SPARE_PARTS_LIST", "EXPLODED_SCHEME", "BOTH"}:
        key = fingerprint("GROUP", heading.casefold())
        context["group_key"] = key
        propose(db, run.id, key, "GROUP", {"name": heading},
            {"source_heading": heading, "headings": layout["headings"], "page_number": number},
            .92 if layout["role"] in {"SPARE_PARTS_LIST", "EXPLODED_SCHEME", "BOTH"} else .5,
            ["OCR_REQUIRES_REVIEW"] if layout["ocr_used"] else [], number)
    elif "group_key" not in context and layout["role"] not in {"OTHER", "AMBIGUOUS"}:
        # No made-up name: use an actual extracted source line for a manual decision.
        key = fingerprint("GROUP", number)
        context["group_key"] = key
        propose(db, run.id, key, "GROUP", {"name": ""}, {"source_heading": None},
                .2, ["HEADING_NOT_FOUND"], number)
    group_key = context.get("group_key")
    warnings = list(layout["warnings"])
    if not heading and group_key and layout["role"] != "OTHER":
        warnings.append("CONTINUATION_INFERRED" if association == "TABLE_CONTINUATION" else "GROUP_UNCERTAIN")
    propose(db, run.id, fingerprint("PAGE", number), "PAGE",
        {"role": layout["role"], "group_key": group_key},
        {"role_signals": layout["role_evidence"], "heading": heading,
         "method": layout["method"], "rotation": layout["rotation"], "association": association,
         "tables": layout["tables"], "schema_version": layout.get("schema_version")},
        layout["confidence"], warnings, number)
    for row in layout["rows"]:
        key = fingerprint("PART", number, row["bbox"], row["raw_text"])
        propose(db, run.id, key, "PART", {**row["payload"], "group_key": group_key},
            {**{key: row[key] for key in ("bbox", "raw_text", "raw_values", "method")},
             **{key: row[key] for key in ("schema", "raw_cells", "continuation_cells") if key in row},
             "geometry": normalized_geometry(row["bbox"], layout)},
            row["confidence"], row["warnings"] + (["GROUP_UNCERTAIN"] if not group_key else []), number)
    run.context = context


def match_hotspots(db: Session, run: CatalogIngestRun) -> None:
    rows = db.scalars(select(CatalogIngestCandidate).where(
        CatalogIngestCandidate.run_id == run.id, CatalogIngestCandidate.kind.in_(["PART", "PAGE"]))).all()
    parts, schemes = {}, {}
    for row in rows:
        if row.state == "REJECTED":
            continue
        group = row.payload.get("group_key")
        if row.kind == "PART" and row.payload.get("position") and group:
            position = row.payload["position"]
            if row.state == "ACCEPTED":
                actual = db.get(CatalogRevisionPart, row.target_id)
                if actual is None:
                    continue
                position = actual.position
            parts.setdefault(group, set()).add(position)
        elif row.kind == "PAGE" and row.payload["role"] in {"EXPLODED_SCHEME", "BOTH"} and group:
            schemes.setdefault(group, []).append(row.page_number)
    for group, positions in parts.items():
        layouts = db.scalars(select(CatalogIngestPage).where(CatalogIngestPage.run_id == run.id,
            CatalogIngestPage.page_number.in_(schemes.get(group, [])))).all()
        for position in sorted(positions):
            result = match_position(position, [(source.page_number, source.evidence) for source in layouts])
            match, locations, ocr = result["match"], result["locations"], result["ocr_used"]
            propose(db, run.id, fingerprint("HOTSPOT", group, position), "HOTSPOT",
                {"group_key": group, "position": position, "match": match, "locations": locations},
                {"source_pages": schemes.get(group, []), "ocr_used": ocr},
                .94 if match == "EXACT" else .5, [] if match == "EXACT" else [match])
    for row in db.scalars(select(CatalogIngestCandidate).where(CatalogIngestCandidate.run_id == run.id,
        CatalogIngestCandidate.kind == "HOTSPOT", CatalogIngestCandidate.reviewed_by_id.is_(None),
        CatalogIngestCandidate.state.in_(["PROPOSED", "NEEDS_REVIEW"]))).all():
        if row.payload.get("position") not in parts.get(row.payload.get("group_key"), set()):
            row.state = "REJECTED"
            row.version += 1


def candidate_dict(candidate: CatalogIngestCandidate, run: CatalogIngestRun) -> dict:
    return {**{key: getattr(candidate, key) for key in ("id", "source_key", "kind", "state", "page_number",
        "confidence", "payload", "evidence", "warnings", "version", "target_id", "reviewed_by_id", "reviewed_at")},
        "run_id": run.id, "artifact_id": run.artifact_id, "sha256": run.sha256, "extractor_version": run.extractor_version}


def summary(db: Session, run: CatalogIngestRun) -> dict:
    counts = {kind: count for kind, count in db.execute(select(CatalogIngestCandidate.kind, func.count())
        .where(CatalogIngestCandidate.run_id == run.id).group_by(CatalogIngestCandidate.kind))}
    states = {state: count for state, count in db.execute(select(CatalogIngestCandidate.state, func.count())
        .where(CatalogIngestCandidate.run_id == run.id).group_by(CatalogIngestCandidate.state))}
    role_column = CatalogIngestCandidate.payload["role"].as_string()
    match_column = CatalogIngestCandidate.payload["match"].as_string()
    roles = {role: count for role, count in db.execute(select(role_column, func.count())
        .where(CatalogIngestCandidate.run_id == run.id, CatalogIngestCandidate.kind == "PAGE")
        .group_by(role_column))}
    matches = {match: count for match, count in db.execute(select(match_column, func.count())
        .where(CatalogIngestCandidate.run_id == run.id, CatalogIngestCandidate.kind == "HOTSPOT")
        .group_by(match_column))}
    return {"id": run.id, "artifact_id": run.artifact_id, "revision_id": run.revision_id,
        "sha256": run.sha256, "extractor_version": run.extractor_version, "status": run.status,
        "processed_pages": min(run.page_count, run.next_page - 1), "page_count": run.page_count,
        "error_code": run.error_code, "counts": counts, "states": states, "roles": roles, "matches": matches,
        "ocr_pages": run.context.get("ocr_pages", 0), "updated_at": run.updated_at}
