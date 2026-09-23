"""Authoritative immutable catalog evidence. Callers own the transaction."""

from __future__ import annotations

import hashlib
import json
import math
import mimetypes
from pathlib import Path, PureWindowsPath

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session, joinedload

from ..audit import add_audit_log
from ..models import (
    CatalogDiagram,
    CatalogPositionHotspot,
    CatalogVisualPartMap,
    CatalogVisualSource,
    PartCatalog,
    PartHotspot,
    PartRequestLine,
    PartVisualArtifact,
    PartVisualOccurrence,
    PartVisualSnapshot,
    TechnicalDocument,
    TechnicalDocumentRevision,
    User,
    utcnow,
)
from ..workflow import business_conflict

CATALOG_FIELDS = (
    "source_row_index",
    "source_version",
    "source_document_sha256",
    "revision",
    "verification_status",
    "is_verified",
    "verified_by_id",
    "verified_at",
    "position",
    "part_number",
    "replaced_by_part_number",
    "description",
    "original_name",
    "manufacturer",
    "brand",
    "model",
    "family",
    "assembly",
    "unit",
    "source_document",
    "source_page",
    "source_figure",
    "diagram_page",
)
OCCURRENCE_FIELDS = (
    "ordinal",
    "source_kind",
    "hotspot_id",
    "technical_document_id",
    "diagram_id",
    "page_number",
    "x",
    "y",
    "width",
    "height",
    "artifact_sha256",
    "source_metadata",
)


def fingerprint(value: dict) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


def _filename(value: str | None) -> str | None:
    # Both separator conventions, independent of the host operating system.
    return PureWindowsPath(value).name if value else None


def _integrity_error() -> HTTPException:
    return business_conflict(
        "visual_snapshot_source_integrity_failed",
        "Визуалният източник не може да бъде запазен с потвърдена цялост.",
    )


def _read_source_file(relative: str | None) -> bytes:
    root = Path(__file__).resolve().parents[2] / "resources" / "technical_docs"
    if not relative or PureWindowsPath(relative).is_absolute():
        raise _integrity_error()
    path = (root / relative).resolve()
    if root.resolve() not in path.parents or not path.is_file():
        raise _integrity_error()
    try:
        return path.read_bytes()
    except OSError as exc:
        raise _integrity_error() from exc


def resolve_catalog_part(db: Session, catalog_part_id: int) -> PartCatalog:
    statement = select(PartCatalog).where(PartCatalog.id == catalog_part_id)
    if db.get_bind().dialect.name == "postgresql":
        statement = statement.with_for_update(read=True)
    part = db.scalar(statement.execution_options(populate_existing=True))
    if part is None:
        raise HTTPException(404, "Каталожната част не е намерена.")
    if not part.is_verified or not part.is_active:
        raise business_conflict(
            "unverified_catalog_parts",
            "Непотвърдена каталожна част не може да бъде добавена към официална заявка.",
            catalog_part_id=part.id,
        )
    return part


def _source_artifact(
    db: Session,
    document: TechnicalDocument | None,
    expected_hash: str | None,
) -> tuple[str, dict, bytes]:
    if document is None:
        raise _integrity_error()
    expected_hash = expected_hash or document.sha256
    revision = None
    if expected_hash:
        revision = db.scalar(
            select(TechnicalDocumentRevision)
            .where(
                TechnicalDocumentRevision.document_id == document.id,
                TechnicalDocumentRevision.sha256 == expected_hash,
            )
            .order_by(TechnicalDocumentRevision.version.desc())
        )
    if revision is not None:
        content = (
            revision.content
            if revision.content is not None
            else _read_source_file(revision.file_path)
        )
        filename = _filename(revision.filename)
        media_type = revision.media_type
    else:
        content = (
            document.uploaded_content
            if document.uploaded_content is not None
            else _read_source_file(document.file_path)
        )
        filename = _filename(document.uploaded_filename or document.file_path)
        media_type = document.media_type
    digest = hashlib.sha256(content).hexdigest()
    if not content or (expected_hash and digest != expected_hash):
        raise _integrity_error()
    # Never infer part/diagram identity from a filename; this is format detection only.
    media_type = media_type or mimetypes.guess_type(filename or "")[0] or "application/octet-stream"
    values = {"sha256": digest, "content": content, "byte_length": len(content)}
    insert = pg_insert if db.get_bind().dialect.name == "postgresql" else sqlite_insert
    db.execute(
        insert(PartVisualArtifact)
        .values(**values)
        .on_conflict_do_nothing(index_elements=["sha256"])
    )
    artifact = db.get(PartVisualArtifact, digest)
    if artifact is None or artifact.byte_length != len(content) or artifact.content != content:
        raise _integrity_error()
    return (
        digest,
        {
            "document_title": document.title,
            "document_source_id": document.source_id,
            "document_dataset_version": document.dataset_version,
            "document_revision": document.revision,
            "document_sha256": document.sha256,
            "revision_id": revision.id if revision else None,
            "revision_version": revision.version if revision else None,
            "revision_label": revision.revision_label if revision else None,
            "filename": filename,
            "media_type": media_type,
            "byte_length": len(content),
        },
        content,
    )


def _validate_visual(content: bytes, media_type: str, page: int, geometry: dict) -> None:
    if page < 1 or any(not math.isfinite(value) for value in geometry.values()):
        raise _integrity_error()
    x, y, width, height = (geometry[name] for name in ("x", "y", "width", "height"))
    if min(x, y) < 0 or min(width, height) <= 0 or x + width > 1.000001 or y + height > 1.000001:
        raise _integrity_error()
    _validate_page(content, media_type, page)


def _validate_page(content: bytes, media_type: str, page: int) -> None:
    if page < 1:
        raise _integrity_error()
    # Verify that the retained bytes can reproduce the declared visual page.
    try:
        import fitz

        with fitz.open(stream=content, filetype=media_type.split("/")[-1]) as source:
            if page > source.page_count:
                raise _integrity_error()
    except HTTPException:
        raise
    except Exception as exc:
        raise _integrity_error() from exc


def _visual_source(
    db: Session, part: PartCatalog, document: TechnicalDocument, page: int,
    *, diagram: CatalogDiagram | None = None,
) -> CatalogVisualSource | None:
    identity = (
        CatalogVisualSource.source_id == part.source_id,
        CatalogVisualSource.technical_document_id == document.id,
        CatalogVisualSource.page_number == page,
    )
    if diagram is not None:
        identity += (CatalogVisualSource.role == "EXPLODED_SCHEME",)
    candidates = db.scalars(select(CatalogVisualSource).where(
        *identity, CatalogVisualSource.catalog_revision == part.source_version,
    )).all()
    if len(candidates) > 1:
        raise _integrity_error()
    visual = candidates[0] if candidates else None
    if visual is None and db.scalar(
        select(CatalogVisualSource.id).where(*identity).limit(1)
    ) is not None:
        # A source exists, but only for another revision. Never silently use it.
        raise _integrity_error()
    return visual


def _page_references(db: Session, part: PartCatalog) -> list[dict]:
    mapped = db.scalars(
        select(CatalogVisualPartMap)
        .join(CatalogVisualSource)
        .options(joinedload(CatalogVisualPartMap.visual_source).joinedload(
            CatalogVisualSource.technical_document
        ))
        .where(
            CatalogVisualPartMap.part_id == part.id,
            CatalogVisualSource.catalog_revision == part.source_version,
        )
        .order_by(CatalogVisualSource.role, CatalogVisualSource.source_sha256,
                  CatalogVisualSource.page_number, CatalogVisualPartMap.id)
    ).all()
    if not mapped and db.scalar(
        select(CatalogVisualPartMap.id)
        .where(CatalogVisualPartMap.part_id == part.id)
        .limit(1)
    ) is not None:
        # Historical mappings may remain, but a new request needs this revision.
        raise _integrity_error()
    references = []
    for mapping in mapped:
        source = mapping.visual_source
        if source.source_id != part.source_id or source.role != "SPARE_PARTS_LIST":
            raise _integrity_error()
        digest, metadata, content = _source_artifact(
            db, source.technical_document, source.source_sha256
        )
        _validate_page(content, metadata["media_type"], source.page_number)
        references.append({
            "visual_role": source.role,
            "catalog_visual_source_id": source.id,
            "catalog_visual_part_map_id": mapping.id,
            "catalog_revision": source.catalog_revision,
            "artifact_sha256": digest,
            "page_number": source.page_number,
            "source_metadata": metadata,
        })
    return references


def _occurrences(db: Session, part: PartCatalog) -> list[dict]:
    references = []
    direct = db.scalars(
        select(PartHotspot)
        .options(
            joinedload(PartHotspot.technical_document),
        )
        .where(PartHotspot.part_id == part.id, PartHotspot.is_verified.is_(True))
    ).all()
    for hotspot in direct:
        references.append(("PART_HOTSPOT", hotspot, None, hotspot.technical_document))
    if part.source_id is not None and part.position is not None:
        positions = db.scalars(
            select(CatalogPositionHotspot)
            .join(CatalogDiagram)
            .options(
                joinedload(CatalogPositionHotspot.diagram).joinedload(
                    CatalogDiagram.technical_document
                ),
            )
            .where(
                CatalogDiagram.source_id == part.source_id,
                CatalogPositionHotspot.position == part.position,
                CatalogPositionHotspot.is_verified.is_(True),
            )
        ).all()
        for hotspot in positions:
            diagram = hotspot.diagram
            if (
                part.source_document_sha256
                and diagram.source_pdf_sha256 != part.source_document_sha256
            ):
                raise _integrity_error()
            references.append(("POSITION_HOTSPOT", hotspot, diagram, diagram.technical_document))
    references.sort(
        key=lambda item: (
            item[0],
            item[3].id if item[3] else 0,
            item[2].page_number if item[2] else item[1].page_number,
            item[2].id if item[2] else 0,
            item[1].id,
        )
    )
    captured = []
    sources = {}
    for ordinal, (kind, hotspot, diagram, document) in enumerate(references, 1):
        if document is None:
            raise _integrity_error()
        page = diagram.page_number if diagram else hotspot.page_number
        visual_source = _visual_source(db, part, document, page, diagram=diagram)
        expected_hash = (
            diagram.source_pdf_sha256 if diagram else
            visual_source.source_sha256 if visual_source else None
        )
        if visual_source is not None and diagram is not None and (
            visual_source.source_sha256 != expected_hash
        ):
            raise _integrity_error()
        key = (document.id, expected_hash)
        if key not in sources:
            sources[key] = _source_artifact(db, document, expected_hash)
        digest, metadata, content = sources[key]
        geometry = {name: float(getattr(hotspot, name)) for name in ("x", "y", "width", "height")}
        _validate_visual(content, metadata["media_type"], page, geometry)
        captured.append(
            {
                "ordinal": ordinal,
                "source_kind": kind,
                "hotspot_id": hotspot.id,
                "technical_document_id": document.id,
                "diagram_id": diagram.id if diagram else None,
                "page_number": page,
                **geometry,
                "artifact_sha256": digest,
                "source_metadata": {
                    **metadata,
                    "hotspot_key": getattr(hotspot, "hotspot_key", None),
                    "label": hotspot.position if diagram else hotspot.label,
                    "provenance": hotspot.provenance,
                    "confidence": hotspot.confidence,
                    "is_verified": hotspot.is_verified,
                    "verified_by_id": getattr(hotspot, "verified_by_id", None),
                    "verified_at": (
                        hotspot.verified_at.isoformat()
                        if getattr(hotspot, "verified_at", None)
                        else None
                    ),
                    "diagram_title": diagram.title if diagram else None,
                    "diagram_source_id": diagram.source_id if diagram else None,
                    "diagram_source_sha256": expected_hash,
                    "render_version": diagram.render_version if diagram else None,
                    "visual_role": visual_source.role if visual_source else (
                        "EXPLODED_SCHEME" if diagram else None
                    ),
                    "catalog_visual_source_id": visual_source.id if visual_source else None,
                    "catalog_revision": (
                        visual_source.catalog_revision if visual_source else part.source_version
                    ),
                },
            }
        )
    return captured


def _snapshot_payload(snapshot: PartVisualSnapshot) -> dict:
    return {
        "schema_version": snapshot.schema_version,
        "line_id": snapshot.line_id,
        "catalog_part_id": snapshot.catalog_part_id,
        "source_id": snapshot.source_id,
        "source_record_key": snapshot.source_record_key,
        "captured_at": snapshot.captured_at.isoformat(),
        "capture_origin": snapshot.capture_origin,
        "catalog": snapshot.catalog,
        "occurrence_count": snapshot.occurrence_count,
        "visual_references": [
            {name: getattr(value, name) for name in OCCURRENCE_FIELDS}
            for value in snapshot.occurrences
        ],
    }


def _capture_snapshot(
    db: Session, line: PartRequestLine, user: User, *, origin: str
) -> PartVisualSnapshot:
    """Freeze exactly once; no commits or historical backfill, regardless of caller."""
    part_id = line.linked_catalog_part_id if origin == "CATALOG_LINK" else line.catalog_part_id
    if part_id is None:
        raise ValueError("A catalog binding is required")
    if line.visual_snapshot is not None:
        if (
            line.visual_snapshot.catalog_part_id != part_id
            or line.visual_snapshot.capture_origin != origin
        ):
            raise business_conflict(
                "visual_snapshot_binding_conflict", "Редът вече има историческа връзка."
            )
        return line.visual_snapshot
    part = resolve_catalog_part(db, part_id)
    catalog = {name: getattr(part, name) for name in CATALOG_FIELDS}
    catalog["verified_at"] = part.verified_at.isoformat() if part.verified_at else None
    catalog["source_document"] = _filename(part.source_document)
    catalog["requested_part_number"] = part.replaced_by_part_number or part.part_number
    catalog["visual_pages"] = _page_references(db, part)
    references = _occurrences(db, part)
    snapshot = PartVisualSnapshot(
        line=line,
        catalog_part_id=part.id,
        source_id=part.source_id,
        source_record_key=part.source_record_key,
        schema_version=1,
        captured_at=line.linked_at if origin == "CATALOG_LINK" else utcnow(),
        capture_origin=origin,
        catalog=catalog,
        occurrence_count=len(references),
    )
    snapshot.line_id = line.id
    snapshot.occurrences = [PartVisualOccurrence(**values) for values in references]
    snapshot.sha256 = fingerprint(_snapshot_payload(snapshot))
    db.add(snapshot)
    db.flush()
    add_audit_log(
        db,
        user,
        "part_visual_snapshot",
        snapshot.id,
        "Запазен неизменим визуален произход на заявена част",
        {
            "request_reference": line.request.request_reference,
            "line_id": line.id,
            "catalog_part_id": part.id,
            "source_id": part.source_id,
            "source_record_key": part.source_record_key,
            "capture_origin": origin,
            "visual_reference_count": len(references),
            "snapshot_sha256": snapshot.sha256,
            "artifact_sha256": sorted({value["artifact_sha256"] for value in references}),
        },
        line.request.request_reference,
    )
    return snapshot


def capture_snapshot(
    db: Session, line: PartRequestLine, user: User, *, origin: str
) -> PartVisualSnapshot:
    try:
        return _capture_snapshot(db, line, user, origin=origin)
    except Exception:
        # Includes the outer request/link work, not merely an inner savepoint.
        db.rollback()
        raise


def create_request_line(db: Session, request_id: int, values: dict, user: User) -> PartRequestLine:
    """The production catalog-line writer; client metadata never defines evidence."""
    values = dict(values)
    if values.get("catalog_part_id") is not None:
        part = resolve_catalog_part(db, values["catalog_part_id"])
        values.update(
            {
                name: getattr(part, name)
                for name in (
                    "position",
                    "description",
                    "unit",
                    "source_document",
                    "source_page",
                    "assembly",
                )
            }
        )
        values["part_number"] = part.replaced_by_part_number or part.part_number
    line = PartRequestLine(request_id=request_id, **values)
    db.add(line)
    db.flush()
    if line.catalog_part_id is not None:
        capture_snapshot(db, line, user, origin="REQUEST_CREATION")
    return line


def snapshot_response(line: PartRequestLine) -> dict:
    snapshot = line.visual_snapshot
    if snapshot is None:
        state = (
            "legacy_snapshot_unavailable"
            if line.catalog_part_id is not None or line.linked_catalog_part_id is not None
            else "no_catalog_binding"
        )
        return {"state": state, "snapshot": None}
    payload = _snapshot_payload(snapshot)
    if (
        len(payload["visual_references"]) != snapshot.occurrence_count
        or fingerprint(payload) != snapshot.sha256
    ):
        raise _integrity_error()
    return {
        "state": "verified_visual_references"
        if snapshot.occurrence_count or payload["catalog"].get("visual_pages")
        else "no_visual_reference_at_capture",
        "snapshot": {"id": snapshot.id, "sha256": snapshot.sha256, **payload},
    }


def snapshot_document_reference(line: PartRequestLine) -> dict | None:
    snapshot = line.visual_snapshot
    return {"id": snapshot.id, "sha256": snapshot.sha256} if snapshot else None
