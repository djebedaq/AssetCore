"""Actor-bound signed previews and atomic confirmation without job/candidate tables."""

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
    CatalogRevisionArtifact,
    CatalogRevisionPart,
    CatalogRevisionPartPageMap,
    CatalogRevisionVisualPage,
)
from ...settings import settings
from .. import parts, reference_pages
from ..service import fail
from ..visual_sources import _meta
from . import process
from .tables import parse_region

EXTRACTOR_VERSION = "SPARE_PARTS_1"


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


def _result(claim: dict) -> dict:
    return {"token": _sign(claim), "source": claim["source"], "rows": claim["rows"],
            "tables": claim["tables"], "warnings": claim["warnings"], "method": claim["method"]}


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
    evidence = process.extract(artifact.content, "page", source["page_number"], config)
    if evidence.get("error"):
        raise fail(evidence["error"], 422)
    claim = {"actor_id": actor.id, "page_id": page.id, "page_version": page.version,
        "created": int(time.time()), "extractor": EXTRACTOR_VERSION, "source": source,
        "rows": evidence["rows"], "tables": evidence["tables"], "warnings": evidence["warnings"],
        "method": evidence["method"]}
    result = _result(claim)
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
    claim["tables"][data.table_index] = updated
    add_audit_log(db, actor, "catalog_reference_page", page_id, "SPARE_PARTS_COLUMNS_MAPPED",
        _meta(context[3], context[2], context[1], table_index=data.table_index, mapping=mapping))
    db.commit()
    return _result(claim)


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
            identity = json.dumps([claim["source"]["sha256"], claim["source"]["page_number"],
                row["bbox"], row["raw_text"]], ensure_ascii=False, separators=(",", ":"))
            key = hashlib.sha256(identity.encode()).hexdigest()
            prior = db.scalar(select(CatalogRevisionPart).where(
                CatalogRevisionPart.reference_page_id == page.id, CatalogRevisionPart.extraction_key == key))
            if prior:
                existing.append(prior.id)
                continue  # Re-extraction can never overwrite a confirmed human edit.
            values = parts._clean(selection.part.model_dump())
            item = CatalogRevisionPart(assembly_id=assembly.id, reference_page_id=page.id,
                extraction_key=key, extraction_evidence={"source": claim["source"], "row": row,
                "extractor": EXTRACTOR_VERSION, "confirmed_by_id": actor.id}, created_by_id=actor.id, **values)
            db.add(item)
            db.flush()
            db.add(CatalogRevisionPartPageMap(part_id=item.id,
                visual_page_id=claim["source"]["visual_page_id"], created_by_id=actor.id))
            created.append(item.id)
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
