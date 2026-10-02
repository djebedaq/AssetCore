"""Additive simple workflow; the existing Builder services remain authoritative."""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import re
import time
import unicodedata
from collections import defaultdict
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..audit import add_audit_log
from ..models import CatalogRevision, CatalogRevisionAssembly, User
from . import parts, publication, service, visual_sources
from .schemas import AssemblyCreate, CatalogCreate, PartImportPreview, SimpleCatalogCreate


def display_name(value: str) -> str:
    value = value.strip()
    if not value or any(ord(char) < 32 or 127 <= ord(char) <= 159 for char in value):
        raise service.fail("catalog_invalid_update", 422)
    return value


def generated_code(value: str, prefix: str) -> str:
    stem = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode().upper()
    stem = re.sub(r"[^A-Z0-9]+", "_", stem).strip("_")
    if not stem or not stem[0].isalpha():
        stem = f"{prefix}_{stem}".rstrip("_")
    # Database uniqueness is the final guard, including concurrent creations.
    return f"{stem[:47]}_{uuid4().hex.upper()}"


def create_catalog(db: Session, actor: User, data: SimpleCatalogCreate) -> dict:
    name = display_name(data.name)
    return service.create_catalog(db, actor, CatalogCreate(
        code=generated_code(" ".join(filter(None, [data.manufacturer, data.model_reference, name])), "CATALOG"),
        asset_category_id=data.asset_category_id, name_bg=name, name_en=name, name_ru=name,
        manufacturer=data.manufacturer, model_reference=data.model_reference,
    ), initial_draft=True)


def group_code(db: Session, revision_id: int, name: str) -> str:
    """Caller holds the established catalog/revision lock until insertion."""
    cyrillic = dict(zip(
        "АБВГДЕЖЗИЙКЛМНОПРСТУФХЦЧШЩЪЬЮЯЁЫЭ",
        ("A", "B", "V", "G", "D", "E", "ZH", "Z", "I", "Y", "K", "L", "M", "N", "O",
         "P", "R", "S", "T", "U", "F", "H", "TS", "CH", "SH", "SHT", "A", "", "YU", "YA",
         "YO", "Y", "E"), strict=True))
    romanized = name.upper().translate(str.maketrans(cyrillic))
    stem = unicodedata.normalize("NFKD", romanized).encode("ascii", "ignore").decode()
    stem = re.sub(r"[^A-Z0-9]+", "_", stem).strip("_")
    if not stem or not stem[0].isalpha() or len(stem) < 2:
        stem = f"GROUP_{stem}".rstrip("_")
    used = set(db.scalars(select(CatalogRevisionAssembly.code).where(
        CatalogRevisionAssembly.revision_id == revision_id)).all())
    number = 1
    while True:
        suffix = "" if number == 1 else f"_{number}"
        candidate = stem[:80 - len(suffix)] + suffix
        if candidate not in used:
            return candidate
        number += 1


def create_group(db: Session, actor: User, revision_id: int, name: str) -> dict:
    visual_sources._revision(db, revision_id, mutate=True)
    name = display_name(name)
    order = db.scalar(select(func.max(CatalogRevisionAssembly.sort_order)).where(
        CatalogRevisionAssembly.revision_id == revision_id))
    return visual_sources.create_assembly(db, actor, revision_id, AssemblyCreate(
        code=group_code(db, revision_id, name), name_bg=name, name_en=name, name_ru=name,
        sort_order=(order or 0) + 1,
    ))


def edit_catalog(db: Session, actor: User, catalog_id: int) -> dict:
    catalog = service.catalog(db, catalog_id, lock=True)
    if not catalog.is_active:
        raise service.fail("catalog_inactive")
    rows = db.scalars(select(CatalogRevision).where(CatalogRevision.catalog_id == catalog_id)
                      .order_by(CatalogRevision.id.desc())).all()
    draft = next((row for row in rows if row.status == "DRAFT"), None)
    if draft:
        return service.revision_dict(draft)
    published = next((row for row in rows if row.status == "PUBLISHED"), None)
    used = {row.revision_code for row in rows}
    number = 1
    while f"REV-{number}" in used:
        number += 1
    code = f"REV-{number}"
    if published:
        return publication.clone(db, actor, published.id, code, None)
    from .schemas import RevisionCreate
    return service.create_revision(db, actor, catalog_id, RevisionCreate(revision_code=code))


def _context_digest(db: Session, revision, catalog) -> str:
    return publication.digest(catalog, revision, publication.graph(db, revision))


def workflow(db: Session, revision_id: int) -> dict:
    revision, _ = visual_sources._revision(db, revision_id)
    result = publication.readiness(db, revision_id)
    content = publication.graph(db, revision)
    artifacts = {row.id: row for row in content["artifacts"]}
    pages = {row.id: row for row in content["pages"]}
    part_rows = {row.id: row for row in content["parts"]}
    hotspots = {row.id: row for row in content["hotspots"]}
    kits = {row.id: row for row in content["kits"]}
    maps = {row.id: row for row in content["maps"]}
    components = {row.id: row for row in content["components"]}
    reference_pages = {row.id: row for row in content["reference_pages"]}
    for issue in result["errors"] + result["warnings"]:
        part = part_rows.get(issue.get("part_id"))
        if issue.get("mapping_id") in maps:
            part = part_rows.get(maps[issue["mapping_id"]].part_id)
        hotspot = hotspots.get(issue.get("hotspot_id"))
        page = pages.get(issue.get("visual_page_id") or (hotspot.visual_page_id if hotspot else None))
        artifact = artifacts.get(issue.get("artifact_id") or (page.artifact_id if page else None))
        kit = kits.get(issue.get("kit_id"))
        if issue.get("component_id") in components:
            kit = kits.get(components[issue["component_id"]].kit_id)
        logical_page_id = issue.get("reference_page_id") or (part.reference_page_id if part else page.reference_page_id if page else None)
        if logical_page_id in reference_pages:
            issue.update(reference_page_id=logical_page_id, assembly_id=reference_pages[logical_page_id].assembly_id)
        if part:
            issue.update(assembly_id=part.assembly_id, part_id=part.id, step="parts")
        elif hotspot:
            issue.update(assembly_id=artifact.assembly_id if artifact else None,
                         position=hotspot.position, visual_page_id=hotspot.visual_page_id, step="hotspots")
        elif kit:
            issue.update(assembly_id=kit.assembly_id, step="kits")
        elif artifact:
            issue.update(assembly_id=artifact.assembly_id, step="documents")
        elif "hotspot" in issue["code"]:
            issue["step"] = "hotspots"
        else:
            issue["step"] = "documents"
    positions = {(row.assembly_id, row.reference_page_id, row.position) for row in content["parts"]}
    marked = set()
    unconfirmed = set()
    for hotspot in content["hotspots"]:
        page = pages.get(hotspot.visual_page_id)
        artifact = artifacts.get(page.artifact_id) if page else None
        if artifact:
            identity = (artifact.assembly_id, page.reference_page_id, hotspot.position)
            if hotspot.is_verified:
                marked.add(identity)
            else:
                unconfirmed.add(identity)
    marked -= unconfirmed
    result["progress"] = {"position_count": len(positions), "completed_positions": len(marked & positions)}
    incomplete_parts = any(issue["step"] == "parts" for issue in result["errors"])
    incomplete_hotspots = any(issue["step"] == "hotspots" for issue in result["errors"])
    result["resume_step"] = ("references" if not content["assemblies"] else "documents" if not content["pages"]
                            else "parts" if not content["parts"] or incomplete_parts
                            else "hotspots" if positions - marked or incomplete_hotspots else "review")
    return result


def _preview(db: Session, revision_id: int, rows: list[dict]) -> dict:
    groups = {row.code: row for row in db.scalars(select(CatalogRevisionAssembly).where(
        CatalogRevisionAssembly.revision_id == revision_id)).all()}
    indexed = defaultdict(list)
    output = []
    for index, raw in enumerate(rows):
        code = raw.get("assembly_code", "")
        if code not in groups:
            output.append({"row_number": index + 2, "assembly_code": code, "assembly_id": None,
                           "normalized": raw, "status": "ERROR", "errors": ["catalog_import_group_missing"],
                           "warnings": [], "resolved_visual_page_ids": []})
        else:
            if not any(value for key, value in raw.items() if key not in {"assembly_code", "assembly_name"}):
                output.append({"row_number": index + 2, "assembly_code": code, "assembly_id": groups[code].id,
                               "normalized": raw, "status": "ERROR", "errors": ["catalog_import_template_row"],
                               "warnings": [], "resolved_visual_page_ids": []})
                continue
            normalized = dict(raw)
            name = raw.get("name") or next((raw.get(key) for key in ("name_bg", "name_en", "name_ru") if raw.get(key)), None)
            if name:
                for key in ("name_bg", "name_en", "name_ru"):
                    normalized[key] = raw.get(key) or name
            indexed[code].append((index, normalized))
    duplicates = 0
    for code, values in indexed.items():
        preview = parts._preview_rows(db, groups[code].id, [raw for _, raw in values])
        duplicates += preview["summary"]["duplicate_rows"]
        for (index, raw), row in zip(values, preview["rows"], strict=True):
            row.update(row_number=index + 2, assembly_code=code, assembly_id=groups[code].id, source_page=raw.get("source_page"))
            if not raw.get("source_page"):
                row["errors"].append("catalog_part_import_page_required")
                row["warnings"] = []
                row["status"] = "ERROR"
            output.append(row)
    output.sort(key=lambda row: row["row_number"])
    return {"rows": output, "summary": {
        "total_rows": len(output), "valid_rows": sum(row["status"] == "VALID" for row in output),
        "warning_rows": sum(row["status"] == "WARNING" for row in output),
        "error_rows": sum(row["status"] == "ERROR" for row in output), "duplicate_rows": duplicates,
    }}


def import_preview(db: Session, actor: User, revision_id: int, data: PartImportPreview) -> dict:
    revision, catalog = visual_sources._revision(db, revision_id, mutate=True)
    content, rows = parts.read_csv(data, whole_catalog=True)
    result = _preview(db, revision_id, rows)
    claim = {"revision_id": revision_id, "actor_id": actor.id, "created": int(time.time()),
             "rows": rows, "source_digest": hashlib.sha256(content).hexdigest(),
             "context_digest": _context_digest(db, revision, catalog)}
    payload = json.dumps(claim, ensure_ascii=False, separators=(",", ":")).encode()
    result["token"] = base64.urlsafe_b64encode(payload).decode().rstrip("=") + "." + parts._signature(payload)
    result["source_digest"] = claim["source_digest"]
    return result


def import_confirm(db: Session, actor: User, revision_id: int, token: str, confirm_warnings: bool) -> dict:
    revision, catalog = visual_sources._revision(db, revision_id, mutate=True)
    try:
        encoded, signature = token.split(".", 1)
        payload = base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4))
        if not hmac.compare_digest(signature, parts._signature(payload)):
            raise ValueError("signature")
        claim = json.loads(payload)
        if (claim["revision_id"] != revision_id or claim["actor_id"] != actor.id
                or not 0 <= time.time() - claim["created"] <= 900):
            raise ValueError("binding")
        rows = claim["rows"]
        if not isinstance(rows, list) or not 1 <= len(rows) <= parts.MAX_CSV_ROWS:
            raise ValueError("rows")
    except (binascii.Error, ValueError, KeyError, TypeError, UnicodeError) as exc:
        raise service.fail("catalog_part_import_token_invalid", 422) from exc
    if claim.get("context_digest") != _context_digest(db, revision, catalog):
        raise service.fail("catalog_part_import_conflict")
    result = _preview(db, revision_id, rows)
    if result["summary"]["error_rows"]:
        raise service.fail("catalog_part_import_conflict")
    if result["summary"]["warning_rows"] and not confirm_warnings:
        raise service.fail("catalog_part_import_warning_confirmation", 422)
    grouped = defaultdict(list)
    for row in result["rows"]:
        grouped[row["assembly_id"]].append(row)
    created = []
    try:
        for assembly_id, preview_rows in grouped.items():
            assembly = db.get(CatalogRevisionAssembly, assembly_id)
            created.extend(parts.insert_preview_rows(db, actor, assembly, revision, catalog, preview_rows))
            add_audit_log(db, actor, "catalog_revision_assembly", assembly_id, "BUILDER_PART_IMPORT_CONFIRMED",
                          visual_sources._meta(catalog, revision, assembly, row_count=len(preview_rows),
                                               source_digest=claim["source_digest"], scope="CATALOG"))
        db.flush()
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise service.fail("catalog_part_import_conflict") from exc
    return {"created_count": len(created), "part_ids": created}


def csv_template(db: Session, revision_id: int) -> bytes:
    """Blank rows expose real stable group codes without inventing industrial parts."""
    import csv
    import io

    visual_sources._revision(db, revision_id)
    columns = ["assembly_code", "position", "part_number", "name", "quantity", "source_page"]
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=columns)
    writer.writeheader()
    for assembly in db.scalars(select(CatalogRevisionAssembly).where(
            CatalogRevisionAssembly.revision_id == revision_id).order_by(
                CatalogRevisionAssembly.sort_order, CatalogRevisionAssembly.id)).all():
        writer.writerow({"assembly_code": assembly.code})
    return stream.getvalue().encode("utf-8-sig")
