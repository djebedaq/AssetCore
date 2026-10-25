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
from docx.enum.table import WD_CELL_VERTICAL_ALIGNMENT, WD_ROW_HEIGHT_RULE, WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Mm, Pt, RGBColor
from lxml import etree as ElementTree

from .files import validate_docx
from .schemas import FIELD_CATALOG, Layout, validate_workflow, walk_blocks

MANIFEST = "assetcore/studio.json"
MAX_PAGES = 40
_CONVERSIONS = BoundedSemaphore(2)
TABLE_KEYS = {
    "REQUEST_LINES": ("position", "part_number", "description", "quantity"),
    "PARTS_USED": ("position", "part_number", "description", "quantity"),
    "REPAIR_EVENTS": ("date", "event_type", "description"),
    "EQUIPMENT_CHECKLIST": ("position", "component", "condition", "measurement", "note"),
    "REPAIR_PARTICIPANTS": ("name", "job_title", "contribution", "duration"),
    "REPAIR_ATTACHMENTS": ("filename", "stage", "description"),
}


def canonical(value) -> bytes:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()


def digest(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def check_layout(layout: Layout, document_type: str):
    validate_workflow(layout, document_type)
    if layout.native is not None:
        return
    width, height = (210, 297) if layout.page.orientation == "portrait" else (297, 210)
    usable = width - 2 * layout.page.margin_mm
    def check(blocks, available, region="body", nested=False):
        previous = None
        for i, block in enumerate(blocks):
            if region != "body" and block.type not in {"grid", "text", "heading", "field", "image", "logo", "line", "page_number"}:
                raise ValueError("studio_invalid_region")
            actual = available * block.style.width_percent / 100
            if block.type in {"image", "logo", "frame", "qr", "line"}:
                if block.width_mm > actual or getattr(block, "height_mm", 0) > height - 2 * layout.page.margin_mm:
                    raise ValueError("studio_bounds")
            if block.type == "grid":
                for row_index, row in enumerate(block.grid_rows):
                    col = 0
                    if row.page_break_before and (region != "body" or nested or row_index < block.repeat_rows):
                        raise ValueError("studio_invalid_region")
                    if row_index < block.repeat_rows and any(b.type == "signature" for cell in row.cells for b in walk_blocks(cell.blocks)):
                        raise ValueError("studio_required_block")
                    for cell in row.cells:
                        inner = actual * sum(block.widths[col:col + cell.colspan]) / 100 - 2 * cell.padding_mm
                        if inner < 8:
                            raise ValueError("studio_table_width")
                        check(cell.blocks, inner, region, True)
                        col += cell.colspan
            if block.type in {"dynamic_table", "table"}:
                widths = [c.width_percent for c in block.columns] if block.type == "dynamic_table" else block.widths or [100 / len(block.rows[0])] * len(block.rows[0])
                padding = block.cell_padding_mm if block.cell_padding_mm is not None else 1
                if min(widths) < 5 or min(widths) * actual / 100 < block.style.size_pt * 1.5 * 25.4 / 72 + 2 * padding:
                    raise ValueError("studio_table_width")
            if block.type == "signature" and (block.style.size_pt > 18 or block.style.width_percent < 40 or actual < 32):
                raise ValueError("studio_bounds")
            if block.type == "page_break" and (i == 0 or i == len(blocks) - 1 or previous == "page_break"):
                raise ValueError("studio_blank_page")
            previous = block.type
    for region in ("body", "header", "footer"):
        blocks = [b for b in layout.blocks if b.region == region]
        check(blocks, usable, region)
        if region != "body":
            reserved = getattr(layout.page, region + "_mm") or layout.page.margin_mm - 6
            if sum(_height(b, usable, {}) for b in blocks) > reserved:
                raise ValueError("studio_region_overflow")


def _height(block, width, bindings):
    """Conservative header/footer budget; real snapshot values are checked too."""
    style = block.style
    width *= style.width_percent / 100
    if block.type == "grid":
        total = 0
        for row in block.grid_rows:
            col, heights = 0, []
            for cell in row.cells:
                inner = width * sum(block.widths[col:col + cell.colspan]) / 100 - 2 * cell.padding_mm
                heights.append(sum(_height(b, inner, bindings) for b in cell.blocks) + 2 * cell.padding_mm)
                col += cell.colspan
            total += max(row.min_height_mm, *heights)
        return total + style.spacing_mm + style.paragraph_before_mm
    if block.type in {"image", "logo", "native_image"}:
        return block.height_mm + style.spacing_mm + style.paragraph_before_mm
    text = str(bindings.get(block.field, "")) if block.type == "field" else getattr(block, "text", "")
    lines = sum(max(1, math.ceil(len(line.expandtabs(4)) * style.size_pt * .7 / max(1, width * 72 / 25.4))) for line in text.split("\n"))
    return lines * style.size_pt * 1.3 * 25.4 / 72 + style.spacing_mm + style.paragraph_before_mm


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
    ids = {str(b.image_id) for b in walk_blocks(layout.blocks) if b.type in {"image", "logo", "native_image"} and b.image_id is not None}
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


def _shade(properties, color):
    if color != "transparent":
        shade = OxmlElement("w:shd")
        shade.set(qn("w:fill"), color[1:])
        properties.append(shade)


def _paragraph_style(paragraph, style, width):
    paragraph.alignment = {"left": WD_ALIGN_PARAGRAPH.LEFT, "center": WD_ALIGN_PARAGRAPH.CENTER,
                           "right": WD_ALIGN_PARAGRAPH.RIGHT}[style.align]
    paragraph.paragraph_format.space_after = Mm(style.spacing_mm)
    paragraph.paragraph_format.space_before = Mm(style.paragraph_before_mm)
    paragraph.paragraph_format.widow_control = True
    unused = width * (1 - style.width_percent / 100)
    paragraph.paragraph_format.left_indent = Mm(unused if style.align == "right" else unused / 2 if style.align == "center" else 0)
    paragraph.paragraph_format.right_indent = Mm(unused if style.align == "left" else unused / 2 if style.align == "center" else 0)
    props = paragraph._p.get_or_add_pPr()
    _shade(props, style.background)
    if style.border_pt:
        borders = OxmlElement("w:pBdr")
        for edge in ("top", "left", "bottom", "right"):
            border = OxmlElement(f"w:{edge}")
            for name, value in {"val": "single", "sz": str(round(style.border_pt * 8)), "color": style.color[1:]}.items():
                border.set(qn(f"w:{name}"), value)
            borders.append(border)
        props.append(borders)


def _text(paragraph, value, style):
    if "[[ASSETCORE_" in str(value):
        raise ValueError("studio_reserved_marker")
    return _literal_text(paragraph, value, style)


def _literal_text(paragraph, value, style):
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


def _table(container, rows, widths, style, width, repeat, keep_rows=False, group_headers=None, padding=None, min_height=None):
    table = _new_table(container, width, 0, len(widths))
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
        if min_height is not None:
            row.height, row.height_rule = Mm(min_height), WD_ROW_HEIGHT_RULE.AT_LEAST
        if padding is not None:
            for cell in row.cells:
                margin = OxmlElement("w:tcMar")
                for edge in ("top", "left", "bottom", "right"):
                    node = OxmlElement("w:" + edge)
                    node.set(qn("w:w"), str(round(padding / 25.4 * 1440)))
                    node.set(qn("w:type"), "dxa")
                    margin.append(node)
                cell._tc.get_or_add_tcPr().append(margin)
        if group_headers and index in group_headers:
            cell = row.cells[0].merge(row.cells[-1]) if len(row.cells) > 1 else row.cells[0]
            paragraph = cell.paragraphs[0]
            group_style = style.model_copy(update={"bold": True, "border_pt": 0})
            _paragraph_style(paragraph, group_style, actual_width)
            paragraph.paragraph_format.keep_with_next = True
            _text(paragraph, group_headers[index], group_style)
            _shade(cell._tc.get_or_add_tcPr(), style.background)
            row._tr.get_or_add_trPr().append(OxmlElement("w:cantSplit"))
            continue
        if index == 0 and repeat:
            row._tr.get_or_add_trPr().append(OxmlElement("w:tblHeader"))
        if index and keep_rows:
            row._tr.get_or_add_trPr().append(OxmlElement("w:cantSplit"))
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
            _shade(cell._tc.get_or_add_tcPr(), style.background)
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


def _new_table(container, width, rows, cols):
    from docx.section import _Footer, _Header
    if isinstance(container, (_Header, _Footer)):
        return container.add_table(rows=rows, cols=cols, width=Mm(width))
    return container.add_table(rows=rows, cols=cols)


def _grid(container, block, width, emit):
    if any(row.page_break_before for row in block.grid_rows):
        # Paragraph pageBreakBefore inside a table is ignored by converters.
        # Use native flow tables separated by a real body page break instead.
        segments, rows, force = [], [], False
        for row in block.grid_rows:
            if row.page_break_before:
                if rows:
                    segments.append((force, rows))
                force, rows = True, []
            rows.append(row.model_copy(update={"page_break_before": False}))
        if rows:
            segments.append((force, rows))
        for index, (page_break, rows) in enumerate(segments):
            if page_break:
                paragraph = container.add_paragraph()
                paragraph.paragraph_format.page_break_before = True
                paragraph.paragraph_format.keep_with_next = True
                paragraph.paragraph_format.space_after = Pt(0)
                paragraph.paragraph_format.line_spacing = Pt(1)
                paragraph.add_run().font.size = Pt(1)
            if index and block.repeat_rows:
                rows = list(block.grid_rows[:block.repeat_rows]) + rows
            _grid(container, block.model_copy(update={"grid_rows": rows, "keep_together": False}), width, emit)
        return
    width *= block.style.width_percent / 100
    table = _new_table(container, width, 0, len(block.widths))
    table.autofit = False
    table.alignment = {"left": WD_TABLE_ALIGNMENT.LEFT, "center": WD_TABLE_ALIGNMENT.CENTER, "right": WD_TABLE_ALIGNMENT.RIGHT}[block.style.align]
    _table_borders(table, block.style)
    _shade(table._tbl.tblPr, block.style.background)
    for column, percent in zip(table.columns, block.widths, strict=True):
        column.width = Mm(width * percent / 100)
    for i, definition in enumerate(block.grid_rows):
        row = table.add_row()
        row.height, row.height_rule = Mm(definition.min_height_mm), WD_ROW_HEIGHT_RULE.AT_LEAST
        props = row._tr.get_or_add_trPr()
        if i < block.repeat_rows:
            props.append(OxmlElement("w:tblHeader"))
        if definition.keep_together:
            props.append(OxmlElement("w:cantSplit"))
        # Set native grid column widths before merging, preserving the gridSpan.
        for c, percent in zip(row.cells, block.widths, strict=True):
            c.width = Mm(width * percent / 100)
        col = 0
        for item in definition.cells:
            cell = row.cells[col]
            if item.colspan > 1:
                cell = cell.merge(row.cells[col + item.colspan - 1])
            size = width * sum(block.widths[col:col + item.colspan]) / 100
            cell.width = Mm(size)
            cell.vertical_alignment = {"top": WD_CELL_VERTICAL_ALIGNMENT.TOP, "center": WD_CELL_VERTICAL_ALIGNMENT.CENTER, "bottom": WD_CELL_VERTICAL_ALIGNMENT.BOTTOM}[item.vertical_align]
            properties = cell._tc.get_or_add_tcPr()
            margin = OxmlElement("w:tcMar")
            for edge in ("top", "left", "bottom", "right"):
                node = OxmlElement("w:" + edge)
                node.set(qn("w:w"), str(round(item.padding_mm / 25.4 * 1440)))
                node.set(qn("w:type"), "dxa")
                margin.append(node)
            properties.append(margin)
            _shade(properties, item.style.background)
            borders = OxmlElement("w:tcBorders")
            for edge in ("top", "left", "bottom", "right"):
                node = OxmlElement("w:" + edge)
                for k,v in {"val": "single" if item.style.border_pt else "nil", "sz": str(max(1, round(item.style.border_pt * 8))), "color": item.style.color[1:]}.items():
                    node.set(qn("w:" + k),v)
                borders.append(node)
            properties.append(borders)
            # Retain a tiny required terminal paragraph; do not add blank lines
            # above every field/image/nested table.
            blank = cell.paragraphs[0]
            emit(cell, item.blocks, size - 2 * item.padding_mm)
            if item.blocks:
                blank._p.getparent().remove(blank._p)
            if not cell._tc[-1].tag.endswith("}p"):
                cell.add_paragraph()
            for p in cell.paragraphs:
                if not p.text and not p._p.xpath(".//w:drawing"):
                    p.paragraph_format.space_after = p.paragraph_format.space_before = Pt(0)
                    p.paragraph_format.line_spacing = Pt(1)
                    p.add_run().font.size = Pt(1)
                if block.keep_together and i < len(block.grid_rows) - 1:
                    p.paragraph_format.keep_with_next = True
            if definition.page_break_before:
                cell.paragraphs[0].paragraph_format.page_break_before = True
            col += item.colspan
    spacer = container.add_paragraph()
    spacer.paragraph_format.space_after = Mm(block.style.spacing_mm)
    spacer.paragraph_format.space_before = Pt(0)
    spacer.paragraph_format.line_spacing = Pt(1)
    spacer.add_run().font.size = Pt(1)


def render(manifest: dict, values: dict, tables: dict | None = None, *, source=False) -> bytes:
    layout = Layout.model_validate(manifest["layout"])
    if layout.native is not None:
        from .native_contract import render as render_native
        return render_native(manifest, values, tables, source=source)
    check_layout(layout, manifest["document_type"])
    if {str(b.image_id) for b in walk_blocks(layout.blocks) if b.type in {"image", "logo", "native_image"} and b.image_id is not None} != set(manifest["images"]):
        raise ValueError("studio_image_missing")
    document = Document()
    if layout.schema_version >= 3:
        normal = document.styles["Normal"]
        normal.font.name, normal.font.size = "Arial", Pt(9)
        normal.paragraph_format.space_after = Pt(0)
        normal.paragraph_format.line_spacing = 1
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
    section.top_margin = Mm(max(layout.page.margin_mm, layout.page.header_mm + 6))
    section.bottom_margin = Mm(max(layout.page.margin_mm, layout.page.footer_mm + 6))
    section.header_distance = section.footer_distance = Mm(3)
    width = page_width - 2 * layout.page.margin_mm
    identity = manifest["company"]["identity"]
    bindings = {**values, "COMPANY_NAME": identity["legal_name"],
        "COMPANY_ADDRESS": ", ".join(identity[k] for k in ("address", "city", "country") if identity[k]),
        "COMPANY_REGISTRATION": " · ".join(identity[k] for k in ("registration_number", "vat_number") if identity[k]),
        "COMPANY_CONTACTS": " · ".join(identity[k] for k in ("phone", "email", "website") if identity[k])}
    for region in ("header", "footer"):
        reserved = getattr(layout.page, region + "_mm") or layout.page.margin_mm - 6
        if sum(_height(b, width, bindings) for b in layout.blocks if b.region == region) > reserved:
            raise ValueError("studio_region_overflow")
    def emit(container, blocks, width):
        for block_index, block in enumerate(blocks):
            style = block.style
            if block.type == "grid":
                if style.paragraph_before_mm:
                    before = container.add_paragraph()
                    before.paragraph_format.line_spacing = Pt(1)
                    before.paragraph_format.space_after = Mm(style.paragraph_before_mm)
                _grid(container, block, width, emit)
                continue
            if block.type in {"table", "dynamic_table"}:
                group_headers = {}
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
                        if block.source == "EQUIPMENT_CHECKLIST":
                            displayed = {c.key for c in block.columns}
                            record["condition"] = " · ".join(str(v) for v in [record.get("condition"),
                                record.get("measurement") if "measurement" not in displayed else None,
                                record.get("note") if "note" not in displayed else None] if v is not None and str(v) != "")
                        if "quantity" in record and "unit" not in record:
                            amount, _, unit = str(record["quantity"]).partition(" ")
                            record["quantity"], record["unit"] = amount, unit
                        if "quantity" in record and not any(c.key == "unit" for c in block.columns):
                            record["quantity"] = " ".join(str(v) for v in (record["quantity"], record.get("unit")) if v is not None and str(v) != "")
                    rows = [[c.label for c in block.columns]]
                    previous_group = None
                    for record in records:
                        group = str(record.get(block.group_by) or "") if block.group_by else ""
                        if group and group != previous_group:
                            group_headers[len(rows)] = group
                            rows.append([group] + [""] * (len(block.columns) - 1))
                        previous_group = group
                        rows.append([record.get(c.key, "") for c in block.columns])
                _table(container, rows, widths, style, width, block.repeat_header, getattr(block, "keep_rows_together", False), group_headers, block.cell_padding_mm, block.min_height_mm)
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
                if block.show_identity:
                    _text(paragraph, " · ".join(str(bindings.get(f"{side}_{k}") or "") for k in ("SIGNER_NAME", "SIGNER_JOB_TITLE", "SIGNER_ORGANIZATION")), style)
                if block.label:
                    _text(paragraph, block.label, style)
                paragraph.paragraph_format.keep_with_next = True
                paragraph.paragraph_format.keep_together = True
                paragraph.paragraph_format.space_before = Mm(max(0, block.min_height_mm - 14) + style.paragraph_before_mm)
                marker = container.add_paragraph()
                _paragraph_style(marker, style, width)
                value = bindings.get(block.slot, "")
                if value in {"[[ASSETCORE_LEFT_SIGNATURE]]", "[[ASSETCORE_RIGHT_SIGNATURE]]"}:
                    _text(marker, "________________________", style)
                    _literal_text(marker, value, style).font.hidden = True
                else:
                    _text(marker, value, style)
                marker.paragraph_format.keep_together = True
                if block_index + 1 < len(blocks) and blocks[block_index + 1].type == "signature":
                    marker.paragraph_format.keep_with_next = True
            elif block.type in {"image", "logo", "native_image"}:
                if block.image_id is not None:
                    image = manifest["images"][str(block.image_id)]
                    paragraph.add_run().add_picture(io.BytesIO(base64.b64decode(image["content"])), width=Mm(block.width_mm), height=Mm(block.height_mm))
                else:
                    # A deliberately empty logo reserves space, never printable text.
                    paragraph.paragraph_format.line_spacing = Mm(block.height_mm)
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
                table = _new_table(container, block.width_mm, 1, 1)
                table.autofit = False
                table.columns[0].width = Mm(block.width_mm)
                table.rows[0].height, table.rows[0].height_rule = Mm(block.height_mm), WD_ROW_HEIGHT_RULE.AT_LEAST
                table.style = "Table Grid"
                _table_borders(table, style)
                table.alignment = {"left": WD_TABLE_ALIGNMENT.LEFT, "center": WD_TABLE_ALIGNMENT.CENTER, "right": WD_TABLE_ALIGNMENT.RIGHT}[style.align]
                cell = table.cell(0, 0)
                cell.width = Mm(block.width_mm)
                _shade(cell._tc.get_or_add_tcPr(), style.background)
                _paragraph_style(cell.paragraphs[0], style, block.width_mm)
                for border in list(cell.paragraphs[0]._p.get_or_add_pPr().findall(qn("w:pBdr"))):
                    cell.paragraphs[0]._p.pPr.remove(border)
                _text(cell.paragraphs[0], block.text, style)
                container.add_paragraph().paragraph_format.space_after = Mm(style.spacing_mm)
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
    for region in ("body", "header", "footer"):
        target = document if region == "body" else getattr(section, region)
        if region != "body" and layout.schema_version >= 3:
            initial = target.paragraphs[0]
            initial.paragraph_format.space_after = initial.paragraph_format.space_before = Pt(0)
            initial.paragraph_format.line_spacing = Pt(1)
            initial.add_run().font.size = Pt(1)
        emit(target, [b for b in layout.blocks if b.region == region], width)
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
    values["REQUEST_VARIANT"] = "MACHINE"
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
                    "REPAIR_EVENTS": [["", "", ""]] + [[r[0], r[1], r[2]] for r in rows],
                    "REPAIR_PARTICIPANTS": [{"name": word, "job_title": word, "contribution": word, "duration": "15 min"}],
                    "REPAIR_ATTACHMENTS": [], "EQUIPMENT_CHECKLIST": _synthetic_checklist(language)}


def _synthetic_checklist(language):
    # In-memory preview fixture only, from the canonical HPWJ vocabulary.
    from ..documents.transfer_documents import CHECKLIST
    return [{"position": str(i), "component": label, "condition": {"bg": "Синтетична проверка", "en": "Synthetic check", "ru": "Синтетическая проверка"}[language], "measurement": "", "note": ""}
        for i, label in enumerate(CHECKLIST[language], 1)]
