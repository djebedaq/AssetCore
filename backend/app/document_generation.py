from __future__ import annotations

import hashlib
import io
import re
from datetime import datetime
from pathlib import Path
from xml.sax.saxutils import escape

from docx import Document
from docx.enum.table import WD_CELL_VERTICAL_ALIGNMENT, WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from docx.shared import Mm, Pt
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from .models import ProtocolDocument, TransferBatch, TransferProtocol

DOCX_MEDIA_TYPE = (
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
)
PDF_MEDIA_TYPE = "application/pdf"


def safe_filename(value: str) -> str:
    """Return a stable ASCII filename stem without path components."""
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", value.strip())
    return cleaned.strip(".-") or "assetcore-protocol"


def _set_run_font(run, size: float = 10, bold: bool = False) -> None:
    run.font.name = "Arial"
    run._element.rPr.rFonts.set(qn("w:eastAsia"), "Arial")
    run.font.size = Pt(size)
    run.bold = bold


def _protocol_rows(transfer: TransferProtocol, batch_reference: str) -> list[tuple[str, str]]:
    machine = transfer.machine
    return [
        ("Дата на издаване", (transfer.issued_at or transfer.created_at).strftime("%d.%m.%Y %H:%M")),
        ("Партида", batch_reference),
        ("Машина", f"{machine.name} - {machine.brand} {machine.model or ''}".strip()),
        ("Инвентарен №", machine.inventory_number),
        ("Сериен №", machine.serial_number or "-"),
        ("Налягане", f"{machine.pressure_bar} bar"),
        ("Фирма / звено", transfer.company_unit or "-"),
        ("Кораб", transfer.vessel or "-"),
        ("Местоположение", transfer.location_text or "-"),
        ("Комплектовка", transfer.equipment or "-"),
        ("Състояние", transfer.condition_text or "-"),
        ("Забележки", transfer.remarks or "-"),
    ]


def build_protocol_docx(transfer: TransferProtocol, batch_reference: str) -> bytes:
    document = Document()
    section = document.sections[0]
    section.page_width = Mm(210)
    section.page_height = Mm(297)
    section.top_margin = Mm(16)
    section.bottom_margin = Mm(16)
    section.left_margin = Mm(18)
    section.right_margin = Mm(18)

    normal = document.styles["Normal"]
    normal.font.name = "Arial"
    normal._element.rPr.rFonts.set(qn("w:eastAsia"), "Arial")
    normal.font.size = Pt(10)

    heading = document.add_paragraph()
    heading.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = heading.add_run("ОДЕСОС ШИПРИПЕЪР ЯРД АД")
    _set_run_font(run, 14, True)

    title = document.add_paragraph()
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = title.add_run(
        f"ПРИЕМО-ПРЕДАВАТЕЛЕН ПРОТОКОЛ\n№ {transfer.protocol_number}"
    )
    _set_run_font(run, 13, True)

    operation = document.add_paragraph()
    operation.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = operation.add_run("Операция: Предаване на HPWJ машина")
    _set_run_font(run, 10, True)

    table = document.add_table(rows=0, cols=2)
    table.style = "Table Grid"
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    table.autofit = False
    for label, value in _protocol_rows(transfer, batch_reference):
        cells = table.add_row().cells
        cells[0].width = Mm(49)
        cells[1].width = Mm(117)
        cells[0].vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
        cells[1].vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
        label_run = cells[0].paragraphs[0].add_run(label)
        _set_run_font(label_run, 9.5, True)
        value_run = cells[1].paragraphs[0].add_run(value)
        _set_run_font(value_run, 9.5)

    document.add_paragraph()
    signatures = document.add_table(rows=2, cols=2)
    signatures.alignment = WD_TABLE_ALIGNMENT.CENTER
    signatures.autofit = False
    values = [
        f"Предал: {transfer.handed_over_by or ''}",
        f"Приел: {transfer.accepted_by or ''}",
        "Подпис: __________________",
        "Подпис: __________________",
    ]
    for index, cell in enumerate(
        [
            signatures.cell(0, 0),
            signatures.cell(0, 1),
            signatures.cell(1, 0),
            signatures.cell(1, 1),
        ]
    ):
        cell.width = Mm(83)
        cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
        run = cell.paragraphs[0].add_run(values[index])
        _set_run_font(run, 10, index < 2)

    output = io.BytesIO()
    document.save(output)
    return output.getvalue()


def _register_pdf_fonts() -> tuple[str, str]:
    normal_candidates = [
        Path("C:/Windows/Fonts/arial.ttf"),
        Path("C:/Windows/Fonts/dejavusans.ttf"),
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
    ]
    bold_candidates = [
        Path("C:/Windows/Fonts/arialbd.ttf"),
        Path("C:/Windows/Fonts/dejavusans-bold.ttf"),
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
    ]
    normal_path = next((path for path in normal_candidates if path.is_file()), None)
    bold_path = next((path for path in bold_candidates if path.is_file()), None)
    if normal_path is None or bold_path is None:
        raise RuntimeError(
            "Липсва Unicode шрифт за генериране на български PDF протокол."
        )
    if "AssetCoreSans" not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont("AssetCoreSans", str(normal_path)))
    if "AssetCoreSans-Bold" not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont("AssetCoreSans-Bold", str(bold_path)))
    return "AssetCoreSans", "AssetCoreSans-Bold"


def build_protocol_pdf(transfer: TransferProtocol, batch_reference: str) -> bytes:
    normal_font, bold_font = _register_pdf_fonts()
    output = io.BytesIO()
    pdf = SimpleDocTemplate(
        output,
        pagesize=A4,
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=16 * mm,
        bottomMargin=16 * mm,
        title=f"Протокол {transfer.protocol_number}",
        author="AssetCore",
    )
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "AssetCoreTitle",
        parent=styles["Title"],
        fontName=bold_font,
        fontSize=14,
        leading=17,
        alignment=TA_CENTER,
        textColor=colors.HexColor("#172033"),
        spaceAfter=5 * mm,
    )
    body_style = ParagraphStyle(
        "AssetCoreBody",
        parent=styles["BodyText"],
        fontName=normal_font,
        fontSize=9.5,
        leading=12,
        textColor=colors.HexColor("#172033"),
    )
    label_style = ParagraphStyle(
        "AssetCoreLabel",
        parent=body_style,
        fontName=bold_font,
    )
    story = [
        Paragraph("ОДЕСОС ШИПРИПЕЪР ЯРД АД", title_style),
        Paragraph(
            f"ПРИЕМО-ПРЕДАВАТЕЛЕН ПРОТОКОЛ<br/>№ {escape(transfer.protocol_number)}",
            title_style,
        ),
        Paragraph("Операция: Предаване на HPWJ машина", label_style),
        Spacer(1, 4 * mm),
    ]
    data = [
        [Paragraph(escape(label), label_style), Paragraph(escape(value), body_style)]
        for label, value in _protocol_rows(transfer, batch_reference)
    ]
    table = Table(data, colWidths=[49 * mm, 117 * mm], repeatRows=0)
    table.setStyle(
        TableStyle(
            [
                ("GRID", (0, 0), (-1, -1), 0.55, colors.HexColor("#8292a3")),
                ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#eef2f6")),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ]
        )
    )
    story.extend([table, Spacer(1, 8 * mm)])
    signature_data = [
        [
            Paragraph(f"Предал: {escape(transfer.handed_over_by or '')}", label_style),
            Paragraph(f"Приел: {escape(transfer.accepted_by or '')}", label_style),
        ],
        [Paragraph("Подпис: __________________", body_style), Paragraph("Подпис: __________________", body_style)],
    ]
    signature_table = Table(signature_data, colWidths=[83 * mm, 83 * mm])
    signature_table.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ]
        )
    )
    story.append(signature_table)
    pdf.build(story)
    return output.getvalue()


def build_daily_report_pdf(repairs: list) -> bytes:
    normal_font, bold_font = _register_pdf_fonts()
    output = io.BytesIO()
    pdf = SimpleDocTemplate(
        output,
        pagesize=A4,
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=16 * mm,
        bottomMargin=16 * mm,
        title="AssetCore - дневен HPWJ отчет",
        author="AssetCore",
    )
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "DailyTitle",
        parent=styles["Title"],
        fontName=bold_font,
        fontSize=16,
        leading=19,
        alignment=TA_CENTER,
    )
    body_style = ParagraphStyle(
        "DailyBody",
        parent=styles["BodyText"],
        fontName=normal_font,
        fontSize=9.5,
        leading=12,
    )
    story = [
        Paragraph("AssetCore - дневен HPWJ отчет", title_style),
        Paragraph(datetime.now().strftime("%d.%m.%Y %H:%M"), body_style),
        Spacer(1, 5 * mm),
    ]
    if not repairs:
        story.append(Paragraph("Няма регистрирани ремонти.", body_style))
    else:
        data = [[
            Paragraph("Машина", ParagraphStyle("DailyHead1", parent=body_style, fontName=bold_font)),
            Paragraph("Проблем", ParagraphStyle("DailyHead2", parent=body_style, fontName=bold_font)),
            Paragraph("Статус", ParagraphStyle("DailyHead3", parent=body_style, fontName=bold_font)),
        ]]
        for repair in repairs:
            data.append([
                Paragraph(escape(repair.machine.name), body_style),
                Paragraph(escape(repair.reported_problem), body_style),
                Paragraph(escape(repair.status), body_style),
            ])
        table = Table(data, colWidths=[38 * mm, 90 * mm, 38 * mm], repeatRows=1)
        table.setStyle(TableStyle([
            ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#8292a3")),
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eaf1f7")),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("LEFTPADDING", (0, 0), (-1, -1), 5),
            ("RIGHTPADDING", (0, 0), (-1, -1), 5),
            ("TOPPADDING", (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ]))
        story.append(table)
    pdf.build(story)
    return output.getvalue()


def make_protocol_documents(
    transfer: TransferProtocol, batch: TransferBatch, created_by_id: int
) -> list[ProtocolDocument]:
    stem = safe_filename(transfer.protocol_number)
    generated = [
        ("docx", DOCX_MEDIA_TYPE, build_protocol_docx(transfer, batch.batch_reference)),
        ("pdf", PDF_MEDIA_TYPE, build_protocol_pdf(transfer, batch.batch_reference)),
    ]
    documents: list[ProtocolDocument] = []
    for format_name, media_type, content in generated:
        documents.append(
            ProtocolDocument(
                transfer_id=transfer.id,
                machine_id=transfer.machine_id,
                batch_id=batch.id,
                format=format_name,
                filename=f"{stem}.{format_name}",
                media_type=media_type,
                content=content,
                sha256=hashlib.sha256(content).hexdigest(),
                created_by_id=created_by_id,
                created_at=transfer.created_at,
            )
        )
    return documents
