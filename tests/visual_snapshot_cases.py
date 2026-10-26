"""Entirely synthetic evidence; never imported by seeds or application code."""

import hashlib

import fitz
from app.models import (
    AssetCategory,
    CatalogDiagram,
    CatalogPositionHotspot,
    CatalogVisualPartMap,
    CatalogVisualSource,
    Machine,
    PartCatalog,
    PartHotspot,
    TechnicalDocument,
    TechnicalDocumentRevision,
    User,
    utcnow,
)
from sqlalchemy import select


def future_catalog(factory, *, visuals=True, source_content=None):
    if source_content is None:
        with fitz.open() as pdf:
            for number in range(2):
                pdf.new_page().insert_text((70, 90), f"Synthetic QA diagram {number + 1}")
            content = pdf.tobytes()
    else:
        content = source_content
    digest = hashlib.sha256(content).hexdigest()
    with factory() as db:
        actor = db.scalar(select(User).where(User.is_system_owner.is_(True)))
        category = AssetCategory(
            code="QA_FUTURE_COMPRESSOR",
            name_bg="Тестов компресор", name_en="QA compressor", name_ru="Тестовый компрессор",
            capabilities=["HAS_PARTS_CATALOG"],
        )
        db.add(category)
        db.flush()
        machine = Machine(
            inventory_number="QA-FUTURE-9001",
            name="Synthetic QA compressor",
            category=category.code,
            category_id=category.id,
            brand="FUTURE-SYNTHETIC",
            model="X9000",
            pressure_bar=0,
        )
        db.add(machine)
        part = PartCatalog(
            source_record_key="QA-FUTURE-SOURCE:row17",
            source_id="QA-FUTURE-SOURCE",
            source_row_index=17,
            source_version="QA-REV-42",
            revision="QA-42",
            source_document_sha256=digest,
            family="QA-COMPRESSOR-FAMILY",
            brand=machine.brand,
            model=machine.model,
            assembly="QA future assembly",
            position="QA-P7",
            part_number="QA-991122",
            description="Synthetic QA rotor",
            original_name="QA source rotor",
            manufacturer="QA synthetic manufacturer",
            unit="pcs",
            source_document="qa-source.pdf",
            source_page=2,
            source_figure="QA-FIG-7",
            diagram_page=1,
            is_verified=True,
            verification_status="VERIFIED_QA",
            verified_by_id=actor.id,
            verified_at=utcnow(),
            compatible_machine_numbers=[machine.inventory_number],
        )
        document = TechnicalDocument(
            brand=machine.brand,
            model=machine.model,
            category="QA",
            title="Synthetic QA source",
            file_path="qa/future-source.pdf",
            source_id=part.source_id,
            dataset_version=part.source_version,
            revision="QA-42",
            sha256=digest,
            uploaded_content=content,
            uploaded_filename="qa-source.pdf",
            media_type="application/pdf",
            page_count=2,
        )
        db.add_all([part, document])
        db.flush()
        revision = TechnicalDocumentRevision(
            document_id=document.id,
            version=42,
            revision_label="QA-42",
            filename="qa-source.pdf",
            media_type="application/pdf",
            content=content,
            sha256=digest,
        )
        db.add(revision)
        diagrams = []
        if visuals:
            for page in (1, 2):
                diagram = CatalogDiagram(
                    source_id=part.source_id,
                    family=part.family,
                    assembly=part.assembly,
                    technical_document_id=document.id,
                    page_number=page,
                    title=f"QA diagram {page}",
                    source_pdf_sha256=digest,
                )
                db.add(diagram)
                db.flush()
                diagrams.append(diagram.id)
            # Deliberately insert opposite to canonical page order.
            for index, diagram_id in enumerate((diagrams[1], diagrams[0], diagrams[0])):
                db.add(
                    CatalogPositionHotspot(
                        hotspot_key=f"QA-future-occurrence-{index}",
                        diagram_id=diagram_id,
                        position=part.position,
                        x=0.1 + index * 0.1,
                        y=0.2,
                        width=0.03,
                        height=0.04,
                        is_verified=True,
                        provenance="QA explicit verification",
                        confidence=0.99,
                        verified_by_id=actor.id,
                        verified_at=utcnow(),
                    )
                )
            db.add(
                PartHotspot(
                    part_id=part.id,
                    technical_document_id=document.id,
                    page_number=2,
                    x=0.6,
                    y=0.6,
                    width=0.03,
                    height=0.04,
                    label="QA direct",
                    provenance="QA direct verification",
                    is_verified=True,
                    created_by_id=actor.id,
                )
            )
        db.commit()
        return {
            "part_id": part.id,
            "machine_id": machine.id,
            "document_id": document.id,
            "revision_id": revision.id,
            "sha256": digest,
            "content": content,
            "diagram_ids": diagrams,
            "actor_id": actor.id,
        }


def request_payload(data):
    return {
        "machine_id": data["machine_id"],
        "submit_for_approval": True,
        "lines": [
            {
                "catalog_part_id": data["part_id"],
                "quantity": 3,
                "description": "STALE CLIENT DESCRIPTION",
                "position": "FALSE",
                "part_number": "FALSE",
                "unit": "FALSE",
                "source_document": "FALSE.pdf",
                "source_page": 999,
                "source_hash": "FALSE",
                "x": 0.99,
                "visual_snapshot": {"sha256": "FALSE"},
            }
        ],
    }


def declared_catalog(factory):
    """Synthetic, explicitly classified scheme/list pages; no inferred roles."""
    with fitz.open() as pdf:
        scheme = pdf.new_page()
        scheme.insert_text((50, 55), "SYNTHETIC QA ONLY - EXPLODED SCHEME", fontsize=14)
        scheme.insert_text((50, 80), "Not a real industrial catalog or business record")
        for x, label in ((70, "QA-A"), (180, "QA-P7"), (300, "QA-B")):
            scheme.draw_rect(fitz.Rect(x, 270, x + 90, 340))
            scheme.insert_text((x + 10, 305), label)
        scheme.draw_line((160, 305), (180, 305))
        scheme.draw_line((270, 305), (300, 305))
        listing = pdf.new_page()
        listing.insert_text((50, 55), "SYNTHETIC QA ONLY - SPARE PARTS LIST", fontsize=14)
        listing.insert_text((50, 80), "Not a real industrial catalog or business record")
        columns = (50, 130, 240, 450, 545)
        for y, values in ((145, ("Position", "Part No.", "Description", "Unit")),
                          (180, ("QA-P7", "QA-991122", "Synthetic QA rotor", "pcs"))):
            for x, right, value in zip(columns[:-1], columns[1:], values, strict=True):
                listing.draw_rect(fitz.Rect(x, y - 20, right, y + 15))
                listing.insert_text((x + 5, y), value, fontsize=9)
        content = pdf.tobytes()
    data = future_catalog(factory, visuals=False, source_content=content)
    with factory() as db:
        part = db.get(PartCatalog, data["part_id"])
        for page, role in ((1, "EXPLODED_SCHEME"), (2, "SPARE_PARTS_LIST")):
            source = CatalogVisualSource(source_id=part.source_id, catalog_revision=part.source_version,
                technical_document_id=data["document_id"], page_number=page, role=role,
                source_sha256=data["sha256"])
            db.add(source)
            db.flush()
            if role == "SPARE_PARTS_LIST":
                db.add(CatalogVisualPartMap(visual_source_id=source.id, part_id=part.id))
        diagram = CatalogDiagram(source_id=part.source_id, family=part.family, assembly=part.assembly,
            technical_document_id=data["document_id"], page_number=1,
            title="SYNTHETIC QA declared scheme", source_pdf_sha256=data["sha256"])
        db.add(diagram)
        db.flush()
        db.add(CatalogPositionHotspot(hotspot_key="QA-declared-catalog-position", diagram_id=diagram.id,
            position=part.position, x=.3, y=.35, width=.08, height=.03, is_verified=True,
            provenance="SYNTHETIC QA explicit role and position confirmation", confidence=.99,
            verified_by_id=data["actor_id"], verified_at=utcnow()))
        db.commit()
    return data
