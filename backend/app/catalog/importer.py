from __future__ import annotations

import mimetypes
from collections import defaultdict
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..audit import add_audit_log
from ..models import (
    CatalogDiagram,
    CatalogPositionHotspot,
    Machine,
    PartCatalog,
    RepairKit,
    RepairKitComponent,
    TechnicalDocument,
    TechnicalDocumentRevision,
    User,
    utcnow,
)
from .position_mapping import MANUALLY_CONFIRMED, is_manually_confirmed
from .sources import (
    CATALOG_VERSION,
    dataset_sources,
    load_manifest,
    load_source_dataset,
    source_path,
    source_relative_path,
)
from .validation import validate_catalog_v2


class CatalogImportError(RuntimeError):
    pass


def _verified_machine_numbers(db: Session, family: str) -> list[str]:
    metadata = load_manifest()["families"][family]
    expected = {str(number) for number in metadata["machine_numbers"]}
    machines = list(
        db.scalars(select(Machine).where(Machine.inventory_number.in_(expected)))
    )
    found = {str(machine.inventory_number) for machine in machines}
    if found != expected:
        raise CatalogImportError(
            f"Липсва проверена машина за каталожно семейство {family}: "
            f"{sorted(expected - found)}"
        )
    invalid = [
        machine.inventory_number
        for machine in machines
        if machine.brand != metadata["brand"] or machine.model != metadata["model"]
    ]
    if invalid:
        raise CatalogImportError(
            f"Несъответстваща canonical family mapping за машини: {sorted(invalid)}"
        )
    return sorted(expected, key=int)


def _upsert_documents(
    db: Session, verifier: User, counters: dict[str, int]
) -> dict[str, TechnicalDocument]:
    active_paths = {source_relative_path(source) for source in dataset_sources()}
    for document in db.scalars(select(TechnicalDocument)).all():
        if (
            document.file_path not in active_paths
            and document.uploaded_content is None
            and document.is_active
        ):
            document.is_active = False
            counters["archived_documents"] += 1

    documents: dict[str, TechnicalDocument] = {}
    manifest = load_manifest()
    for source in dataset_sources():
        relative = source_relative_path(source)
        document = db.scalar(
            select(TechnicalDocument).where(TechnicalDocument.file_path == relative)
        )
        is_new = document is None
        family = manifest["families"][source["family"]]
        if document is None:
            document = TechnicalDocument(
                brand=family["brand"],
                model=family["model"],
                category=(
                    "Контрол на обхвата на каталога"
                    if source.get("import_status") == "SCOPE_CONTROL"
                    else "Каталог резервни части"
                ),
                title=source["document_title"],
                file_path=relative,
            )
            db.add(document)
            counters["created_documents"] += 1
        else:
            counters["updated_documents"] += 1
        document.brand = family["brand"]
        document.model = family["model"]
        document.category = (
            "Контрол на обхвата на каталога"
            if source.get("import_status") == "SCOPE_CONTROL"
            else "Каталог резервни части"
        )
        document.title = source["document_title"]
        document.revision = source.get("document_reference")
        document.source_id = source["source_id"]
        document.dataset_version = CATALOG_VERSION
        document.allowed_pages = source.get("allowed_pages") or []
        document.page_count = source.get("page_count")
        document.sha256 = source["sha256"]
        document.source_label = source.get("document_reference") or source["document_title"]
        document.source_date = (
            datetime.fromisoformat(source["source_date"])
            if source.get("source_date")
            else None
        )
        document.document_date = document.source_date
        document.linked_machine_numbers = _verified_machine_numbers(db, source["family"])
        document.tags = [CATALOG_VERSION, source["family"], source["assembly"]]
        document.notes = (
            f"Допустим обхват: {source['allowed_scope']}."
            if source.get("allowed_scope")
            else "Контролиран authoritative source за активния каталог."
        )
        document.uploaded_filename = source_path(source).name
        document.media_type = (
            mimetypes.guess_type(source_path(source).name)[0]
            or "application/octet-stream"
        )
        document.extracted_text = (
            source_path(source).read_text(encoding="utf-8")
            if source_path(source).suffix.lower() == ".txt"
            else None
        )
        document.is_active = True
        document.created_at = document.created_at or utcnow()
        db.flush()
        if is_new or not db.scalar(
            select(TechnicalDocumentRevision.id).where(
                TechnicalDocumentRevision.document_id == document.id,
                TechnicalDocumentRevision.version == 1,
            )
        ):
            document.revisions.append(
                TechnicalDocumentRevision(
                    version=1,
                    revision_label=source.get("document_reference"),
                    filename=source_path(source).name,
                    media_type=document.media_type,
                    file_path=relative,
                    sha256=source["sha256"],
                    change_note=(
                        f"Проверен източник от {CATALOG_VERSION}; "
                        "оригиналният файл не се променя."
                    ),
                    created_by_id=verifier.id,
                )
            )
        documents[source["source_id"]] = document
    return documents


def _upsert_parts(
    db: Session, verifier: User, counters: dict[str, int]
) -> dict[str, PartCatalog]:
    for part in db.scalars(select(PartCatalog).where(PartCatalog.is_active.is_(True))):
        if part.source_version != CATALOG_VERSION:
            part.is_active = False
            counters["archived_parts"] += 1

    parts: dict[str, PartCatalog] = {}
    machine_numbers = {
        family: _verified_machine_numbers(db, family)
        for family in load_manifest()["families"]
    }
    for source in dataset_sources():
        for data in load_source_dataset(source).get("records") or []:
            item = db.scalar(
                select(PartCatalog).where(
                    PartCatalog.source_record_key == data["source_record_key"]
                )
            )
            if item is None:
                item = PartCatalog(
                    source_record_key=data["source_record_key"],
                    brand=data["brand"],
                    part_number=data["part_number"],
                    description=data["description"],
                )
                db.add(item)
                counters["created_parts"] += 1
            else:
                counters["updated_parts"] += 1
            values = {
                **data,
                "category": "SPARE_PART",
                "compatible_models": data["model"],
                "compatible_machine_numbers": machine_numbers[data["family"]],
                "name_bg": None,
                "name_en": data.get("description_en") or None,
                "name_ru": None,
                "unit": None,
                "source_excerpt": data["source_record_key"],
                "provenance_confidence": 1.0,
            }
            for field in (
                "source_record_key",
                "source_id",
                "source_row_index",
                "family",
                "manufacturer",
                "brand",
                "model",
                "assembly",
                "position",
                "part_number",
                "description",
                "quantity",
                "quantity_raw",
                "description_de",
                "description_en",
                "description_fr",
                "description_2",
                "valid_for_raw",
                "repair_kit_code",
                "source_anomaly_codes",
                "original_name",
                "technical_specification",
                "source_document",
                "source_page",
                "source_figure",
                "diagram_page",
                "source_version",
                "source_document_sha256",
                "verification_status",
                "replaced_by_part_number",
                "category",
                "compatible_models",
                "compatible_machine_numbers",
                "name_bg",
                "name_en",
                "name_ru",
                "unit",
                "source_excerpt",
                "provenance_confidence",
            ):
                setattr(item, field, values.get(field) or None)
            # Empty source part numbers and quantity_raw values are meaningful.
            item.part_number = data["part_number"]
            item.quantity_raw = data.get("quantity_raw") or ""
            item.is_active = True
            item.is_verified = True
            item.verified_by_id = verifier.id
            item.verified_at = item.verified_at or utcnow()
            parts[data["source_record_key"]] = item
    db.flush()
    return parts


def _upsert_diagrams_and_hotspots(
    db: Session,
    verifier: User,
    documents: dict[str, TechnicalDocument],
    counters: dict[str, int],
) -> None:
    for source in dataset_sources():
        document = documents[source["source_id"]]
        diagrams: dict[int, CatalogDiagram] = {}
        for page in source.get("diagram_pages") or []:
            diagram = db.scalar(
                select(CatalogDiagram).where(
                    CatalogDiagram.source_id == source["source_id"],
                    CatalogDiagram.page_number == page,
                )
            )
            if diagram is None:
                diagram = CatalogDiagram(
                    source_id=source["source_id"],
                    family=source["family"],
                    assembly=source["assembly"],
                    technical_document_id=document.id,
                    page_number=page,
                    title=f"{source['document_title']} — схема, стр. {page}",
                    source_pdf_sha256=source["sha256"],
                    render_version="PDF_PREVIEW_V1",
                )
                db.add(diagram)
                counters["created_diagrams"] += 1
            else:
                diagram.family = source["family"]
                diagram.assembly = source["assembly"]
                diagram.technical_document_id = document.id
                diagram.title = f"{source['document_title']} — схема, стр. {page}"
                diagram.source_pdf_sha256 = source["sha256"]
            db.flush()
            diagrams[page] = diagram
        for data in load_source_dataset(source).get("hotspots") or []:
            hotspot = db.scalar(
                select(CatalogPositionHotspot).where(
                    CatalogPositionHotspot.hotspot_key == data["hotspot_key"]
                )
            )
            preserve_manual_correction = hotspot is not None and is_manually_confirmed(
                hotspot.provenance
            )
            if hotspot is None:
                hotspot = CatalogPositionHotspot(
                    hotspot_key=data["hotspot_key"],
                    diagram_id=diagrams[data["page"]].id,
                    position=data["position"],
                    x=data["x"],
                    y=data["y"],
                    width=data["width"],
                    height=data["height"],
                    provenance=data["provenance"],
                    confidence=data.get("confidence"),
                    created_by_id=verifier.id,
                )
                db.add(hotspot)
                counters["created_hotspots"] += 1
            else:
                hotspot.diagram_id = diagrams[data["page"]].id
                hotspot.position = data["position"]
                if preserve_manual_correction:
                    hotspot.provenance = MANUALLY_CONFIRMED
                    hotspot.confidence = 1.0
                else:
                    hotspot.x = data["x"]
                    hotspot.y = data["y"]
                    hotspot.width = data["width"]
                    hotspot.height = data["height"]
                    hotspot.provenance = data["provenance"]
                    hotspot.confidence = data.get("confidence")
            hotspot.is_verified = bool(data.get("is_verified"))
            if not preserve_manual_correction:
                hotspot.verified_by_id = verifier.id if hotspot.is_verified else None
                hotspot.verified_at = (
                    hotspot.verified_at or utcnow()
                ) if hotspot.is_verified else None


def _upsert_repair_kits(
    db: Session,
    verifier: User,
    parts: dict[str, PartCatalog],
    counters: dict[str, int],
) -> None:
    for kit in db.scalars(select(RepairKit).where(RepairKit.is_active.is_(True))):
        if kit.source_version != CATALOG_VERSION:
            kit.is_active = False
            kit.is_approved = False
            counters["archived_repair_kits"] += 1

    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for source in dataset_sources():
        for row in load_source_dataset(source).get("records") or []:
            if row.get("repair_kit_code"):
                grouped[row["repair_kit_code"]].append(row)

    for code, rows in sorted(grouped.items()):
        source_ids = {row["source_id"] for row in rows}
        families = {row["family"] for row in rows}
        assemblies = {row["assembly"] for row in rows}
        if len(source_ids) != 1 or len(families) != 1 or len(assemblies) != 1:
            raise CatalogImportError(f"Cross-source repair kit is not allowed: {code}")
        source = next(item for item in dataset_sources() if item["source_id"] in source_ids)
        kit = db.scalar(select(RepairKit).where(RepairKit.code == code))
        if kit is None:
            kit = RepairKit(
                code=code,
                name=f"Repair kit {code}",
                created_by_id=verifier.id,
            )
            db.add(kit)
            counters["created_repair_kits"] += 1
        else:
            counters["updated_repair_kits"] += 1
        family = load_manifest()["families"][rows[0]["family"]]
        kit.name = f"Repair kit {code}"
        kit.family = rows[0]["family"]
        kit.source_id = rows[0]["source_id"]
        kit.source_version = CATALOG_VERSION
        kit.source_document_sha256 = rows[0]["source_document_sha256"]
        kit.brand = family["brand"]
        kit.model = family["model"]
        kit.compatible_models = family["model"]
        kit.assembly = rows[0]["assembly"]
        kit.source_document = rows[0]["source_document"]
        kit.source_page = min(int(row["source_page"]) for row in rows)
        kit.provenance = "Изрична стойност в колоната Repair kit на authoritative PDF."
        kit.confidence = 1.0
        kit.is_active = True
        kit.is_approved = True
        kit.approved_by_id = verifier.id
        kit.approved_at = kit.approved_at or utcnow()
        db.flush()

        existing = {component.part_id: component for component in kit.components}
        expected_ids: set[int] = set()
        for row in rows:
            part = parts[row["source_record_key"]]
            expected_ids.add(part.id)
            component = existing.get(part.id)
            if component is None:
                component = RepairKitComponent(kit_id=kit.id, part_id=part.id)
                db.add(component)
            if row.get("quantity") is None:
                raise CatalogImportError(
                    f"Repair kit {code} has ambiguous quantity at {row['source_record_key']}"
                )
            component.quantity = float(row["quantity"])
            component.quantity_raw = row.get("quantity_raw")
            component.source_record_key = row["source_record_key"]
            component.source_document = row["source_document"]
            component.source_page = row["source_page"]
            component.is_optional = False
            component.note = None
        for part_id, component in existing.items():
            if part_id not in expected_ids:
                db.delete(component)
        counters["repair_kit_components"] += len(rows)


def import_authoritative_catalog(db: Session, verifier: User) -> dict[str, Any]:
    report = validate_catalog_v2()
    if not report["valid"]:
        raise CatalogImportError("; ".join(report["errors"]))

    counters: dict[str, int] = defaultdict(int)
    documents = _upsert_documents(db, verifier, counters)
    parts = _upsert_parts(db, verifier, counters)
    _upsert_diagrams_and_hotspots(db, verifier, documents, counters)
    _upsert_repair_kits(db, verifier, parts, counters)
    db.flush()

    changed = sum(
        count
        for key, count in counters.items()
        if key.startswith("created_") or key.startswith("archived_")
    )
    if changed:
        add_audit_log(
            db,
            verifier,
            "catalog_dataset",
            None,
            "Активиран authoritative каталог за резервни части",
            {
                "dataset_version": CATALOG_VERSION,
                "record_count": report["record_count"],
                "records_by_family": report["records_by_family"],
                "repair_kit_count": report["repair_kit_count"],
                "repair_kit_component_count": report["repair_kit_component_count"],
                "verified_hotspot_count": report["verified_hotspot_count"],
                **dict(counters),
            },
            CATALOG_VERSION,
        )
    return {"dataset_version": CATALOG_VERSION, **report, **dict(counters)}
