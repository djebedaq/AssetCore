"""Allowlisted flow layout -> editable DOCX -> exact DOCX PDF.

Published sources carry their complete immutable rendering inputs. No database,
network, current company settings, expressions or file paths are read here.
"""
from __future__ import annotations

import base64
import hashlib
import io
import json
import math
import zipfile
from threading import BoundedSemaphore

import fitz
import qrcode
from docx import Document
from docx.enum.table import WD_ROW_HEIGHT_RULE, WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Mm, Pt, RGBColor
from lxml import etree as ElementTree

from .files import validate_docx
from .schemas import FIELD_CATALOG, Layout, validate_workflow

MANIFEST = "assetcore/studio.json"
MAX_PAGES = 40
_CONVERSIONS = BoundedSemaphore(2)
TABLE_KEYS = {
    "REQUEST_LINES": ("position", "part_number", "description", "quantity"),
    "PARTS_USED": ("position", "part_number", "description", "quantity"),
    "REPAIR_EVENTS": ("date", "event_type", "description"),
}


def canonical(value) -> bytes:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()


def digest(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def check_layout(layout: Layout, document_type: str):
    validate_workflow(layout, document_type)
    width, height = (210, 297) if layout.page.orientation == "portrait" else (297, 210)
    usable = width - 2 * layout.page.margin_mm
    for region in ("header", "footer"):
        # Header/footer content must fit wholly inside the reserved margin.
        total = 0
        for block in (b for b in layout.blocks if b.region == region):
            if block.type not in {"text", "heading", "field", "image", "logo", "line", "page_number"}:
                raise ValueError("studio_invalid_region")
            if block.type in {"image", "logo"}:
                total += block.height_mm + block.style.spacing_mm
            else:
                text = getattr(block, "text", "")
                if len(text) > 120 or "\n" in text:
                    raise ValueError("studio_region_overflow")
                total += block.style.size_pt * .5 + block.style.spacing_mm
        if total > layout.page.margin_mm - 6:
            raise ValueError("studio_region_overflow")
    previous = None
    body = [b for b in layout.blocks if b.region == "body"]
    for block in layout.blocks:
        if block.type in {"image", "logo", "frame", "qr"}:
            if block.width_mm > usable or block.height_mm > height - 2 * layout.page.margin_mm:
                raise ValueError("studio_bounds")
        if block.type == "dynamic_table" and any(c.width_percent < 5 for c in block.columns):
            raise ValueError("studio_table_width")
        if block.type in {"dynamic_table", "table"}:
            widths = [c.width_percent for c in block.columns] if block.type == "dynamic_table" else block.widths or [100 / len(block.rows[0])] * len(block.rows[0])
            if min(widths) * usable * block.style.width_percent / 10000 < block.style.size_pt * 1.5 * 25.4 / 72 + 2:
                raise ValueError("studio_table_width")
        if block.type == "signature" and (block.style.size_pt > 18 or block.style.width_percent < 40):
            raise ValueError("studio_bounds")
        if block.type == "page_break" and (block is body[0] or block is body[-1] or previous == "page_break"):
            raise ValueError("studio_blank_page")
        if block.region == "body":
            previous = block.type


def manifest_from_source(content: bytes) -> dict | None:
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        if MANIFEST not in archive.namelist():
            return None
        info = archive.getinfo(MANIFEST)
        if info.file_size > 8_000_000:
            raise ValueError("studio_source_size")
        manifest = json.loads(archive.read(MANIFEST))
    if manifest.get("renderer") != 1 or manifest.get("language") not in {"bg", "en", "ru"}:
        raise ValueError("studio_source_invalid")
    layout = Layout.model_validate(manifest["layout"])
    check_layout(layout, manifest["document_type"])
    ids = {str(b.image_id) for b in layout.blocks if b.type in {"image", "logo"}}
    if ids != set(manifest["images"]):
        raise ValueError("studio_image_missing")
    for image in manifest["images"].values():
        raw = base64.b64decode(image["content"], validate=True)
        if len(raw) > 4_000_000 or digest(raw) != image["sha256"]:
            raise ValueError("studio_image_invalid")
    return manifest


def _stable_zip(content: bytes, manifest: dict | None = None) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(content)) as source, zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as target:
        entries = {i.filename: source.read(i) for i in source.infolist()}
        if manifest is not None:
            entries[MANIFEST] = canonical(manifest)
            # A real OPC relationship preserves the frozen evidence through
            # later python-docx signature and visual-appendix edits.
            root = ElementTree.fromstring(entries["[Content_Types].xml"])
            if not any(n.attrib.get("PartName") == "/" + MANIFEST for n in root):
                ElementTree.SubElement(root, "{http://schemas.openxmlformats.org/package/2006/content-types}Override",
                    {"PartName": "/" + MANIFEST, "ContentType": "application/vnd.assetcore.studio+json"})
            entries["[Content_Types].xml"] = ElementTree.tostring(root, encoding="utf-8", xml_declaration=True)
            root = ElementTree.fromstring(entries["_rels/.rels"])
            if not any(n.attrib.get("Target") == MANIFEST for n in root):
                ElementTree.SubElement(root, "{http://schemas.openxmlformats.org/package/2006/relationships}Relationship",
                    {"Id": "assetcoreStudio", "Type": "urn:assetcore:studio:1", "Target": MANIFEST})
            entries["_rels/.rels"] = ElementTree.tostring(root, encoding="utf-8", xml_declaration=True)
        for name, data in sorted(entries.items()):
            entry = zipfile.ZipInfo(name, (2000, 1, 1, 0, 0, 0))
            entry.compress_type = zipfile.ZIP_DEFLATED
            target.writestr(entry, data)
    return output.getvalue()


def _paragraph_style(paragraph, style, width):
    paragraph.alignment = {"left": WD_ALIGN_PARAGRAPH.LEFT, "center": WD_ALIGN_PARAGRAPH.CENTER,
                           "right": WD_ALIGN_PARAGRAPH.RIGHT}[style.align]
    paragraph.paragraph_format.space_after = Mm(style.spacing_mm)
    paragraph.paragraph_format.widow_control = True
    unused = width * (1 - style.width_percent / 100)
    paragraph.paragraph_format.left_indent = Mm(unused if style.align == "right" else unused / 2 if style.align == "center" else 0)
    paragraph.paragraph_format.right_indent = Mm(unused if style.align == "left" else unused / 2 if style.align == "center" else 0)
    props = paragraph._p.get_or_add_pPr()
    shade = OxmlElement("w:shd")
    shade.set(qn("w:fill"), style.background[1:])
    props.append(shade)
    if style.border_pt:
        borders = OxmlElement("w:pBdr")
        for edge in ("top", "left", "bottom", "right"):
            border = OxmlElement(f"w:{edge}")
            for name, value in {"val": "single", "sz": str(round(style.border_pt * 8)), "color": style.color[1:]}.items():
                border.set(qn(f"w:{name}"), value)
            borders.append(border)
        props.append(borders)


def _text(paragraph, value, style):
    run = paragraph.add_run(str(value) if value is not None else "")
    run.font.name, run.font.size = style.font, Pt(style.size_pt)
    fonts = run._element.get_or_add_rPr().rFonts
    for key in ("ascii", "hAnsi", "eastAsia", "cs"):
        fonts.set(qn(f"w:{key}"), style.font)
    run.font.color.rgb = RGBColor.from_string(style.color[1:])
    run.bold, run.italic = style.bold, style.italic
    return run


def _page_number(paragraph, style):
    for instruction in ("PAGE", "NUMPAGES"):
        if instruction == "NUMPAGES":
            _text(paragraph, " / ", style)
        for kind in ("begin", "instruction", "separate", "value", "end"):
            run = paragraph.add_run()
            run.font.name, run.font.size = style.font, Pt(style.size_pt)
            run.font.color.rgb = RGBColor.from_string(style.color[1:])
            if kind == "instruction":
                node = OxmlElement("w:instrText")
                node.text = instruction
            elif kind == "value":
                node = OxmlElement("w:t")
                node.text = "1"
            else:
                node = OxmlElement("w:fldChar")
                node.set(qn("w:fldCharType"), kind)
            run._r.append(node)


def _table(container, rows, widths, style, width, repeat):
    table = container.add_table(rows=0, cols=len(widths))
    table.autofit = False
    table.alignment = {"left": WD_TABLE_ALIGNMENT.LEFT, "center": WD_TABLE_ALIGNMENT.CENTER,
                       "right": WD_TABLE_ALIGNMENT.RIGHT}[style.align]
    table.style = "Table Grid"
    _table_borders(table, style)
    actual_width = width * style.width_percent / 100
    for col, percent in zip(table.columns, widths, strict=True):
        col.width = Mm(actual_width * percent / 100)
    for index, values in enumerate(rows):
        row = table.add_row()
        if index == 0 and repeat:
            row._tr.get_or_add_trPr().append(OxmlElement("w:tblHeader"))
        # No exact heights or cantSplit: long cells flow to following pages.
        for cell, value, percent in zip(row.cells, values, widths, strict=True):
            cell.width = Mm(actual_width * percent / 100)
            paragraph = cell.paragraphs[0]
            # The table owns the grid. Paragraph borders would draw a second
            # box inside every cell and distort the requested cell spacing.
            _paragraph_style(paragraph, style.model_copy(update={"border_pt": 0}), actual_width * percent / 100)
            paragraph.paragraph_format.left_indent = paragraph.paragraph_format.right_indent = Mm(0)
            _text(paragraph, value, style)
            if index == 0 and repeat:
                for run in paragraph.runs:
                    run.bold = True
            shade = OxmlElement("w:shd")
            shade.set(qn("w:fill"), style.background[1:])
            cell._tc.get_or_add_tcPr().append(shade)
    container.add_paragraph().paragraph_format.space_after = Mm(style.spacing_mm)


def _table_borders(table, style):
    props = table._tbl.tblPr
    for old in list(props.findall(qn("w:tblBorders"))):
        props.remove(old)
    borders = OxmlElement("w:tblBorders")
    for edge in ("top", "left", "bottom", "right", "insideH", "insideV"):
        border = OxmlElement(f"w:{edge}")
        for key, val in {"val": "single" if style.border_pt else "nil", "sz": str(max(1, round(style.border_pt * 8))), "color": style.color[1:]}.items():
            border.set(qn(f"w:{key}"), val)
        borders.append(border)
    props.append(borders)


def render(manifest: dict, values: dict, tables: dict | None = None, *, source=False) -> bytes:
    layout = Layout.model_validate(manifest["layout"])
    check_layout(layout, manifest["document_type"])
    document = Document()
    document.core_properties.author = "AssetCore"
    document.core_properties.title = "AssetCore"
    document.core_properties.language = manifest["language"]
    update_fields = OxmlElement("w:updateFields")
    update_fields.set(qn("w:val"), "true")
    document.settings.element.append(update_fields)
    section = document.sections[0]
    page_width, page_height = (210, 297) if layout.page.orientation == "portrait" else (297, 210)
    section.page_width, section.page_height = Mm(page_width), Mm(page_height)
    for edge in ("top_margin", "bottom_margin", "left_margin", "right_margin"):
        setattr(section, edge, Mm(layout.page.margin_mm))
    section.header_distance = section.footer_distance = Mm(3)
    width = page_width - 2 * layout.page.margin_mm
    identity = manifest["company"]["identity"]
    bindings = {**values, "COMPANY_NAME": identity["legal_name"],
        "COMPANY_ADDRESS": ", ".join(identity[k] for k in ("address", "city", "country") if identity[k]),
        "COMPANY_REGISTRATION": " · ".join(identity[k] for k in ("registration_number", "vat_number") if identity[k]),
        "COMPANY_CONTACTS": " · ".join(identity[k] for k in ("phone", "email", "website") if identity[k])}
    for region in ("header", "footer"):
        height = 0
        for block in (b for b in layout.blocks if b.region == region):
            if block.type in {"image", "logo"}:
                height += block.height_mm + block.style.spacing_mm
            else:
                text = str(bindings.get(block.field, "")) if block.type == "field" else getattr(block, "text", "")
                # Conservative glyph budget: headers/footers may never grow
                # into body/signature content when a real snapshot is longer.
                lines = max(1, math.ceil(len(text.expandtabs(4)) * block.style.size_pt * 1.5 /
                    (width * block.style.width_percent / 100 * 72 / 25.4)))
                height += lines * block.style.size_pt * 1.5 * 25.4 / 72 + block.style.spacing_mm
        if height > layout.page.margin_mm - 6:
            raise ValueError("studio_region_overflow")
    for block_index, block in enumerate(layout.blocks):
        container = document if block.region == "body" else getattr(section, block.region)
        style = block.style
        if block.type in {"table", "dynamic_table"}:
            if block.type == "table":
                rows, widths = block.rows, block.widths or [100 / len(block.rows[0])] * len(block.rows[0])
            else:
                widths = [c.width_percent for c in block.columns]
                raw = (tables or {}).get(block.source, [])
                if len(raw) > 501:
                    raise ValueError("studio_table_size")
                keys = TABLE_KEYS[block.source]
                records = [dict(row) for row in raw] if raw and isinstance(raw[0], dict) else [dict(zip(keys, row, strict=True)) for row in raw[1:]] if raw else []
                for record in records:
                    if "quantity" in record and "unit" not in record:
                        amount, _, unit = str(record["quantity"]).partition(" ")
                        record["quantity"], record["unit"] = amount, unit
                    if "quantity" in record and not any(c.key == "unit" for c in block.columns):
                        record["quantity"] = " ".join(str(v) for v in (record["quantity"], record.get("unit")) if v is not None and str(v) != "")
                rows = [[c.label for c in block.columns]] + [[r.get(c.key, "") for c in block.columns] for r in records]
            _table(container, rows, widths, style, width, block.repeat_header)
            continue
        if block.type == "conditional" and bindings.get(block.when_field) in (None, "") and not source:
            continue
        paragraph = container.add_paragraph()
        _paragraph_style(paragraph, style.model_copy(update={"border_pt": 0}) if block.type == "line" else style, width)
        if block.type in {"text", "heading", "conditional"}:
            if block.type == "heading":
                paragraph.style = "Heading 2"
                paragraph.paragraph_format.keep_with_next = True
            _text(paragraph, block.text, style)
        elif block.type == "field":
            if block.field not in bindings:
                raise ValueError("studio_binding_missing")
            _text(paragraph, bindings[block.field], style)
        elif block.type == "signature":
            side = block.slot.removesuffix("_SIGNATURE")
            _text(paragraph, " · ".join(str(bindings.get(f"{side}_{k}") or "") for k in ("SIGNER_NAME", "SIGNER_JOB_TITLE")), style)
            paragraph.paragraph_format.keep_with_next = True
            paragraph.paragraph_format.keep_together = True
            paragraph.paragraph_format.space_before = Mm(6)
            marker = container.add_paragraph()
            _paragraph_style(marker, style, width)
            value = bindings.get(block.slot, "")
            if value in {"[[ASSETCORE_LEFT_SIGNATURE]]", "[[ASSETCORE_RIGHT_SIGNATURE]]"}:
                _text(marker, "________________________", style)
                _text(marker, value, style).font.hidden = True
            else:
                _text(marker, value, style)
            marker.paragraph_format.keep_together = True
            if block_index + 1 < len(layout.blocks) and layout.blocks[block_index + 1].type == "signature":
                marker.paragraph_format.keep_with_next = True
        elif block.type in {"image", "logo"}:
            image = manifest["images"][str(block.image_id)]
            paragraph.add_run().add_picture(io.BytesIO(base64.b64decode(image["content"])), width=Mm(block.width_mm), height=Mm(block.height_mm))
        elif block.type == "page_break":
            paragraph.paragraph_format.page_break_before = True
            paragraph.paragraph_format.space_after = Mm(0)
            paragraph.paragraph_format.keep_with_next = True
        elif block.type == "page_number":
            _page_number(paragraph, style)
        elif block.type == "qr":
            # Encoded text only; never dereferenced. Official number is canonical.
            encoded = str(bindings.get("DOCUMENT_NUMBER", ""))[:255]
            qr = qrcode.make(encoded)
            stream = io.BytesIO()
            qr.save(stream, format="PNG")
            paragraph.add_run().add_picture(io.BytesIO(stream.getvalue()), width=Mm(block.width_mm), height=Mm(block.width_mm))
        elif block.type == "frame":
            paragraph._p.getparent().remove(paragraph._p)
            table = document.add_table(rows=1, cols=1)
            table.autofit = False
            table.columns[0].width = Mm(block.width_mm)
            table.rows[0].height, table.rows[0].height_rule = Mm(block.height_mm), WD_ROW_HEIGHT_RULE.AT_LEAST
            table.style = "Table Grid"
            _table_borders(table, style)
            table.alignment = {"left": WD_TABLE_ALIGNMENT.LEFT, "center": WD_TABLE_ALIGNMENT.CENTER, "right": WD_TABLE_ALIGNMENT.RIGHT}[style.align]
            cell = table.cell(0, 0)
            cell.width = Mm(block.width_mm)
            shade = OxmlElement("w:shd")
            shade.set(qn("w:fill"), style.background[1:])
            cell._tc.get_or_add_tcPr().append(shade)
            _paragraph_style(cell.paragraphs[0], style, block.width_mm)
            for border in list(cell.paragraphs[0]._p.get_or_add_pPr().findall(qn("w:pBdr"))):
                cell.paragraphs[0]._p.pPr.remove(border)
            _text(cell.paragraphs[0], block.text, style)
            document.add_paragraph().paragraph_format.space_after = Mm(style.spacing_mm)
        elif block.type == "line":
            _text(paragraph, block.text, style)
            unused = width - block.width_mm
            paragraph.paragraph_format.left_indent = Mm(unused if style.align == "right" else unused / 2 if style.align == "center" else 0)
            paragraph.paragraph_format.right_indent = Mm(unused if style.align == "left" else unused / 2 if style.align == "center" else 0)
            props = paragraph._p.get_or_add_pPr()
            borders = OxmlElement("w:pBdr")
            for edge in (("bottom",) if block.type == "line" else ("top", "left", "bottom", "right")):
                border = OxmlElement(f"w:{edge}")
                for key, val in {"val": "single", "sz": str(max(4, round(style.border_pt * 8))), "color": style.color[1:]}.items():
                    border.set(qn(f"w:{key}"), val)
                borders.append(border)
            props.append(borders)
    if source:
        paragraph = document.add_paragraph()
        run = paragraph.add_run("{{TEMPLATE_LANGUAGE:" + manifest["language"] + "}}")
        run.font.hidden = True
        run.font.size = Pt(1)
    stream = io.BytesIO()
    document.save(stream)
    content = _stable_zip(stream.getvalue(), manifest)
    validate_docx(content)
    return content


def build_source(manifest: dict) -> bytes:
    values = {key: "{{" + key + "}}" for key in FIELD_CATALOG}
    values.update({key: "{{" + key + "}}" for key in ("LEFT_SIGNATURE", "RIGHT_SIGNATURE")})
    return render(manifest, values, source=True)


def render_source(content: bytes, values: dict, tables=None) -> bytes:
    manifest = manifest_from_source(content)
    if manifest is None:
        raise ValueError("studio_source_invalid")
    return render(manifest, values, tables)


def inspect_pdf(content: bytes, *, raster=False) -> dict:
    if not content or len(content) > 20_000_000:
        raise ValueError("studio_pdf_invalid")
    pages = []
    with fitz.open(stream=content, filetype="pdf") as pdf:
        if not 1 <= len(pdf) <= MAX_PAGES:
            raise ValueError("studio_page_limit")
        for page in pdf:
            text = page.get_text()
            if not text.strip() and not page.get_images():
                raise ValueError("studio_blank_page")
            for x0, y0, x1, y1, *_ in page.get_text("blocks"):
                if x0 < 0 or y0 < 0 or x1 > page.rect.width + 1 or y1 > page.rect.height + 1:
                    raise ValueError("studio_pdf_overflow")
            pages.append({"width": page.rect.width, "height": page.rect.height,
                          "text_sha256": digest(text.encode()),
                          **({"png": base64.b64encode(page.get_pixmap(matrix=fitz.Matrix(1, 1), alpha=False).tobytes("png")).decode()} if raster else {})})
    return {"pages": pages, "page_count": len(pages), "pdf_sha256": digest(content)}


def pdf_required(docx: bytes) -> bytes:
    from ..template_engine import TemplateValidationError, convert_docx_to_pdf
    if not _CONVERSIONS.acquire(blocking=False):
        raise TemplateValidationError("studio_renderer_busy")
    try:
        pdf = convert_docx_to_pdf(docx, bounded=True)
    finally:
        _CONVERSIONS.release()
    if pdf is None:
        raise TemplateValidationError("studio_converter_unavailable")
    try:
        inspect_pdf(pdf)
    except ValueError as exc:
        raise TemplateValidationError(str(exc)) from None
    return pdf


def synthetic_values(language: str, count: int):
    # Explicitly synthetic, in-memory acceptance data; never ORM business rows.
    word = {"bg": "Синтетична проверка", "en": "Synthetic check", "ru": "Синтетическая проверка"}[language]
    values = {code: f"{word} · {code}" for code in FIELD_CATALOG}
    values.update(DOCUMENT_NUMBER="PREVIEW", LEFT_SIGNATURE="________________", RIGHT_SIGNATURE="________________")
    rows = [[str(i), "QA", (word + " дълго описание проверка / long description / описание " ) * (8 if i == count else 1), "1"] for i in range(1, count + 1)]
    return values, {"REQUEST_LINES": [["", "", "", ""]] + rows, "PARTS_USED": [["", "", "", ""]] + rows,
                    "REPAIR_EVENTS": [["", "", ""]] + [[r[0], r[1], r[2]] for r in rows]}
