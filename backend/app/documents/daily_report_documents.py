"""Daily repair-report PDF presentation."""

from __future__ import annotations

import io
from datetime import datetime
from xml.sax.saxutils import escape

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.platypus import (
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
)

from ..models import (
    Repair,
)
from .rendering import (
    _pdf_header,
    _pdf_styles,
    _pdf_table_style,
)


def build_daily_report_pdf(repairs: list[Repair]) -> bytes:
    _, _, body, label, title, _ = _pdf_styles()
    output = io.BytesIO()
    pdf = SimpleDocTemplate(output, pagesize=A4, leftMargin=10 * mm, rightMargin=8 * mm, topMargin=7 * mm, bottomMargin=8 * mm, title="AssetCore - дневен HPWJ отчет", author="AssetCore")
    story = [_pdf_header(), Spacer(1, 3 * mm), Paragraph("AssetCore - дневен HPWJ отчет", title), Paragraph(datetime.now().strftime("%d.%m.%Y %H:%M"), body), Spacer(1, 3 * mm)]
    if not repairs:
        story.append(Paragraph("Няма регистрирани ремонти.", body))
    else:
        data = [[Paragraph("Машина", label), Paragraph("Проблем", label), Paragraph("Статус", label)]]
        data.extend([[Paragraph(escape(repair.machine.name), body), Paragraph(escape(repair.reported_problem), body), Paragraph(escape(repair.status), body)] for repair in repairs])
        table = Table(data, colWidths=[38 * mm, 112 * mm, 42 * mm], repeatRows=1)
        table.setStyle(_pdf_table_style(header_rows=1))
        story.append(table)
    pdf.build(story)
    return output.getvalue()
