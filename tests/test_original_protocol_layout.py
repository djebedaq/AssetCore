from __future__ import annotations

import hashlib
import io
import zipfile
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image, ImageDraw
from pypdf import PdfReader

from app.signature_rendering import (
    LEFT_SIGNATURE_MARKER,
    RIGHT_SIGNATURE_MARKER,
    finalize_signed_files_from_rows,
)
from app.template_engine import convert_docx_to_pdf, render_docx, validate_template

ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = ROOT / "backend" / "resources" / "templates"


def _version(operation: str, language: str = "bg"):
    path = TEMPLATES / f"transfer_{operation}-{language}-v3.docx"
    return SimpleNamespace(
        source_content=None,
        source_path=f"templates/{path.name}",
        source_filename=path.name,
        source_media_type=(
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        ),
        source_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
        language=language,
        required_fields=["MACHINE_NUMBER", "SERIAL_NUMBER", "CONDITION_TEXT"],
        layout_contract={"page": "A4 portrait", "reference_only": False},
        template=SimpleNamespace(
            document_type=(
                "TRANSFER_RETURN" if operation == "return" else "TRANSFER_ISSUE"
            )
        ),
    )


def _values(operation: str) -> dict[str, object]:
    values: dict[str, object] = {
        "DOCUMENT_NUMBER": "AC-2026-0001-R" if operation == "return" else "AC-2026-0001",
        "CREATION_DATE": "05.08.2026",
        "EQUIPMENT_TYPE": "HPWJ",
        "MODEL_DISPLAY": "HYDWIN - 500bar; FCE 15/50",
        "MACHINE_NUMBER": "21",
        "SERIAL_NUMBER": "Ser.#: 2512004; Pump: FS20251202001; Fussen FCH 1550",
        "CONDITION_LABEL": "Общо състояние",
        "CONDITION_TEXT": "Добро",
        "USAGE_TEXT": "Миене в сух док - ремонт на кораб",
        "REMARKS": "Комплектна и подготвена за работа.",
        "LEFT_SIGNER_NAME": (
            "Иван Петров Иванов" if operation == "return" else "Евтим Станиславов Горанов"
        ),
        "LEFT_SIGNER_ROLE": (
            "Върнал оборудването"
            if operation == "return"
            else "Предал оборудването от страна на ДИРП · Механик"
        ),
        "RIGHT_SIGNER_NAME": (
            "Евтим Станиславов Горанов" if operation == "return" else "Иван Петров Иванов"
        ),
        "RIGHT_SIGNER_ROLE": (
            "Приел оборудването · Механик"
            if operation == "return"
            else "Приел оборудването"
        ),
        "LEFT_SIGNATURE": LEFT_SIGNATURE_MARKER,
        "RIGHT_SIGNATURE": RIGHT_SIGNATURE_MARKER,
        "SIGNATURE_STATUS": "НЕПЪЛНО ПОДПИСАН",
        "PREPARER_NAME": "Евтим Станиславов Горанов",
        "PREPARER_JOB_TITLE": "Механик",
        "BATCH_REFERENCE": "BATCH-20260805-001",
    }
    checklist = [
        "Добро",
        "Добро · 25 m",
        "Добро · 40 m",
        "Добро",
        "Не се прилага",
        "Добро",
        "Добро · 30 m",
        "Добро",
        "Добро",
        "Добро",
    ]
    for index, value in enumerate(checklist, start=1):
        values[f"CHECK_{index}"] = value
    return values


def _signature_png(reverse: bool = False) -> bytes:
    image = Image.new("RGBA", (500, 180), (255, 255, 255, 0))
    draw = ImageDraw.Draw(image)
    points = [(20, 130), (100, 20), (180, 150), (270, 30), (470, 120)]
    if reverse:
        points = [(x, 180 - y) for x, y in points]
    draw.line(points, fill=(0, 0, 0, 255), width=8)
    output = io.BytesIO()
    image.save(output, "PNG")
    return output.getvalue()


@pytest.mark.parametrize("operation", ["issue", "return"])
@pytest.mark.parametrize("language", ["bg", "en", "ru"])
def test_transfer_v3_templates_validate(operation: str, language: str):
    report = validate_template(_version(operation, language))
    assert report["valid"] is True, report
    assert "LEFT_SIGNATURE" in report["tokens"]
    assert "RIGHT_SIGNATURE" in report["tokens"]


@pytest.mark.parametrize(
    ("operation", "left_slot", "right_slot"),
    [
        ("issue", "HANDOVER", "ACCEPTANCE"),
        ("return", "RETURNED_BY", "ACCEPTED_RETURN"),
    ],
)
def test_transfer_signatures_stay_on_original_a4_page(
    operation: str,
    left_slot: str,
    right_slot: str,
):
    draft_docx = render_docx(_version(operation), _values(operation))
    draft_pdf = convert_docx_to_pdf(draft_docx)
    if draft_pdf is None:
        pytest.skip("LibreOffice is not available for document QA")

    participant_left = SimpleNamespace(
        slot_code=left_slot,
        identity_snapshot={"display_name": "Left"},
        operation_role="Left",
    )
    participant_right = SimpleNamespace(
        slot_code=right_slot,
        identity_snapshot={"display_name": "Right"},
        operation_role="Right",
    )
    signature_left = SimpleNamespace(
        signature_sha256="a" * 64,
        confirmed_at=datetime(2026, 8, 5, 10, 0),
    )
    signature_right = SimpleNamespace(
        signature_sha256="b" * 64,
        confirmed_at=datetime(2026, 8, 5, 10, 1),
    )
    official = SimpleNamespace(
        docx_content=draft_docx,
        pdf_content=draft_pdf,
        language="bg",
        docx_sha256=None,
        pdf_sha256=None,
    )

    finalize_signed_files_from_rows(
        official,
        [
            (participant_left, signature_left, _signature_png()),
            (participant_right, signature_right, _signature_png(reverse=True)),
        ],
    )

    assert len(PdfReader(io.BytesIO(official.pdf_content)).pages) == 1
    assert "Потвърдени подписи" not in official.docx_content.decode(
        "latin-1", errors="ignore"
    )
    with zipfile.ZipFile(io.BytesIO(official.docx_content)) as archive:
        document_xml = archive.read("word/document.xml").decode("utf-8")
        media = [name for name in archive.namelist() if name.startswith("word/media/")]
    assert LEFT_SIGNATURE_MARKER not in document_xml
    assert RIGHT_SIGNATURE_MARKER not in document_xml
    assert "Потвърдени подписи" not in document_xml
    assert len(media) >= 5  # three header images and two graphic signatures
