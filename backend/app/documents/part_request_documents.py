"""Canonical parts-request snapshots and protocol construction."""

from __future__ import annotations

import io
from pathlib import Path
from xml.sax.saxutils import escape

from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Mm, Pt
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.platypus import (
    Image as PdfImage,
)
from reportlab.platypus import (
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
)
from sqlalchemy.orm import Session

from ..models import (
    DocumentType,
    GeneratedDocument,
    PartRequest,
    PartRequestLine,
)
from ..part_requests.visual_snapshots import snapshot_document_reference
from ..template_engine import convert_docx_to_pdf, render_docx
from .common import (
    PARTS_REFERENCE,
    TEXT,
    _language,
)
from .part_request_grouped_visuals import (
    append_docx,
    appendix_manifest,
    pdf_flowables,
    prepare_appendix,
)
from .part_request_visual_appendix import VisualPlan
from .registration import (
    _generated_documents,
    _register_official_version,
)
from .rendering import (
    _add_centered,
    _pdf_styles,
    _pdf_table_style,
    _prepare_document,
    _set_cell,
    _set_repeat_table_header,
    _set_run_font,
)
from .templates import (
    _preparer_values,
    _signature_status,
    _template_version,
)

REQUEST_HEADERS = {
    "bg": ["Поз.", "PART №", "Описание", "Количество"],
    "en": ["Pos.", "PART No.", "Description", "Quantity"],
    "ru": ["Поз.", "PART №", "Описание", "Количество"],
}

REQUEST_META_LABELS = {
    "bg": ("Машина", "Инвентарен №", "Марка", "Модел", "Сериен №", "Налягане", "Партида", "Документ №", "Дата", "Съставил", "Длъжност", "Заявител", "Приел", "Подпис", "Статус на подписите"),
    "en": ("Machine", "Inventory No.", "Brand", "Model", "Serial No.", "Pressure", "Batch", "Document No.", "Date", "Prepared by", "Job title", "Requester", "Accepted by", "Signature", "Signature status"),
    "ru": ("Машина", "Инвентарный №", "Марка", "Модель", "Серийный №", "Давление", "Партия", "Документ №", "Дата", "Составил", "Должность", "Заявитель", "Принял", "Подпись", "Статус подписей"),
}

OFFICIAL_HEADER = Path(__file__).resolve().parents[2] / "resources" / "assets" / "odessos_part_request_header.png"


def _request_snapshot(request: PartRequest, appendix: VisualPlan | None = None) -> dict:
    result = {
        "request_id": request.id,
        "request_reference": request.request_reference,
        "machine_id": request.machine_id,
        "machine_number": request.machine.inventory_number if request.machine else None,
        "repair_id": request.repair_id,
        "repair_reference": request.repair.repair_reference if request.repair else None,
        "priority": request.priority,
        "status": request.status,
        "language": request.language,
        "reason": request.reason,
        "department": request.department,
        "supplier": request.supplier,
        "delivery_note": request.delivery_note,
        "ordered_at": request.ordered_at.isoformat() if request.ordered_at else None,
        "delivered_at": request.delivered_at.isoformat() if request.delivered_at else None,
        "requested_by_id": request.requested_by_id,
        "submitted_at": request.submitted_at.isoformat() if request.submitted_at else None,
        "decided_at": request.decided_at.isoformat() if request.decided_at else None,
        "decision_note": request.decision_note,
        "lines": [
            {
                "catalog_part_id": line.catalog_part_id,
                "position": line.position,
                "part_number": line.part_number,
                "description": line.description,
                "quantity": line.quantity,
                "unit": line.unit,
                "source_document": line.source_document,
                "source_page": line.source_page,
                "delivered_quantity": line.delivered_quantity,
                "is_unknown_part": line.is_unknown_part,
                "assembly": line.assembly,
                "note": line.note,
                "linked_catalog_part_id": line.linked_catalog_part_id,
                "linked_part_number": line.linked_catalog_part.part_number if line.linked_catalog_part else None,
                "linked_at": line.linked_at.isoformat() if line.linked_at else None,
                **({"visual_snapshot": snapshot_document_reference(line)}
                   if line.visual_snapshot is not None else {}),
            }
            for line in request.lines
        ],
    }
    if appendix is not None:
        result["visual_appendix"] = appendix_manifest(appendix)
    return result


def _part_request_line_description(line: PartRequestLine, language: str) -> str:
    if not line.is_unknown_part:
        return line.description
    label = {
        "bg": "Част без потвърден part number",
        "en": "Part without a confirmed part number",
        "ru": "Деталь без подтверждённого part number",
    }[_language(language)]
    assembly = {"bg": "Възел", "en": "Assembly", "ru": "Узел"}[_language(language)]
    linked = ""
    if line.linked_catalog_part:
        linked_label = {"bg": "Свързана с", "en": "Linked to", "ru": "Связана с"}[_language(language)]
        linked = f"; {linked_label}: {line.linked_catalog_part.part_number}"
    return f"[{label}] {assembly}: {line.assembly or '-'}; {line.description}{linked}"


def build_part_request_docx(request: PartRequest, language: str = "bg") -> bytes:
    language = _language(language)
    t = TEXT[language]
    document = _prepare_document(PARTS_REFERENCE)
    for line in t["part_request_title"].splitlines():
        _add_centered(document, line, 10.5, True)
    if request.machine:
        machine = request.machine
        for label_text, value in ((t["machine"], f"{machine.name}; {machine.brand} {machine.model or ''}".strip()), (t["inventory"], machine.inventory_number), (t["serial"], machine.serial_number or "")):
            paragraph = document.add_paragraph()
            paragraph.paragraph_format.space_after = Pt(0)
            _set_run_font(paragraph.add_run(f"{label_text}: "), 8.5, True)
            _set_run_font(paragraph.add_run(value), 8.5)
    document.add_paragraph()
    table = document.add_table(rows=1, cols=4)
    table.style = "Table Grid"
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    headers = (t["position"], t["part_number"], t["description"], t["quantity"])
    widths = (Mm(14), Mm(31), Mm(127), Mm(20))
    for index, value in enumerate(headers):
        table.rows[0].cells[index].width = widths[index]
        _set_cell(table.rows[0].cells[index], value, bold=True, size=8)
        table.rows[0].cells[index].paragraphs[0].alignment = WD_ALIGN_PARAGRAPH.CENTER
    _set_repeat_table_header(table.rows[0])
    for line in request.lines:
        cells = table.add_row().cells
        values = (line.position or "", line.part_number or "", _part_request_line_description(line, language), f"{line.quantity:g} {line.unit or ''}".strip())
        for index, value in enumerate(values):
            cells[index].width = widths[index]
            _set_cell(cells[index], value, size=8)
    if request.reason:
        paragraph = document.add_paragraph()
        _set_run_font(paragraph.add_run(f'{t["remarks"]}: '), 8.5, True)
        _set_run_font(paragraph.add_run(request.reason), 8.5)
    footer = document.add_table(rows=1, cols=3)
    footer.style = "Table Grid"
    request_ref = request.request_reference or f"PR-{request.id:06d}"
    requester = request.requested_by.full_name if request.requested_by else ""
    decision = request.decision_note or request.status
    for cell, value in zip(footer.rows[0].cells, (f'{t["request_number"]}: {request_ref}', f'{t["date"]}: {request.created_at:%d.%m.%Y}', f'{t["requester"]}: {requester}\n{t["decision"]}: {decision}'), strict=True):
        _set_cell(cell, value, size=8)
    output = io.BytesIO()
    document.save(output)
    return output.getvalue()


def build_part_request_pdf(
    request: PartRequest, language: str = "bg", *, appendix: VisualPlan | None = None
) -> bytes:
    language = _language(language)
    t = TEXT[language]
    (
        machine_label, inventory_label, brand_label, model_label, serial_label,
        pressure_label, batch_label, document_label, date_label, _prepared_label,
        _job_label, requester_label, accepted_label, _signature_label, status_label,
    ) = REQUEST_META_LABELS[language]
    _, _, body, label, title, small = _pdf_styles()
    output = io.BytesIO()
    request_ref = request.request_reference or f"PR-{request.id:06d}"
    pdf = SimpleDocTemplate(
        output, pagesize=A4, leftMargin=11 * mm, rightMargin=11 * mm,
        topMargin=8 * mm, bottomMargin=9 * mm, title=request_ref, author="AssetCore",
    )
    story = [PdfImage(str(OFFICIAL_HEADER), width=188 * mm, height=27 * mm), Spacer(1, 4 * mm)]
    title.fontSize = 13
    title.leading = 15
    story.append(Paragraph(escape(t["part_request_title"].replace("\n", " ")), title))
    story.append(Spacer(1, 4 * mm))
    metadata = Table([[
        Paragraph(f"{escape(document_label)}: {escape(request_ref)}", body),
        Paragraph(f"{escape(date_label)}: {request.created_at:%d.%m.%Y}", body),
    ]], colWidths=[94 * mm, 94 * mm])
    metadata.setStyle(_pdf_table_style())
    story.extend([metadata, Spacer(1, 2 * mm)])
    if request.machine:
        machine = request.machine
        machine_rows = [
            (machine_label, machine.name, inventory_label, machine.inventory_number),
            (brand_label, machine.brand, model_label, machine.model or ""),
            (serial_label, machine.serial_number or "", pressure_label,
             f"{machine.pressure_bar:g} bar" if machine.pressure_bar is not None else ""),
            (batch_label, "", "", ""),
        ]
        machine_table = Table([
            [Paragraph(escape(str(value)), body) for value in row]
            for row in machine_rows
        ], colWidths=[47 * mm] * 4)
        machine_table.setStyle(_pdf_table_style())
        story.extend([machine_table, Spacer(1, 3 * mm)])
    data = [[Paragraph(escape(value), label) for value in REQUEST_HEADERS[language]]]
    data.extend([[Paragraph(escape(line.position or ""), small), Paragraph(escape(line.part_number or ""), small), Paragraph(escape(_part_request_line_description(line, language)), small), Paragraph(escape(f"{line.quantity:g} {line.unit or ''}".strip()), small)] for line in request.lines])
    table = Table(data, colWidths=[25 * mm, 44 * mm, 68 * mm, 51 * mm], repeatRows=1)
    table.setStyle(_pdf_table_style(header_rows=1))
    story.append(table)
    if request.reason:
        story.extend([Spacer(1, 2 * mm), Paragraph(f'<b>{escape(t["remarks"])}:</b> {escape(request.reason)}', body)])
    story.extend([
        Paragraph(f"{escape(t['decision'])}: {escape(request.decision_note or request.status)}", small),
        Paragraph(f"{escape(requester_label)}: {escape(request.requested_by.full_name if request.requested_by else '')}", small),
        Paragraph(f"{escape(accepted_label)}: {escape(request.decided_by.full_name if request.decided_by else '')}", small),
        Paragraph(f"{escape(status_label)}: {escape(_signature_status(language))}", small),
    ])
    if appendix is not None:
        story.extend(pdf_flowables(appendix, language))
    pdf.build(story)
    return output.getvalue()


def make_part_request_documents(
    db: Session, request: PartRequest, created_by_id: int, language: str = "bg"
) -> list[GeneratedDocument]:
    template = _template_version(db, DocumentType.PART_REQUEST.value, language)
    number = request.request_reference or f"PR-{request.id:06d}"
    machine = request.machine
    values: dict[str, object] = {
        "DOCUMENT_NUMBER": number,
        "CREATION_DATE": request.created_at.strftime("%d.%m.%Y"),
        "MACHINE_NAME": machine.name if machine else "",
        "MACHINE_NUMBER": machine.inventory_number if machine else "",
        "BRAND": machine.brand if machine else "",
        "MODEL": machine.model or "" if machine else "",
        "SERIAL_NUMBER": machine.serial_number or "" if machine else "",
        "PRESSURE_BAR": machine.pressure_bar if machine and machine.pressure_bar is not None else "",
        "BATCH_REFERENCE": "",
        "REMARKS": request.reason or "",
        "DECISION": request.decision_note or request.status,
        "LEFT_SIGNER_NAME": request.requested_by.full_name if request.requested_by else "",
        "LEFT_SIGNER_JOB_TITLE": request.requested_by.job_title if request.requested_by else "",
        "RIGHT_SIGNER_NAME": request.decided_by.full_name if request.decided_by else "",
        "RIGHT_SIGNER_JOB_TITLE": request.decided_by.job_title if request.decided_by else "",
        "LEFT_SIGNATURE": "",
        "RIGHT_SIGNATURE": "",
        "SIGNATURE_STATUS": _signature_status(language),
    }
    values.update(_preparer_values(db, created_by_id))
    line_rows = [REQUEST_HEADERS[_language(language)]] + [
        [line.position or "", line.part_number or "", _part_request_line_description(line, language), f"{line.quantity:g} {line.unit or ''}".strip()]
        for line in request.lines
    ]
    appendix = prepare_appendix(db, request)
    docx = append_docx(
        render_docx(template, values, {"REQUEST_LINES": line_rows}), appendix, language
    )
    pdf = convert_docx_to_pdf(docx) or build_part_request_pdf(
        request, language, appendix=appendix
    )
    snapshot = _request_snapshot(request, appendix)
    _register_official_version(
        db,
        number=number,
        document_type=DocumentType.PART_REQUEST.value,
        language=language,
        docx=docx,
        pdf=pdf,
        snapshot=snapshot,
        created_by_id=created_by_id,
        machine_id=request.machine_id,
        template_version_id=template.id,
    )
    return _generated_documents(
        number=number,
        document_type=DocumentType.PART_REQUEST.value,
        language=language,
        template_version=template,
        docx=docx,
        pdf=pdf,
        snapshot=snapshot,
        created_by_id=created_by_id,
        machine_id=request.machine_id,
        part_request_id=request.id,
    )
