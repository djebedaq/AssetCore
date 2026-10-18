"""Validate actual HTTP exports and render review previews without altering them."""

import html
import io
import json
import os
import re
import subprocess
import zipfile
from datetime import datetime, timedelta
from pathlib import Path
from xml.etree import ElementTree as ET

import fitz
from pypdf import PdfReader


def validate(qa: Path):
    expected = json.loads((qa / "expected-export.json").read_text(encoding="utf-8"))
    root = Path(__file__).resolve().parents[2]
    labels = json.loads((root / "backend/app/reports/labels.json").read_text(encoding="utf-8"))
    pdf_bytes = (qa / "reports01-filtered.pdf").read_bytes()
    reader = PdfReader(io.BytesIO(pdf_bytes))
    text = "\n".join(page.extract_text() for page in reader.pages)
    assert "KK9000" in text and labels["requests"][0] in text and "Europe/Sofia" in text
    assert "{{" not in text
    ns = {"s": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    with zipfile.ZipFile(qa / "reports01-filtered.xlsx") as archive:
        for name in archive.namelist():
            ET.fromstring(archive.read(name))
        sheet = ET.fromstring(archive.read("xl/worksheets/sheet1.xml"))
        assert not sheet.findall(".//s:f", ns)
        cells = []
        actual = {}
        for row in sheet.findall(".//s:sheetData/s:row", ns):
            values = []
            for cell in row.findall("s:c", ns):
                value = cell.find("s:v", ns)
                content = "".join(cell.itertext()) if value is None else float(value.text)
                if cell.attrib.get("s") == "2" and value is not None:
                    content = (datetime(1899, 12, 30) + timedelta(days=float(value.text))).strftime(
                        "%d.%m.%Y %H:%M"
                    )
                column = 0
                for letter in re.match(r"[A-Z]+", cell.attrib["r"])[0]:
                    column = column * 26 + ord(letter) - 64
                while len(values) < column:
                    values.append("")
                values[column - 1] = content
            if int(row.attrib["r"]) >= 6:
                values += [""] * (8 - len(values))
            cells.append(values)
            if len(values) >= 2:
                actual[values[0]] = values[1]
        for metric in expected["current"] + expected["metrics"]:
            title = labels[metric["key"]][0]
            if metric["value"] is not None:
                assert actual[title] == metric["value"], title
        assert "KK9000" in archive.read("xl/worksheets/sheet2.xml").decode()
        assert any(
            c.attrib.get("s") == "2"
            for c in ET.fromstring(archive.read("xl/worksheets/sheet2.xml")).findall(".//s:c", ns)
        )
    with fitz.open(stream=pdf_bytes, filetype="pdf") as pdf:
        for index, page in enumerate(pdf):
            page.get_pixmap(matrix=fitz.Matrix(1.3, 1.3)).save(qa / f"14-pdf-page-{index + 1}.png")
    rendered_rows = []
    for index, row in enumerate(cells, 1):

        def display(value):
            return html.escape(f"{value:g}" if isinstance(value, float) else str(value))

        if index <= 3:
            rendered_rows.append(
                f'<tr><td>{display(row[0])}</td><td colspan="7">{display(row[1])}</td></tr>'
            )
        elif index == 4:
            rendered_rows.append(f'<tr><td colspan="8">{display(row[0])}</td></tr>')
        else:
            rendered_rows.append("<tr>" + "".join(f"<td>{display(v)}</td>" for v in row) + "</tr>")
    rows = "".join(rendered_rows)
    document = (
        '<!doctype html><meta charset="utf-8"><title>Actual XLSX content preview</title><style>body{font:14px Arial;color:#183548;margin:28px}h1{font-size:24px}table{border-collapse:collapse;width:100%;table-layout:fixed}td{border:1px solid #dce5ec;padding:10px;overflow-wrap:anywhere;vertical-align:top}td:first-child{width:32%}tr:nth-child(even){background:#f0f6f8}tr:first-child,tr:nth-child(6){background:#164e63;color:white;font-weight:bold}</style><h1>AssetCore · XLSX</h1><p>Преглед на действителните клетки от XLSX / Actual workbook cells</p><table>'
        + rows
        + "</table>"
    )
    (qa / "xlsx-preview.html").write_text(document, encoding="utf-8")
    env = os.environ.copy()
    env["QA_OUTPUT"] = str(qa)
    env["QA_BROWSER_CHANNEL"] = "msedge" if os.name == "nt" else ""
    subprocess.run(
        ["node", str(Path(__file__).with_name("reports01_xlsx_preview.mjs"))], env=env, check=True
    )
    (qa / "export-proof.json").write_text(
        json.dumps(
            {
                "valid_pdf": True,
                "pdf_pages": len(reader.pages),
                "valid_ooxml": True,
                "typed_dates": True,
                "formulas": 0,
                "matching_metrics": len(expected["current"] + expected["metrics"]),
                "official_number": "KK9000",
            },
            indent=2,
        ),
        encoding="utf-8",
    )
