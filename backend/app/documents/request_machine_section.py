"""Optional machine specifications in the shared requests document layout."""

from docx.enum.table import WD_CELL_VERTICAL_ALIGNMENT, WD_ROW_HEIGHT_RULE, WD_TABLE_ALIGNMENT
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Mm

from .part_request_documents import REQUEST_META_LABELS


def snapshot(machine):
    """Capture machine values; an explicitly named custom batch is never a transfer batch."""
    data = {
        key: getattr(machine, key)
        for key in ("name", "inventory_number", "brand", "model", "serial_number", "pressure_bar")
    }
    data["batch_reference"] = None
    # This is an optional operator-defined machine field, not an inferred history value.
    for value in machine.custom_values:
        field = value.field
        if (
            field.is_active
            and field.category_id == machine.category_id
            and field.code.lower() == "batch_reference"
        ):
            data["batch_reference"] = value.value
            data["batch_reference_source"] = {"field_id": field.id, "code": field.code}
            break
    return data


def rows(machine, language):
    labels = REQUEST_META_LABELS[language]

    def value(key):
        return str(machine[key]) if machine.get(key) is not None else ""

    pressure = machine.get("pressure_bar")
    return [
        [labels[0], value("name"), labels[1], value("inventory_number")],
        [labels[2], value("brand"), labels[3], value("model")],
        [
            labels[4],
            value("serial_number"),
            labels[5],
            f"{pressure:g} bar" if pressure is not None else "",
        ],
        [labels[6], value("batch_reference"), "", ""],
    ]


def add_docx(document, machine, language, *, paragraph_style, borders):
    """Reusable optional section; inherit typography and borders from the request layout."""
    table = document.add_table(rows=0, cols=4)
    table.alignment, table.autofit = WD_TABLE_ALIGNMENT.CENTER, False
    section = document.sections[0]
    width = (section.page_width - section.left_margin - section.right_margin) // 4
    for column in table.columns:
        column.width = width
    borders(table)
    for values in rows(machine, language):
        row = table.add_row()
        row.height, row.height_rule = Mm(7), WD_ROW_HEIGHT_RULE.AT_LEAST
        row._tr.get_or_add_trPr().append(OxmlElement("w:cantSplit"))
        for index, (cell, text) in enumerate(zip(row.cells, values, strict=True)):
            cell.width, cell.text = width, text
            cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
            shade = OxmlElement("w:shd")
            shade.set(qn("w:fill"), "FFFFFF")
            cell._tc.get_or_add_tcPr().append(shade)
            paragraph = cell.paragraphs[0]
            paragraph_style(paragraph, size=10)
            if index % 2 == 0:
                for run in paragraph.runs:
                    run.bold = True
    return table
