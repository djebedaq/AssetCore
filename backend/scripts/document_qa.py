"""Generate isolated document samples and structural QA evidence.

The script uses a temporary in-memory SQLite database. It never writes sample
records to the configured AssetCore database and never changes source templates.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import zipfile
from pathlib import Path

from docx import Document
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.database import Base  # noqa: E402
from app.document_generation import (  # noqa: E402
    PARTS_REFERENCE,
    REPAIR_REFERENCE,
    build_part_request_docx,
    build_part_request_pdf,
    build_protocol_docx,
    build_protocol_pdf,
    build_repair_protocol_docx,
    build_repair_protocol_pdf,
    build_return_protocol_docx,
    build_return_protocol_pdf,
)
from app.models import (  # noqa: E402
    Machine,
    PartCatalog,
    PartRequest,
    PartRequestLine,
    PartRequestPriority,
    PartRequestStatus,
    Repair,
    RepairEvent,
    RepairEventType,
    RepairStatus,
    TransferBatch,
    TransferBatchStatus,
    TransferProtocol,
    User,
    utcnow,
)
from app.seed import seed_database  # noqa: E402


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _docx_audit(path: Path) -> dict:
    document = Document(path)
    with zipfile.ZipFile(path) as archive:
        names = set(archive.namelist())
        preserved = {}
        for name in ("word/header1.xml", "word/styles.xml", "word/numbering.xml", "word/settings.xml"):
            if name in names:
                preserved[name] = hashlib.sha256(archive.read(name)).hexdigest()
        media = {
            name: hashlib.sha256(archive.read(name)).hexdigest()
            for name in sorted(names)
            if name.startswith("word/media/")
        }
    section = document.sections[0]
    return {
        "sha256": _sha(path),
        "sections": len(document.sections),
        "tables": len(document.tables),
        "paragraphs": len(document.paragraphs),
        "page_width_twips": section.page_width.twips,
        "page_height_twips": section.page_height.twips,
        "margins_twips": {
            "left": section.left_margin.twips,
            "right": section.right_margin.twips,
            "top": section.top_margin.twips,
            "bottom": section.bottom_margin.twips,
        },
        "package_parts": len(names),
        "preserved_parts": preserved,
        "media": media,
    }


def _pdf_audit(path: Path) -> dict:
    content = path.read_bytes()
    page_count = len(re.findall(rb"/Type\s*/Page\b", content))
    media_boxes = [
        [float(value) for value in match]
        for match in re.findall(
            rb"/MediaBox\s*\[\s*([0-9.]+)\s+([0-9.]+)\s+([0-9.]+)\s+([0-9.]+)\s*\]",
            content,
        )
    ]
    return {
        "sha256": _sha(path),
        "pages": page_count,
        "media_boxes": media_boxes,
    }


def _write_pair(output: Path, stem: str, docx_bytes: bytes, pdf_bytes: bytes) -> dict:
    docx_path = output / f"{stem}.docx"
    pdf_path = output / f"{stem}.pdf"
    docx_path.write_bytes(docx_bytes)
    pdf_path.write_bytes(pdf_bytes)
    return {"docx": _docx_audit(docx_path), "pdf": _pdf_audit(pdf_path)}


def generate(output: Path) -> dict:
    output.mkdir(parents=True, exist_ok=True)
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        seed_database(db)
        machine = db.scalar(select(Machine).where(Machine.inventory_number == "4"))
        user = db.scalar(select(User).order_by(User.id))
        part = db.scalar(
            select(PartCatalog)
            .where(PartCatalog.is_verified.is_(True))
            .order_by(PartCatalog.id)
        )
        if machine is None or user is None or part is None:
            raise RuntimeError("Verified seed prerequisites are missing.")

        now = utcnow()
        batch = TransferBatch(
            batch_reference="QA-ONLY-BATCH",
            status=TransferBatchStatus.ACTIVE.value,
            created_by_id=user.id,
        )
        db.add(batch)
        db.flush()
        transfer = TransferProtocol(
            machine_id=machine.id,
            batch_id=batch.id,
            protocol_type="Предаване",
            protocol_number="QA-ONLY-PROTOCOL",
            is_active=True,
            issued_by_id=user.id,
            issued_at=now,
            previous_status=machine.status,
            previous_location_id=machine.location_id,
            issue_location_id=machine.location_id,
        )
        db.add(transfer)
        db.flush()

        repair = Repair(
            machine_id=machine.id,
            repair_reference="QA-ONLY-REPAIR",
            reported_problem="QA тестов запис за проверка на оформлението",
            diagnosis="QA тестова диагностика",
            work_performed="QA тестово описание на извършена работа",
            result="QA тестов резултат",
            condition_before="QA тестово състояние преди ремонта",
            condition_after="QA тестово състояние след ремонта",
            inspection_completed_at=now,
            test_passed=True,
            test_details="QA тестът е отчетен като успешен само в изолираната проверка",
            status=RepairStatus.COMPLETED.value,
            responsible_user_id=user.id,
            accepted_by_id=user.id,
            approved_by_id=user.id,
            approved_at=now,
            closed_at=now,
        )
        db.add(repair)
        db.flush()
        db.add(
            RepairEvent(
                repair_id=repair.id,
                event_type=RepairEventType.TEST.value,
                status_before=RepairStatus.TESTING.value,
                status_after=RepairStatus.COMPLETED.value,
                description="QA тестово хронологично събитие",
                user_id=user.id,
            )
        )

        request = PartRequest(
            machine_id=machine.id,
            request_reference="QA-ONLY-PART-REQUEST",
            part_name=part.description,
            part_number=part.part_number,
            quantity=1,
            reason="QA проверка на оформлението",
            priority=PartRequestPriority.NORMAL.value,
            status=PartRequestStatus.APPROVED.value,
            language="bg",
            requested_by_id=user.id,
            submitted_at=now,
            decided_at=now,
            decided_by_id=user.id,
            decision_note="QA тестово одобрение",
        )
        db.add(request)
        db.flush()
        db.add(
            PartRequestLine(
                request_id=request.id,
                catalog_part_id=part.id,
                position=part.position,
                part_number=part.part_number,
                description=part.description,
                quantity=1,
                unit=part.unit,
                source_document=part.source_document,
                source_page=part.source_page,
            )
        )
        db.flush()
        db.refresh(transfer)
        db.refresh(repair)
        db.refresh(request)

        results = {
            "issue": _write_pair(
                output,
                "issue-protocol-bg",
                build_protocol_docx(transfer, batch.batch_reference, "bg"),
                build_protocol_pdf(transfer, batch.batch_reference, "bg"),
            ),
            "return": _write_pair(
                output,
                "return-protocol-bg",
                build_return_protocol_docx(transfer, batch.batch_reference, "bg"),
                build_return_protocol_pdf(transfer, batch.batch_reference, "bg"),
            ),
            "repair": _write_pair(
                output,
                "repair-protocol-bg",
                build_repair_protocol_docx(repair, "bg"),
                build_repair_protocol_pdf(repair, "bg"),
            ),
            "part_request": _write_pair(
                output,
                "part-request-bg",
                build_part_request_docx(request, "bg"),
                build_part_request_pdf(request, "bg"),
            ),
        }

    source_hashes_after = {
        "repair_reference": _sha(REPAIR_REFERENCE),
        "parts_reference": _sha(PARTS_REFERENCE),
    }
    source_structures = {
        "repair_reference": _docx_audit(REPAIR_REFERENCE),
        "parts_reference": _docx_audit(PARTS_REFERENCE),
    }
    results["source_hashes_after"] = source_hashes_after
    results["source_structures"] = source_structures
    results["source_preservation"] = {
        "repair_unchanged": source_hashes_after["repair_reference"]
        == "39337dfc445d61b4d5144259ca35624c2049d266378e326780176de3104784c1",
        "parts_unchanged": source_hashes_after["parts_reference"]
        == "3ba8e43102ae044b02b6aa7a4cd3b06ff00bce444a56fc8da6ba737c42bbc7a7",
        "repair_header_media_preserved": set(results["repair"]["docx"]["media"].values())
        == set(source_structures["repair_reference"]["media"].values()),
        "parts_header_media_preserved": set(
            results["part_request"]["docx"]["media"].values()
        )
        == set(source_structures["parts_reference"]["media"].values()),
    }
    (output / "qa-manifest.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    engine.dispose()
    return results


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    result = generate(args.output.resolve())
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
