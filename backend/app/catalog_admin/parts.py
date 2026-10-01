"""Draft-only parts editor and signed CSV preview/confirm import."""

from __future__ import annotations

import base64
import binascii
import csv
import hashlib
import hmac
import io
import json
import time

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..audit import add_audit_log
from ..models import (
    CatalogRevisionArtifact,
    CatalogRevisionPart,
    CatalogRevisionPartPageMap,
    CatalogRevisionPositionHotspot,
    CatalogRevisionRepairKitComponent,
    CatalogRevisionVisualPage,
    User,
    utcnow,
)
from ..settings import settings
from .schemas import PartCreate, PartImportPreview, PartPageMapCreate, PartUpdate
from .service import fail
from .visual_sources import _assembly, _meta

MAX_CSV_BYTES = 512 * 1024
MAX_CSV_ROWS = 1000
IMPORT_COLUMNS = tuple(name for name in PartCreate.model_fields if name != "sort_order")
CSV_COLUMNS = set(IMPORT_COLUMNS) | {"source_page", "source_artifact_sha256"}


def _part(db: Session, part_id: int, *, mutate: bool = False):
    item = db.get(CatalogRevisionPart, part_id)
    if item is None:
        raise fail("catalog_part_not_found", 404)
    assembly, revision, catalog = _assembly(db, item.assembly_id, mutate=mutate)
    if mutate:
        item = db.scalar(select(CatalogRevisionPart).where(CatalogRevisionPart.id == part_id)
                         .execution_options(populate_existing=True))
        if item is None or item.assembly_id != assembly.id:
            raise fail("catalog_part_not_found", 404)
    return item, assembly, revision, catalog


def _clean(values: dict) -> dict:
    cleaned = {key: value.strip() if isinstance(value, str) else value for key, value in values.items()}
    for key, value in cleaned.items():
        if isinstance(value, str):
            allowed_controls = "\n\t" if key in {"description", "description_2",
                                                "technical_specification", "technical_notes"} else ""
            if any((ord(char) < 32 and char not in allowed_controls) or 127 <= ord(char) <= 159
                   for char in value):
                raise fail("catalog_part_invalid", 422)
            if len(value) > (4000 if key in {"description", "description_2", "technical_specification", "technical_notes"}
                             else 255):
                raise fail("catalog_part_invalid", 422)
            if not value and key not in {"position", "part_number"}:
                cleaned[key] = None
    if not cleaned.get("position") or not cleaned.get("part_number"):
        raise fail("catalog_part_required", 422)
    if not any(cleaned.get(key) for key in ("name_bg", "name_en", "name_ru", "description")):
        raise fail("catalog_part_name_required", 422)
    return cleaned


def _source_pages(db: Session, assembly_id: int, reference_page_id: int | None = None) -> list[dict]:
    rows = db.execute(select(CatalogRevisionVisualPage, CatalogRevisionArtifact)
                      .join(CatalogRevisionArtifact, CatalogRevisionVisualPage.artifact_id == CatalogRevisionArtifact.id)
                      .where(CatalogRevisionArtifact.assembly_id == assembly_id,
                             CatalogRevisionVisualPage.role == "SPARE_PARTS_LIST",
                             CatalogRevisionVisualPage.reference_page_id == reference_page_id)
                      .order_by(CatalogRevisionArtifact.id, CatalogRevisionVisualPage.page_number)).all()
    return [{"visual_page_id": page.id, "artifact_id": artifact.id, "artifact_title": artifact.title,
             "filename": artifact.filename, "sha256": artifact.sha256, "page_number": page.page_number}
            for page, artifact in rows]


def spare_list_pages(db: Session, assembly_id: int, reference_page_id: int | None = None) -> list[dict]:
    _assembly(db, assembly_id)
    return _source_pages(db, assembly_id, reference_page_id)


def _maps(db: Session, part_id: int) -> list[dict]:
    rows = db.execute(select(CatalogRevisionPartPageMap, CatalogRevisionVisualPage,
                             CatalogRevisionArtifact)
                      .join(CatalogRevisionVisualPage,
                            CatalogRevisionPartPageMap.visual_page_id == CatalogRevisionVisualPage.id)
                      .join(CatalogRevisionArtifact,
                            CatalogRevisionVisualPage.artifact_id == CatalogRevisionArtifact.id)
                      .join(CatalogRevisionPart, CatalogRevisionPartPageMap.part_id == CatalogRevisionPart.id)
                      .where(CatalogRevisionPartPageMap.part_id == part_id,
                             CatalogRevisionVisualPage.role == "SPARE_PARTS_LIST",
                             CatalogRevisionArtifact.assembly_id == CatalogRevisionPart.assembly_id,
                             CatalogRevisionVisualPage.reference_page_id.is_not_distinct_from(CatalogRevisionPart.reference_page_id))
                      .order_by(CatalogRevisionPartPageMap.id)).all()
    return [{"id": mapping.id, "part_id": mapping.part_id, "visual_page_id": page.id,
             "artifact_id": artifact.id, "artifact_title": artifact.title,
             "filename": artifact.filename, "sha256": artifact.sha256,
             "page_number": page.page_number} for mapping, page, artifact in rows]


def _dict(db: Session, item: CatalogRevisionPart) -> dict:
    fields = {key: getattr(item, key) for key in PartCreate.model_fields}
    mappings = _maps(db, item.id)
    valid = (bool(item.position and item.position.strip())
             and bool(item.part_number and item.part_number.strip())
             and any(bool(getattr(item, key) and getattr(item, key).strip())
                     for key in ("name_bg", "name_en", "name_ru", "description")))
    return {"id": item.id, "assembly_id": item.assembly_id, "reference_page_id": item.reference_page_id, **fields,
            "source_pages": mappings,
            "validation_status": "READY" if mappings and valid else "INCOMPLETE",
            "created_at": item.created_at, "updated_at": item.updated_at}


def _last_position_in_use(db: Session, item: CatalogRevisionPart) -> bool:
    other = db.scalar(select(CatalogRevisionPart.id).where(
        CatalogRevisionPart.assembly_id == item.assembly_id,
        CatalogRevisionPart.position == item.position,
        CatalogRevisionPart.reference_page_id == item.reference_page_id,
        CatalogRevisionPart.id != item.id).limit(1))
    if other is not None:
        return False
    page_ids = select(CatalogRevisionVisualPage.id).join(
        CatalogRevisionArtifact, CatalogRevisionVisualPage.artifact_id == CatalogRevisionArtifact.id).where(
            CatalogRevisionArtifact.assembly_id == item.assembly_id,
            CatalogRevisionVisualPage.reference_page_id == item.reference_page_id)
    return db.scalar(select(CatalogRevisionPositionHotspot.id).where(
        CatalogRevisionPositionHotspot.visual_page_id.in_(page_ids),
        CatalogRevisionPositionHotspot.position == item.position).limit(1)) is not None


def list_parts(db: Session, assembly_id: int, *, reference_page_id: int | None = None) -> list[dict]:
    _assembly(db, assembly_id)
    query = select(CatalogRevisionPart).where(CatalogRevisionPart.assembly_id == assembly_id)
    if reference_page_id is not None:
        query = query.where(CatalogRevisionPart.reference_page_id == reference_page_id)
    items = db.scalars(query
                       .order_by(CatalogRevisionPart.sort_order, CatalogRevisionPart.id)).all()
    return [_dict(db, item) for item in items]


def get_part(db: Session, part_id: int) -> dict:
    return _dict(db, _part(db, part_id)[0])


def create_part(db: Session, actor: User, assembly_id: int, data: PartCreate, *, reference_page_id: int | None = None) -> dict:
    assembly, revision, catalog = _assembly(db, assembly_id, mutate=True)
    if reference_page_id is not None:
        from .reference_pages import load
        reference, _, _, _ = load(db, reference_page_id, mutate=True)
        if reference.assembly_id != assembly.id:
            raise fail("catalog_part_page_invalid", 422)
    values = _clean(data.model_dump())
    item = CatalogRevisionPart(assembly_id=assembly.id, reference_page_id=reference_page_id, created_by_id=actor.id, **values)
    db.add(item)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise fail("catalog_part_duplicate") from exc
    add_audit_log(db, actor, "catalog_revision_part", item.id, "BUILDER_PART_CREATED",
                  _meta(catalog, revision, assembly, position=item.position, part_number=item.part_number))
    db.commit()
    return _dict(db, item)


def update_part(db: Session, actor: User, part_id: int, data: PartUpdate) -> dict:
    item, assembly, revision, catalog = _part(db, part_id, mutate=True)
    changes = data.model_dump(exclude_unset=True)
    values = _clean({**{key: getattr(item, key) for key in PartCreate.model_fields}, **changes})
    if values["position"] != item.position and _last_position_in_use(db, item):
        raise fail("catalog_part_position_in_use")
    before = {key: getattr(item, key) for key in changes}
    for key in changes:
        setattr(item, key, values[key])
    if changes:
        item.updated_at = utcnow()
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise fail("catalog_part_duplicate") from exc
    if changes:
        add_audit_log(db, actor, "catalog_revision_part", item.id, "BUILDER_PART_UPDATED",
                      _meta(catalog, revision, assembly, before=before,
                            after={key: values[key] for key in changes}))
    db.commit()
    return _dict(db, item)


def delete_part(db: Session, actor: User, part_id: int) -> None:
    item, assembly, revision, catalog = _part(db, part_id, mutate=True)
    if db.scalar(select(CatalogRevisionRepairKitComponent.id).where(
        CatalogRevisionRepairKitComponent.part_id == item.id).limit(1)) is not None:
        raise fail("catalog_part_in_repair_kit")
    if _last_position_in_use(db, item):
        raise fail("catalog_part_position_in_use")
    removed = [row["visual_page_id"] for row in _maps(db, item.id)]
    db.execute(delete(CatalogRevisionPartPageMap).where(CatalogRevisionPartPageMap.part_id == item.id))
    add_audit_log(db, actor, "catalog_revision_part", item.id, "BUILDER_PART_DELETED",
                  _meta(catalog, revision, assembly, position=item.position,
                        part_number=item.part_number, unmapped_visual_page_ids=removed))
    db.delete(item)
    db.commit()


def list_mappings(db: Session, part_id: int) -> list[dict]:
    _part(db, part_id)
    return _maps(db, part_id)


def map_pages(db: Session, actor: User, part_id: int, data: PartPageMapCreate) -> list[dict]:
    item, assembly, revision, catalog = _part(db, part_id, mutate=True)
    ids = data.visual_page_ids
    if len(ids) != len(set(ids)):
        raise fail("catalog_part_page_duplicate")
    allowed = set(db.scalars(select(CatalogRevisionVisualPage.id).join(CatalogRevisionArtifact,
        CatalogRevisionVisualPage.artifact_id == CatalogRevisionArtifact.id).where(
        CatalogRevisionArtifact.assembly_id == assembly.id, CatalogRevisionVisualPage.role == "SPARE_PARTS_LIST",
        CatalogRevisionVisualPage.reference_page_id == item.reference_page_id)))
    if any(page_id not in allowed for page_id in ids):
        raise fail("catalog_part_page_invalid", 422)
    existing = db.scalar(select(CatalogRevisionPartPageMap.id).where(
        CatalogRevisionPartPageMap.part_id == item.id,
        CatalogRevisionPartPageMap.visual_page_id.in_(ids)).limit(1))
    if existing:
        raise fail("catalog_part_page_duplicate")
    db.add_all(CatalogRevisionPartPageMap(part_id=item.id, visual_page_id=page_id,
                                           created_by_id=actor.id) for page_id in ids)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise fail("catalog_part_page_duplicate") from exc
    add_audit_log(db, actor, "catalog_revision_part", item.id, "BUILDER_PART_SOURCE_MAPPED",
                  _meta(catalog, revision, assembly, visual_page_ids=ids))
    db.commit()
    return _maps(db, item.id)


def unmap_page(db: Session, actor: User, mapping_id: int) -> None:
    mapping = db.get(CatalogRevisionPartPageMap, mapping_id)
    if mapping is None:
        raise fail("catalog_part_page_not_found", 404)
    item, assembly, revision, catalog = _part(db, mapping.part_id, mutate=True)
    mapping = db.scalar(select(CatalogRevisionPartPageMap).where(CatalogRevisionPartPageMap.id == mapping_id)
                        .execution_options(populate_existing=True))
    if mapping is None or mapping.part_id != item.id:
        raise fail("catalog_part_page_not_found", 404)
    page_id = mapping.visual_page_id
    db.delete(mapping)
    add_audit_log(db, actor, "catalog_revision_part", item.id, "BUILDER_PART_SOURCE_UNMAPPED",
                  _meta(catalog, revision, assembly, visual_page_ids=[page_id]))
    db.commit()


def _resolve_page(row: dict, pages: list[dict]) -> tuple[list[int], list[str], list[str]]:
    page = row.get("source_page")
    sha = row.get("source_artifact_sha256")
    if not page and not sha:
        return [], [], ["catalog_part_import_unmapped"]
    if not page:
        return [], ["catalog_part_import_page_required"], []
    if len(page) > 10 or not page.isascii() or not page.isdecimal() or int(page) < 1:
        return [], ["catalog_part_import_page_invalid"], []
    if sha and (len(sha) != 64 or any(c not in "0123456789abcdef" for c in sha.lower())):
        return [], ["catalog_part_import_sha_invalid"], []
    matches = [item for item in pages if item["page_number"] == int(page)
               and (not sha or item["sha256"] == sha.lower())]
    if len(matches) != 1:
        return [], ["catalog_part_import_page_ambiguous" if matches else "catalog_part_import_page_missing"], []
    return [matches[0]["visual_page_id"]], [], []


def _preview_rows(db: Session, assembly_id: int, rows: list[dict], reference_page_id: int | None = None) -> dict:
    pages = _source_pages(db, assembly_id, reference_page_id)
    seen = set()
    existing = set(db.execute(select(CatalogRevisionPart.position, CatalogRevisionPart.part_number)
                              .where(CatalogRevisionPart.assembly_id == assembly_id, CatalogRevisionPart.reference_page_id == reference_page_id)).all())
    output = []
    duplicates = 0
    for number, raw in enumerate(rows, 2):
        errors, warnings = [], []
        try:
            data = PartCreate.model_validate({key: raw.get(key) or None for key in IMPORT_COLUMNS
                                               if key in raw and key != "sort_order"})
            normalized = _clean(data.model_dump())
        except Exception:
            normalized = {key: raw.get(key) for key in IMPORT_COLUMNS if key in raw}
            errors.append("catalog_part_invalid")
        identity = (normalized.get("position"), normalized.get("part_number"))
        duplicate = False
        if identity in seen:
            errors.append("catalog_part_import_duplicate_row")
            duplicate = True
        seen.add(identity)
        if identity in existing:
            errors.append("catalog_part_duplicate")
            duplicate = True
        duplicates += int(duplicate)
        resolved, page_errors, page_warnings = _resolve_page(raw, pages)
        errors.extend(page_errors)
        warnings.extend(page_warnings)
        output.append({"row_number": number, "normalized": normalized,
                       "status": "ERROR" if errors else "WARNING" if warnings else "VALID",
                       "errors": errors, "warnings": warnings,
                       "resolved_visual_page_ids": resolved})
    return {"rows": output, "summary": {"total_rows": len(output),
            "valid_rows": sum(row["status"] == "VALID" for row in output),
            "warning_rows": sum(row["status"] == "WARNING" for row in output),
            "error_rows": sum(row["status"] == "ERROR" for row in output),
            "duplicate_rows": duplicates}}


def _signature(payload: bytes) -> str:
    return hmac.new(settings.secret_key.encode(), payload, hashlib.sha256).hexdigest()


def read_csv(data: PartImportPreview, *, whole_catalog: bool = False) -> tuple[bytes, list[dict]]:
    """One bounded UTF-8 parser for both import scopes."""
    if (not data.filename.lower().endswith(".csv")
            or any(char in data.filename for char in "/\\")
            or any(ord(char) < 32 or 127 <= ord(char) <= 159 for char in data.filename)
            or len(data.content_base64) > ((MAX_CSV_BYTES + 2) // 3) * 4 + 4):
        raise fail("catalog_part_import_invalid_file", 422)
    try:
        content = base64.b64decode(data.content_base64, validate=True)
        if len(content) > MAX_CSV_BYTES or b"\x00" in content:
            raise ValueError("size or NUL")
        decoded = content.decode("utf-8-sig", errors="strict")
        if any((ord(char) < 32 and char not in "\r\n\t") or 127 <= ord(char) <= 159
               for char in decoded):
            raise ValueError("control")
        reader = csv.DictReader(io.StringIO(decoded, newline=""), strict=True)
        if not reader.fieldnames or len(set(reader.fieldnames)) != len(reader.fieldnames):
            raise ValueError("headers")
        required = {"position", "part_number"}
        columns = CSV_COLUMNS
        if whole_catalog:
            required |= {"assembly_code", "source_page"}
            columns = columns | {"assembly_code", "name"}
        if not required.issubset(reader.fieldnames) or set(reader.fieldnames) - columns:
            raise ValueError("headers")
        rows = []
        for row in reader:
            if len(rows) >= MAX_CSV_ROWS or None in row:
                raise ValueError("rows")
            rows.append({key: (value or "").strip() for key, value in row.items()})
        if not rows:
            raise ValueError("empty")
    except (binascii.Error, UnicodeError, csv.Error, ValueError) as exc:
        raise fail("catalog_part_import_invalid_file", 422) from exc
    return content, rows


def import_preview(db: Session, actor: User, assembly_id: int, data: PartImportPreview, reference_page_id: int | None = None) -> dict:
    _assembly(db, assembly_id, mutate=True)
    content, rows = read_csv(data)
    result = _preview_rows(db, assembly_id, rows, reference_page_id)
    source_digest = hashlib.sha256(content).hexdigest()
    payload = json.dumps({"assembly_id": assembly_id, "reference_page_id": reference_page_id, "actor_id": actor.id, "created": int(time.time()),
                          "source_digest": source_digest, "rows": rows},
                         ensure_ascii=False, separators=(",", ":")).encode()
    result["token"] = base64.urlsafe_b64encode(payload).decode().rstrip("=") + "." + _signature(payload)
    result["source_digest"] = source_digest
    return result


def import_confirm(db: Session, actor: User, assembly_id: int, token: str,
                   confirm_warnings: bool, reference_page_id: int | None = None) -> dict:
    assembly, revision, catalog = _assembly(db, assembly_id, mutate=True)
    try:
        encoded, signature = token.split(".", 1)
        payload = base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4))
        if not hmac.compare_digest(signature, _signature(payload)):
            raise ValueError("signature")
        claim = json.loads(payload)
        if claim.get("reference_page_id") != reference_page_id or claim["assembly_id"] != assembly_id or claim["actor_id"] != actor.id or abs(time.time() - claim["created"]) > 900:
            raise ValueError("binding")
        rows = claim["rows"]
        if not isinstance(rows, list) or not 1 <= len(rows) <= MAX_CSV_ROWS:
            raise ValueError("rows")
    except (binascii.Error, ValueError, KeyError, TypeError, UnicodeError) as exc:
        raise fail("catalog_part_import_token_invalid", 422) from exc
    result = _preview_rows(db, assembly_id, rows, reference_page_id)
    if result["summary"]["error_rows"]:
        raise fail("catalog_part_import_conflict")
    if result["summary"]["warning_rows"] and not confirm_warnings:
        raise fail("catalog_part_import_warning_confirmation", 422)
    created = []
    try:
        created = insert_preview_rows(db, actor, assembly, revision, catalog, result["rows"], reference_page_id)
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise fail("catalog_part_import_conflict") from exc
    add_audit_log(db, actor, "catalog_revision_assembly", assembly.id, "BUILDER_PART_IMPORT_CONFIRMED",
                  _meta(catalog, revision, assembly, row_count=len(rows), created_count=len(created),
                        source_digest=claim["source_digest"]))
    db.commit()
    return {"created_count": len(created), "part_ids": created}


def insert_preview_rows(db: Session, actor: User, assembly, revision, catalog, rows: list[dict], reference_page_id: int | None = None) -> list[int]:
    created = []
    for preview_row in rows:
        values = preview_row["normalized"]
        item = CatalogRevisionPart(assembly_id=assembly.id, reference_page_id=reference_page_id, created_by_id=actor.id, **values)
        db.add(item)
        db.flush()
        for page_id in preview_row["resolved_visual_page_ids"]:
            db.add(CatalogRevisionPartPageMap(part_id=item.id, visual_page_id=page_id,
                                               created_by_id=actor.id))
        add_audit_log(db, actor, "catalog_revision_part", item.id, "BUILDER_PART_CREATED",
                      _meta(catalog, revision, assembly, position=item.position,
                            part_number=item.part_number, source="CSV_IMPORT"))
        if preview_row["resolved_visual_page_ids"]:
            add_audit_log(db, actor, "catalog_revision_part", item.id, "BUILDER_PART_SOURCE_MAPPED",
                          _meta(catalog, revision, assembly,
                                visual_page_ids=preview_row["resolved_visual_page_ids"], source="CSV_IMPORT"))
        created.append(item.id)
    return created
