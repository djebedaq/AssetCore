"""Actor-bound previews backed by durable attempts and review candidates."""

import base64
import hashlib
import hmac
import json
import time

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ...audit import add_audit_log
from ...models import (
    CatalogExtractionAttempt,
    CatalogExtractionCandidate,
    CatalogRevisionArtifact,
    CatalogRevisionPart,
    CatalogRevisionPartPageMap,
    CatalogRevisionVisualPage,
)
from ...settings import settings
from .. import parts, reference_pages
from ..service import fail
from ..visual_sources import _meta
from . import ledger, process
from .tables import parse_region

EXTRACTOR_VERSION = "SPARE_PARTS_1"


def resumable_attempt(db, source):
    attempt = db.get(CatalogExtractionAttempt, source.current_attempt_id) if source.current_attempt_id else None
    if source.processing_state in {"FAILED", "CANCELLED"}:
        # The failed retry remains authoritative processing history. Its previous
        # exact-source rows can still be corrected/confirmed; final source review
        # requires explicit manual transcription while processing is not successful.
        attempt = db.scalar(select(CatalogExtractionAttempt).where(
            CatalogExtractionAttempt.source_id == source.id, CatalogExtractionAttempt.state == "SUCCEEDED")
            .order_by(CatalogExtractionAttempt.id.desc()).limit(1))
    return attempt if attempt and attempt.state == "SUCCEEDED" else None


def _sign(claim: dict) -> str:
    try:
        payload = json.dumps(claim, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode()
    except (ValueError, TypeError):
        raise fail("catalog_extraction_page_failed", 422) from None
    if len(payload) > 2_900_000:
        raise fail("catalog_extraction_preview_limit", 422)
    signature = hmac.new(settings.secret_key.encode(), payload, hashlib.sha256).hexdigest()
    return base64.urlsafe_b64encode(payload).decode().rstrip("=") + "." + signature


def _read(db: Session, actor, page_id: int, token: str) -> tuple[dict, tuple]:
    context = reference_pages.load(db, page_id, mutate=True)
    try:
        encoded, signature = token.split(".", 1)
        payload = base64.b64decode(encoded + "=" * (-len(encoded) % 4), altchars=b"-_", validate=True)
        expected = hmac.new(settings.secret_key.encode(), payload, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(signature, expected):
            raise ValueError("signature")
        claim = json.loads(payload)
        if (claim["actor_id"] != actor.id or claim["page_id"] != page_id
                or not 0 <= time.time() - claim["created"] <= 900
                or claim["extractor"] != EXTRACTOR_VERSION):
            raise ValueError("binding")
    except (ValueError, TypeError, KeyError, UnicodeError):
        raise fail("catalog_extraction_token_invalid", 422) from None
    reference_pages.check_version(context[0], claim["page_version"])
    _source(db, page_id, claim["source"]["visual_page_id"], expected=claim["source"])
    source, active, *_ = ledger.source_context(db, claim["source"]["visual_page_id"])
    attempt = db.get(CatalogExtractionAttempt, claim.get("attempt_id")) if claim.get("attempt_id") else None
    if (source is None or active.id != claim.get("session_id") or attempt is None
            or resumable_attempt(db, source) is not attempt or attempt.source_id != source.id
            or attempt.state != "SUCCEEDED" or ledger.hashed(attempt.evidence) != claim.get("evidence_digest")):
        raise fail("catalog_extraction_token_invalid", 422)
    return claim, context


def _source(db, page_id, visual_page_id, *, expected=None) -> tuple:
    page = db.get(CatalogRevisionVisualPage, visual_page_id)
    if page is None or page.reference_page_id != page_id or page.role != "SPARE_PARTS_LIST":
        raise fail("catalog_part_page_invalid", 422)
    artifact = db.get(CatalogRevisionArtifact, page.artifact_id)
    reference = db.get(reference_pages.CatalogRevisionReferencePage, page_id)
    if artifact is None or artifact.assembly_id != reference.assembly_id:
        raise fail("catalog_part_page_invalid", 422)
    source = {"visual_page_id": page.id, "artifact_id": artifact.id, "sha256": artifact.sha256,
              "page_number": page.page_number, "filename": artifact.filename}
    if expected is not None and source != expected:
        raise fail("catalog_extraction_token_invalid", 422)
    return artifact, source


def _result(claim: dict, db: Session) -> dict:
    rows = []
    for row in claim["rows"]:
        candidate = db.get(CatalogExtractionCandidate, row["candidate_id"])
        part = ledger.accepted_part(db, candidate)
        payload = {key: getattr(part, key) for key in candidate.values} if part else candidate.values
        rows.append({**row, "payload": payload, "candidate_id": candidate.id,
            "candidate_version": candidate.version, "candidate_state": candidate.state})
    return {"token": _sign(claim), "source": claim["source"], "rows": rows,
            "tables": claim["tables"], "warnings": claim["warnings"], "method": claim["method"]}


def claim_for(db, actor, page, source, active, attempt):
    evidence = attempt.evidence
    _, exact = _source(db, page.id, source.visual_page_id)
    return {"actor_id": actor.id, "page_id": page.id, "page_version": page.version,
        "created": int(time.time()), "extractor": EXTRACTOR_VERSION, "source": exact,
        "attempt_id": attempt.id, "session_id": active.id, "evidence_digest": attempt.evidence_digest,
        "rows": evidence["rows"], "tables": evidence["tables"], "warnings": evidence["warnings"],
        "method": evidence["method"]}


def preview(db: Session, actor, page_id: int, data) -> dict:
    page, assembly, revision, catalog = reference_pages.load(db, page_id, mutate=True)
    artifact, source = _source(db, page_id, data.visual_page_id)
    config = process.configuration(settings)
    if data.continuation_token:
        previous, _ = _read(db, actor, page_id, data.continuation_token)
        if previous["source"]["sha256"] == source["sha256"] and previous["source"]["page_number"] + 1 == source["page_number"]:
            # Keep the fixed worker argument small, including on Windows. Raw
            # cells/rows are preview evidence, never subprocess configuration.
            config["continuation_tables"] = process.continuation_configuration(previous["tables"])
    state, active, *_ = ledger.source_context(db, source["visual_page_id"], actor, create=True)
    attempt = ledger.start(db, actor, state, EXTRACTOR_VERSION)
    attempt_id, session_id = attempt.id, active.id
    raw = artifact.content
    db.commit()  # The RUNNING lease survives a request/worker interruption.
    try:
        evidence = process.extract(raw, "page", source["page_number"], config)
    except Exception as exc:
        from fastapi import HTTPException
        code = exc.detail.get("code") if isinstance(exc, HTTPException) and isinstance(exc.detail, dict) else "catalog_extraction_page_failed"
        evidence = {"error": code}
    from ..visual_sources import lock_catalog
    lock_catalog(db, catalog.id)
    attempt = db.get(CatalogExtractionAttempt, attempt_id)
    historical = db.get(ledger.Source, attempt.source_id)
    active = ledger.session(db, None, assembly, revision, page_id)
    if (revision.status != "DRAFT" or active is None or active.id != session_id
            or historical.current_attempt_id != attempt_id or attempt.state != "RUNNING"):
        if attempt.state == "RUNNING":
            attempt.state, attempt.finished_at = "CANCELLED", ledger.utcnow()
        if historical.current_attempt_id == attempt_id:
            historical.processing_state = "CANCELLED"
            ledger.invalidate(historical)
        add_audit_log(db, actor, "catalog_extraction_attempt", attempt.id, "EXTRACTION_RESULT_STALE", {"source_id": historical.id})
        db.commit()
        raise fail("catalog_reference_page_stale")
    page, assembly, revision, catalog = reference_pages.load(db, page_id, mutate=True)
    state = historical
    if len(json.dumps(evidence, ensure_ascii=False).encode()) > 2_700_000:
        evidence = {"error": "catalog_extraction_preview_limit"}
    ledger.finish(db, actor, state, active, attempt, evidence)
    if evidence.get("error"):
        db.commit()
        raise fail(evidence["error"], 422)
    claim = claim_for(db, actor, page, state, active, attempt)
    result = _result(claim, db)
    add_audit_log(db, actor, "catalog_reference_page", page.id, "SPARE_PARTS_PREVIEW_CREATED",
        _meta(catalog, revision, assembly, artifact, page_number=source["page_number"],
              row_count=len(claim["rows"]), ocr_used=evidence["ocr_used"], extractor=EXTRACTOR_VERSION))
    db.commit()
    return result


def remap(db: Session, actor, page_id: int, data) -> dict:
    claim, context = _read(db, actor, page_id, data.token)
    if data.table_index >= len(claim["tables"]):
        raise fail("catalog_extraction_mapping_invalid", 422)
    table = claim["tables"][data.table_index]
    mapping = data.mapping
    roles = [role for role in mapping.values() if role != "unknown"]
    if (set(mapping) != {str(i) for i in range(len(table["headers"]))}
            or len(roles) != len(set(roles)) or not {"position", "part_number", "description"} <= set(roles)):
        raise fail("catalog_extraction_mapping_invalid", 422)
    rows, updated = parse_region(table["headers"], table["cells"], table["row_boxes"], table["bbox"],
        table["method"], mapping=mapping)
    updated = {**table, **updated}
    updated["human_mapping"] = True
    # Rebuild only this table; preserve other tables and all exact source evidence.
    bbox = table["bbox"]
    claim["rows"] = [row for row in claim["rows"] if not (
        bbox[0] <= row["bbox"][0] and row["bbox"][2] <= bbox[2]
        and bbox[1] <= row["bbox"][1] and row["bbox"][3] <= bbox[3])]
    for row in rows:
        row["human_mapping"] = mapping
        if claim["method"] == "OCR":
            row["method"] = "OCR_WORD_LAYOUT"
        row["warnings"] = sorted(set(row["warnings"] + table.get("geometry", {}).get("warnings", [])
            + (["OCR_REQUIRES_REVIEW"] if claim["method"] == "OCR" else [])))
    claim["rows"].extend(rows)
    schema_warnings = {warning for item in claim["tables"] for warning in item["schema"]["warnings"]}
    claim["tables"][data.table_index] = updated
    claim["warnings"] = sorted((set(claim["warnings"]) - schema_warnings)
        | {warning for item in claim["tables"] for warning in item["schema"]["warnings"]})
    add_audit_log(db, actor, "catalog_reference_page", page_id, "SPARE_PARTS_COLUMNS_MAPPED",
        _meta(context[3], context[2], context[1], table_index=data.table_index, mapping=mapping))
    state, active, *_ = ledger.source_context(db, claim["source"]["visual_page_id"])
    attempt = ledger.start(db, actor, state, EXTRACTOR_VERSION)
    attempt.kind = "MAPPING"
    evidence = {key: claim[key] for key in ("rows", "tables", "warnings", "method")}
    ledger.finish(db, actor, state, active, attempt, evidence)
    claim = claim_for(db, actor, context[0], state, active, attempt)
    result = _result(claim, db)
    db.commit()
    return result


def confirm(db: Session, actor, page_id: int, data) -> dict:
    claim, (page, assembly, revision, catalog) = _read(db, actor, page_id, data.token)
    indices = [row.index for row in data.rows]
    if len(indices) != len(set(indices)) or any(index >= len(claim["rows"]) for index in indices):
        raise fail("catalog_extraction_token_invalid", 422)
    if not data.confirm_warnings and any(claim["rows"][index]["warnings"] for index in indices):
        raise fail("catalog_part_import_warning_confirmation", 422)
    created, existing = [], []
    try:
        for selection in data.rows:
            row = claim["rows"][selection.index]
            candidate = db.get(CatalogExtractionCandidate, row["candidate_id"])
            if candidate.state in {"CONFLICT", "REJECTED"}:
                raise fail("catalog_extraction_candidate_unresolved")
            prior = ledger.accepted_part(db, candidate)
            if prior:
                existing.append(prior.id)
                continue  # Re-extraction can never overwrite a confirmed human edit.
            if candidate.state == "ACCEPTED":
                raise fail("catalog_extraction_candidate_unresolved")
            if ((candidate.version > 1 and selection.expected_version is None)
                    or selection.expected_version is not None and candidate.version != selection.expected_version):
                raise fail("catalog_reference_page_stale")
            key = ledger.hashed([claim["source"]["sha256"], claim["source"]["page_number"], candidate.stable_key])
            values = parts._clean(selection.part.model_dump())
            item = CatalogRevisionPart(assembly_id=assembly.id, reference_page_id=page.id,
                extraction_key=key, extraction_evidence={"source": claim["source"], "row": row,
                "extractor": EXTRACTOR_VERSION, "confirmed_by_id": actor.id}, created_by_id=actor.id, **values)
            db.add(item)
            db.flush()
            db.add(CatalogRevisionPartPageMap(part_id=item.id,
                visual_page_id=claim["source"]["visual_page_id"], created_by_id=actor.id))
            created.append(item.id)
            candidate.part_id, candidate.state = item.id, "ACCEPTED"
            candidate.part_created_at = item.created_at
            candidate.values = json.loads(selection.part.model_dump_json())
            candidate.version += 1
            candidate.updated_by_id = actor.id
        if created:
            state, _, *_ = ledger.source_context(db, claim["source"]["visual_page_id"])
            ledger.invalidate(state)
            ledger.invalidate_scope(db, actor, assembly.id, page.id, "EXTRACTED_PARTS_CONFIRMED")
        add_audit_log(db, actor, "catalog_reference_page", page.id, "SPARE_PARTS_CONFIRMED",
            _meta(catalog, revision, assembly, created_count=len(created), existing_count=len(existing),
                  visual_page_id=claim["source"]["visual_page_id"]))
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise fail("catalog_part_import_conflict") from exc
    except Exception:
        db.rollback()
        raise
    return {"created_count": len(created), "part_ids": created, "existing_part_ids": existing}
