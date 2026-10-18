"""In-memory analytical exports. These do not create or replace official documents."""

import io
import json
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from xml.sax.saxutils import escape

from reportlab.graphics.charts.barcharts import VerticalBarChart
from reportlab.graphics.shapes import Drawing
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from ..documents.rendering import _register_pdf_fonts
from ..localization import status_label
from .filters import SOFIA

LABELS = json.loads(Path(__file__).with_name("labels.json").read_text(encoding="utf-8"))


def label(key, language):
    return LABELS.get(key, [key] * 3)[("bg", "en", "ru").index(language)]


def reference(row):
    return (
        row.get("official_number")
        or row.get("request_reference")
        or row.get("repair_reference")
        or row.get("protocol_number")
        or str(row["id"])
    )


def details_rows(details, language):
    result = []
    for kind, records in details.items():
        for r in records:
            m = r.get("machine")
            remaining = "; ".join(
                f"{line['description']}: {line['quantity']} {line['unit'] or '?'}"
                for line in r.get("remaining", [])
            )
            result.append(
                [
                    label(kind, language),
                    r["id"],
                    reference(r),
                    f"№{m['inventory_number']} {m['name']}" if m else label("general", language),
                    r.get("issued_at") or r.get("opened_at") or r.get("created_at"),
                    r.get("returned_at")
                    if r.get("return_status") == "COMPLETED"
                    else r.get("closed_at") or r.get("delivered_at"),
                    status_label(
                        r.get("status") or r.get("return_status") or r.get("issue_status") or "",
                        language,
                    ),
                    r.get("reported_problem") or r.get("part_name") or r.get("return_damage") or "",
                    r.get("issue_hours"),
                    r.get("cycle_hours"),
                    r.get("source_return_transfer_id"),
                    remaining,
                    r.get("elapsed_days"),
                    r.get("remaining_lines"),
                ]
            )
    return result


def filter_text(data, language):
    f = data["filters"]
    return f"{f['date_from']} - {f['date_to']} · Europe/Sofia · {label('category', language)}: {f['category_id'] or (label('uncategorized', language) if f['uncategorized'] else '*')} · {label('machineLabel', language)}: {', '.join(map(str, f['machine_ids'])) or '*'} · {f['q']}"


def sheets(data, details, language):
    def tr(key):
        return label(key, language)

    summary = [
        [tr("title"), tr(data["section"])],
        [tr("generated"), datetime.fromisoformat(data["generated_at"])],
        [tr("filters"), filter_text(data, language)],
        [tr("analytical")],
        [],
        [
            tr("description"),
            tr("quantity"),
            tr("unit"),
            tr("previous"),
            "Δ",
            "%",
            tr("sample"),
            tr("current"),
        ],
    ]
    for m in data["current"] + data["metrics"]:
        summary.append(
            [
                tr(m["key"]),
                m["value"],
                tr(m["unit"]),
                m["previous"],
                m["change"],
                m["percent"],
                m["sample"],
                tr("current") if m["current"] else tr("period"),
            ]
        )
    for item in data["machines"]:
        summary += [
            [],
            [
                tr("machineLabel"),
                f"№{item['machine']['inventory_number']} {item['machine']['name']}",
            ],
        ]
        for kind, metrics in item["metrics"].items():
            for m in metrics:
                summary.append(
                    [
                        tr(kind) + " · " + tr(m["key"]),
                        m["value"],
                        tr(m["unit"]),
                        m["previous"],
                        m["change"],
                        m["percent"],
                        m["sample"],
                    ]
                )
    records = [
        [
            tr("category"),
            "ID",
            tr("reference"),
            tr("machineLabel"),
            tr("date"),
            tr("end"),
            tr("status"),
            tr("description"),
            tr("issue_hours"),
            tr("avg_cycle_hours"),
            "source_return_transfer_id",
            tr("remaining"),
            tr("elapsed"),
            tr("unfulfilled"),
        ]
    ]
    records += details_rows(details, language)
    trends = [
        [tr("period")]
        + [tr(k) for k in ("issues", "completed_cycles", "opened", "closed", "created", "receipts")]
    ]
    for row in data["trends"]:
        trends.append(
            [row["period"]]
            + [
                row.get(k, 0)
                for k in ("issues", "completed_cycles", "opened", "closed", "created", "receipts")
            ]
        )
    methodology = [
        [tr("methodology")],
        [tr("methodText")],
        [tr("attentionNote")],
        [tr("delayedNote")],
        [tr("articlesNote")],
        [tr("compareNote")],
        [json.dumps(data["thresholds"], ensure_ascii=False)],
    ]
    attention = [[tr("machineLabel"), tr("reasons"), tr("openCount")]]
    for item in data["attention"]:
        reasons = []
        for reason in item["reasons"]:
            text = tr(reason["code"])
            for k, v in reason.items():
                text = text.replace("{{" + k + "}}", str(v))
            reasons.append(text)
        attention.append(
            [item["machine"]["inventory_number"], " ".join(reasons), item["open_count"]]
        )
    return [
        (tr("summary"), summary),
        (tr("records"), records),
        (tr("trends"), trends),
        (tr("attention"), attention),
        (tr("methodology"), methodology),
    ]


def export_xlsx(data, details, language):
    """Minimal standards-based OOXML, no formulas or executable user text.

    Inline string cells preserve =,+,-,@ literally. Numeric and date cells are typed.
    No spreadsheet library or external service is needed by the production server.
    """
    ns = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
    rel = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
    package = "http://schemas.openxmlformats.org/package/2006/relationships"
    output = io.BytesIO()
    content_types = [
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>',
        '<Default Extension="xml" ContentType="application/xml"/>',
        '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>',
        '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>',
    ]
    workbook, relationships = [], []
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as z:
        for index, (name, rows) in enumerate(sheets(data, details, language), 1):
            name = name[:31]
            workbook.append(f'<sheet name="{escape(name)}" sheetId="{index}" r:id="rId{index}"/>')
            relationships.append(
                f'<Relationship Id="rId{index}" Type="{rel}/worksheet" Target="worksheets/sheet{index}.xml"/>'
            )
            content_types.append(
                f'<Override PartName="/xl/worksheets/sheet{index}.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
            )
            xml_rows = []
            columns = max(len(row) for row in rows)
            for rn, row in enumerate(rows, 1):
                cells = []
                for cn, value in enumerate(row, 1):
                    letters, n = "", cn
                    while n:
                        n, rem = divmod(n - 1, 26)
                        letters = chr(65 + rem) + letters
                    address = f"{letters}{rn}"
                    if value is None:
                        continue
                    style = 1 if rn == 1 or (index == 1 and rn == 6) else 0
                    if (
                        isinstance(value, str)
                        and len(value) >= 19
                        and value[4:5] == "-"
                        and value[10:11] == "T"
                    ):
                        try:
                            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
                        except ValueError:
                            pass
                    if isinstance(value, datetime):
                        local = value.replace(tzinfo=UTC) if value.tzinfo is None else value
                        serial = (
                            local.astimezone(SOFIA).replace(tzinfo=None) - datetime(1899, 12, 30)
                        ).total_seconds() / 86400
                        cells.append(f'<c r="{address}" s="2"><v>{serial}</v></c>')
                    elif isinstance(value, (int, float)):
                        cells.append(f'<c r="{address}" s="{style}"><v>{value}</v></c>')
                    else:
                        safe = "".join(ch for ch in str(value) if ord(ch) >= 32 or ch in "\n\t")[
                            :32767
                        ]
                        cells.append(
                            f'<c r="{address}" s="{style}" t="inlineStr"><is><t xml:space="preserve">{escape(safe)}</t></is></c>'
                        )
                xml_rows.append(f'<row r="{rn}">' + "".join(cells) + "</row>")
            cols = "".join(
                f'<col min="{i}" max="{i}" width="{55 if i in (1, 4, 8, 12) else 25}" customWidth="1"/>'
                for i in range(1, columns + 1)
            )
            filter_xml = f'<autoFilter ref="A1:N{len(rows)}"/>' if index == 2 else ""
            z.writestr(
                f"xl/worksheets/sheet{index}.xml",
                f'<?xml version="1.0" encoding="UTF-8"?><worksheet xmlns="{ns}"><sheetViews><sheetView workbookViewId="0"><pane ySplit="1" topLeftCell="A2" state="frozen"/></sheetView></sheetViews><cols>{cols}</cols><sheetData>{"".join(xml_rows)}</sheetData>{filter_xml}</worksheet>',
            )
        relationships.append(f'<Relationship Id="styles" Type="{rel}/styles" Target="styles.xml"/>')
        z.writestr(
            "xl/workbook.xml",
            f'<?xml version="1.0" encoding="UTF-8"?><workbook xmlns="{ns}" xmlns:r="{rel}"><sheets>{"".join(workbook)}</sheets></workbook>',
        )
        z.writestr(
            "xl/_rels/workbook.xml.rels",
            f'<Relationships xmlns="{package}">{"".join(relationships)}</Relationships>',
        )
        z.writestr(
            "_rels/.rels",
            f'<Relationships xmlns="{package}"><Relationship Id="rId1" Type="{rel}/officeDocument" Target="xl/workbook.xml"/></Relationships>',
        )
        z.writestr(
            "[Content_Types].xml",
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            + "".join(content_types)
            + "</Types>",
        )
        z.writestr(
            "xl/styles.xml",
            f'<styleSheet xmlns="{ns}"><numFmts count="1"><numFmt numFmtId="164" formatCode="yyyy-mm-dd hh:mm"/></numFmts><fonts count="2"><font><sz val="11"/><name val="Calibri"/></font><font><b/><color rgb="FFFFFFFF"/><sz val="11"/><name val="Calibri"/></font></fonts><fills count="3"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill><fill><patternFill patternType="solid"><fgColor rgb="FF164E63"/><bgColor indexed="64"/></patternFill></fill></fills><borders count="1"><border/></borders><cellStyleXfs count="1"><xf/></cellStyleXfs><cellXfs count="3"><xf fontId="0" fillId="0" borderId="0" xfId="0"><alignment vertical="top" wrapText="1"/></xf><xf fontId="1" fillId="2" borderId="0" xfId="0"><alignment vertical="top" wrapText="1"/></xf><xf fontId="0" fillId="0" borderId="0" numFmtId="164" applyNumberFormat="1" xfId="0"/></cellXfs><cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles></styleSheet>',
        )
    return output.getvalue()


def export_pdf(data, details, language):
    normal, bold = _register_pdf_fonts()
    body = ParagraphStyle(
        "ReportBody", fontName=normal, fontSize=9, leading=13, textColor=colors.HexColor("#183548")
    )
    heading = ParagraphStyle(
        "ReportHeading",
        parent=body,
        fontName=bold,
        fontSize=13,
        leading=18,
        spaceBefore=14,
        spaceAfter=8,
        keepWithNext=True,
    )
    title = ParagraphStyle("ReportTitle", parent=heading, fontSize=22, leading=28)

    def tr(key):
        return label(key, language)

    def p(text):
        return Paragraph(escape(str(text if text is not None else tr("insufficient"))), body)

    stream = io.BytesIO()
    pdf = SimpleDocTemplate(
        stream,
        pagesize=landscape(A4),
        leftMargin=16 * mm,
        rightMargin=16 * mm,
        topMargin=15 * mm,
        bottomMargin=17 * mm,
        title=tr("title"),
        author="AssetCore",
    )
    story = [
        Paragraph("AssetCore · " + tr("title"), title),
        Paragraph(tr(data["section"]), heading),
        p(tr("generated") + ": " + data["generated_at"]),
        p(filter_text(data, language)),
        p(tr("analytical")),
        Spacer(1, 8 * mm),
    ]

    def table(rows, widths):
        t = Table(
            [[p(cell) for cell in row] for row in rows],
            colWidths=widths,
            repeatRows=1,
            hAlign="LEFT",
            splitInRow=1,
        )
        t.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e1f0f4")),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    (
                        "ROWBACKGROUNDS",
                        (0, 1),
                        (-1, -1),
                        [colors.white, colors.HexColor("#f4f8fa")],
                    ),
                    ("LEFTPADDING", (0, 0), (-1, -1), 7),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 7),
                    ("TOPPADDING", (0, 0), (-1, -1), 6),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                ]
            )
        )
        story.append(t)

    for name, metrics in [("current", data["current"]), ("period", data["metrics"])]:
        if not metrics:
            continue
        story.append(Paragraph(tr(name), heading))
        table(
            [[tr("description"), tr("quantity"), tr("unit"), tr("previous"), tr("sample")]]
            + [
                [tr(m["key"]), m["value"], tr(m["unit"]), m["previous"], m["sample"]]
                for m in metrics
            ],
            [125 * mm, 34 * mm, 25 * mm, 45 * mm, 36 * mm],
        )
    if data["trends"]:
        story.append(Paragraph(tr("trends"), heading))
        keys = [
            k
            for k in ("issues", "completed_cycles", "opened", "closed", "created", "receipts")
            if any(row.get(k) for row in data["trends"])
        ]
        if keys:
            # Six or fewer unstacked series; actual data, never a screen capture.
            drawing = Drawing(740, 190)
            chart = VerticalBarChart()
            chart.x, chart.y, chart.width, chart.height = 35, 30, 680, 145
            chart.data = [tuple(r.get(k, 0) for r in data["trends"]) for k in keys]
            chart.categoryAxis.categoryNames = [r["period"] for r in data["trends"]]
            chart.categoryAxis.labels.fontName, chart.categoryAxis.labels.fontSize = normal, 7
            chart.valueAxis.labels.fontName = normal
            chart.valueAxis.valueMin = 0
            palette = ["#0e7490", "#16a34a", "#ea580c", "#7c3aed", "#2563eb", "#be185d"]
            for i, color in enumerate(palette[: len(keys)]):
                chart.bars[i].fillColor = colors.HexColor(color)
            drawing.add(chart)
            story += [drawing, p(" · ".join(tr(k) for k in keys))]
            table(
                [[tr("period")] + [tr(k) for k in keys]]
                + [[r["period"]] + [r.get(k, 0) for k in keys] for r in data["trends"]],
                [265 * mm / (len(keys) + 1)] * (len(keys) + 1),
            )
    for item in data["machines"]:
        story.append(
            Paragraph(
                f"{tr('machineLabel')} №{escape(item['machine']['inventory_number'])}", heading
            )
        )
        table(
            [[tr("description"), tr("quantity"), tr("unit"), tr("sample")]]
            + [
                [tr(k) + " · " + tr(m["key"]), m["value"], tr(m["unit"]), m["sample"]]
                for k, ms in item["metrics"].items()
                for m in ms
            ],
            [155 * mm, 40 * mm, 30 * mm, 40 * mm],
        )
    for kind, rows in details.items():
        story.append(Paragraph(tr(kind) + " · " + tr("records"), heading))
        flat = details_rows({kind: rows}, language)
        if flat:
            table(
                [
                    [
                        tr("reference"),
                        tr("machineLabel"),
                        tr("date"),
                        tr("end"),
                        tr("description"),
                        tr("status"),
                    ]
                ]
                + [
                    [
                        r[2],
                        r[3],
                        str(r[4] or ""),
                        str(r[5] or ""),
                        r[7] + (" · " + r[11] if r[11] else ""),
                        r[6],
                    ]
                    for r in flat
                ],
                [34 * mm, 48 * mm, 34 * mm, 34 * mm, 79 * mm, 36 * mm],
            )
        else:
            story.append(p(tr("empty")))
    story += [
        Paragraph(tr("methodology"), heading),
        p(tr("methodText")),
        Spacer(1, 4 * mm),
        p(tr("attentionNote")),
        p(tr("delayedNote")),
        p(tr("compareNote")),
    ]

    def footer(canvas, doc):
        canvas.setFont(normal, 8)
        canvas.setFillColor(colors.HexColor("#526a78"))
        canvas.drawString(16 * mm, 9 * mm, "AssetCore · REPORTS-01")
        canvas.drawRightString(281 * mm, 9 * mm, f"{tr('page')} {doc.page}")

    pdf.build(story, onFirstPage=footer, onLaterPages=footer)
    return stream.getvalue()
