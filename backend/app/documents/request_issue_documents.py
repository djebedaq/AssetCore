"""KK documents rendered exclusively from the approval snapshot."""

import hashlib
import io
from datetime import datetime
from types import SimpleNamespace
from xml.sax.saxutils import escape
from zoneinfo import ZoneInfo

from docx import Document
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.oxml.ns import qn
from docx.shared import Mm, Pt, RGBColor
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.platypus import Image, Paragraph, SimpleDocTemplate, Spacer, Table
from sqlalchemy import select

from ..audit import add_audit_log
from ..models import DocumentType, GeneratedDocument, PartVisualArtifact
from ..part_requests.official import canonical_hash, capture_data
from ..template_engine import source_bytes
from . import company_header, request_layout_v2
from .part_request_documents import OFFICIAL_HEADER, _part_request_line_description
from .part_request_grouped_visuals import (
    append_docx,
    appendix_manifest,
    pdf_flowables,
    prepare_appendix,
)
from .registration import _generated_documents, _register_official_version
from .rendering import (
    _clear_body,
    _pdf_styles,
    _pdf_table_style,
    _set_cell,
    _set_repeat_table_header,
)
from .templates import _template_version

LABELS = {
    "bg": ("Отдел", "Заявител", "Основание", "ПРОЕКТ — НЕОДОБРЕНА ЗАЯВКА"),
    "en": ("Department", "Requester", "Reason", "DRAFT — UNAPPROVED REQUEST"),
    "ru": ("Отдел", "Заявитель", "Основание", "ПРОЕКТ — НЕУТВЕРЖДЁННАЯ ЗАЯВКА"),
}
UNIT_LABELS = {
    "bg": {
        "pcs": "бр.",
        "m": "м",
        "l": "л",
        "kg": "кг",
        "g": "г",
        "m2": "м²",
        "m3": "м³",
        "set": "компл.",
        "pair": "чифт",
    },
    "en": {
        "pcs": "pcs",
        "m": "m",
        "l": "l",
        "kg": "kg",
        "g": "g",
        "m2": "m²",
        "m3": "m³",
        "set": "set",
        "pair": "pair",
    },
    "ru": {
        "pcs": "шт.",
        "m": "м",
        "l": "л",
        "kg": "кг",
        "g": "г",
        "m2": "м²",
        "m3": "м³",
        "set": "компл.",
        "pair": "пара",
    },
}


def _rows(data):
    free = data["request_kind"] == "FREE_FORM"
    rows = [
        ["Pos", "DESCRIPTION", "Q'TY ordered"]
        if free
        else ["Pos", "PART No", "DESCRIPTION", "Q'TY ordered"]
    ]
    for index, line in enumerate(data["lines"], 1):
        unit = UNIT_LABELS[data["language"]].get(line["unit"], line["unit"] or "")
        amount = (
            line["quantity"].replace(".", ",") if data["language"] != "en" else line["quantity"]
        )
        values = [str(index) if free else line["position"] or str(index)]
        if not free:
            values.append(line["part_number"] or line["linked_part_number"] or "")
        description = line["description"]
        if not free and line.get("is_unknown_part"):
            linked = (
                SimpleNamespace(part_number=line["linked_part_number"])
                if line.get("linked_part_number")
                else None
            )
            description = _part_request_line_description(
                SimpleNamespace(**{**line, "linked_catalog_part": linked}), data["language"]
            )
        values.extend([description, f"{amount} {unit}".strip()])
        rows.append(values)
    return rows


def _date(data):
    value = data.get("approved_at")
    return (
        datetime.fromisoformat(value).astimezone(ZoneInfo("Europe/Sofia")).strftime("%d/%m/%Y")
        if value
        else ""
    )


def _meta(data):
    department, requester, reason, _ = LABELS[data["language"]]
    result = [
        f"{department}: {data.get('department') or ''}",
        f"{requester}: {data.get('requested_by_name') or ''}",
    ]
    if data.get("machine") and data.get("document_layout_version") != 3:
        m = data["machine"]
        result.append(
            " · ".join(
                str(m[k])
                for k in ("name", "inventory_number", "brand", "model", "serial_number")
                if m.get(k)
            )
        )
    if data.get("repair_reference"):
        result.append(data["repair_reference"])
    if data.get("reason"):
        result.append(f"{reason}: {data['reason']}")
    return result


def build_docx(data, template_content, appendix=None, *, header_content=None, resources=None):
    from ..document_studio.renderer import manifest_from_source, render_source
    manifest = manifest_from_source(template_content) if template_content else None
    if manifest:
        if manifest["document_type"] != "PART_REQUEST" or manifest["language"] != data["language"]:
            raise ValueError("studio_source_invalid")
        from ..document_studio.native_contract import variant
        from ..document_studio.schemas import supports_request_variants
        selected_variant = variant(data)
        if not supports_request_variants(manifest["layout"]):
            # Existing Studio sources have no verified free/machine contract.
            # Preserve their history but refuse an incompatible free request.
            if selected_variant == "FREE_FORM":
                raise ValueError("studio_request_variant_mismatch")
        rendered = render_source(template_content, {**_studio_values(data), "REQUEST_VARIANT": selected_variant}, {"REQUEST_LINES": _studio_rows(data)})
        return append_docx(rendered, appendix, data["language"]) if appendix else rendered
    if data.get("document_layout_version") not in (None, 1, 2, 3):
        raise ValueError("unsupported_request_document_layout_version")
    if data.get("document_layout_version") in (2, 3):
        resources = resources if resources is not None else company_header.current_resources()
        company_header.verify(resources, data["company_header"])
        return request_layout_v2.build_docx(
            data,
            template_content,
            rows=_rows(data),
            meta=_meta(data),
            date=_date(data),
            resources=resources,
            appendix=appendix,
            machine_section=data.get("machine") if data["document_layout_version"] == 3 else None,
        )
    return _legacy_build_docx(data, template_content, appendix, header_content=header_content)


def _legacy_build_docx(data, template_content, appendix=None, *, header_content=None):
    document = Document(io.BytesIO(template_content))
    _clear_body(document)
    section = document.sections[0]
    section.page_width, section.page_height = Mm(210), Mm(297)
    section.left_margin = section.right_margin = Mm(11)
    section.top_margin, section.bottom_margin = Mm(41), Mm(15)
    section.header_distance = Mm(8)
    document.settings.odd_and_even_pages_header_footer = False
    section.different_first_page_header_footer = False
    section.header.is_linked_to_previous = False
    for child in list(section.header._element):
        section.header._element.remove(child)
    header = section.header.add_paragraph()
    header.alignment = 1
    header.paragraph_format.space_after = Pt(0)
    header.add_run().add_picture(
        io.BytesIO(header_content or OFFICIAL_HEADER.read_bytes()), width=Mm(188), height=Mm(27)
    )
    style = document.styles["Normal"]
    style.font.name, style.font.size = "Arial", Pt(9)
    title_style = document.styles["Title"]
    title_style.font.color.rgb = RGBColor(0, 0, 0)
    if title_style.element.pPr is not None:
        for border in list(title_style.element.pPr.findall(qn("w:pBdr"))):
            title_style.element.pPr.remove(border)
    p = document.add_paragraph("TECHNICAL SPECIFICATION\nFOR SPARE PARTS SUPPLY", "Title")
    p.alignment = 1
    for border in list(p._p.get_or_add_pPr().findall(qn("w:pBdr"))):
        p._p.get_or_add_pPr().remove(border)
    p.paragraph_format.keep_with_next = True
    p.paragraph_format.space_after = Pt(11)
    for run in p.runs:
        run.font.name, run.font.size, run.bold = "Arial", Pt(10.5), True
    for text in _meta(data):
        document.add_paragraph(text)
    rows = _rows(data)
    widths = [14, 140, 34] if len(rows[0]) == 3 else [14, 35, 105, 34]
    table = document.add_table(rows=0, cols=len(widths))
    table.style, table.alignment, table.autofit = "Table Grid", WD_TABLE_ALIGNMENT.CENTER, False
    for row_index, values in enumerate(rows):
        cells = table.add_row().cells
        for col, value in enumerate(values):
            cells[col].width = Mm(widths[col])
            _set_cell(cells[col], value, size=9, bold=row_index == 0)
    for col, width in zip(table.columns, widths, strict=True):
        col.width = Mm(width)
    _set_repeat_table_header(table.rows[0])
    document.add_paragraph(f"ENQ №: {data.get('official_number') or ''}      DATE: {_date(data)}")
    document.add_paragraph(data.get("approved_by_name") or "")
    output = io.BytesIO()
    document.save(output)
    return (
        append_docx(output.getvalue(), appendix, data["language"])
        if appendix
        else output.getvalue()
    )


def build_pdf(
    data, appendix=None, *, preview=False, header_content=None, resources=None, docx=None
):
    if data.get("studio_source"):
        from ..document_studio.renderer import pdf_required
        if docx is None:
            raise ValueError("studio_source_invalid")
        return pdf_required(docx)
    if data.get("document_layout_version") not in (None, 1, 2, 3):
        raise ValueError("unsupported_request_document_layout_version")
    if data.get("document_layout_version") in (2, 3):
        docx = docx if docx is not None else build_docx(data, None, appendix, resources=resources)
        return request_layout_v2.build_pdf(
            data,
            docx,
            preview=preview,
            watermark=LABELS[data["language"]][3],
        )
    return _legacy_build_pdf(data, appendix, preview=preview, header_content=header_content)


def _legacy_build_pdf(data, appendix=None, *, preview=False, header_content=None):
    _, _, body, label, title, small = _pdf_styles()
    output = io.BytesIO()
    pdf = SimpleDocTemplate(
        output,
        pagesize=A4,
        leftMargin=11 * mm,
        rightMargin=11 * mm,
        topMargin=10 * mm,
        bottomMargin=15 * mm,
        title=data.get("official_number") or "Request preview",
        author="AssetCore",
    )
    story = [
        Image(
            io.BytesIO(header_content or OFFICIAL_HEADER.read_bytes()),
            width=188 * mm,
            height=27 * mm,
        ),
        Spacer(1, 4 * mm),
        Paragraph("TECHNICAL SPECIFICATION<br/>FOR SPARE PARTS SUPPLY", title),
        Spacer(1, 4 * mm),
    ]
    story.extend(Paragraph(escape(text), body) for text in _meta(data))
    story.append(Spacer(1, 3 * mm))
    rows = _rows(data)
    widths = [14, 140, 34] if len(rows[0]) == 3 else [14, 35, 105, 34]
    table = Table(
        [
            [Paragraph(escape(value), label if i == 0 else small) for value in row]
            for i, row in enumerate(rows)
        ],
        colWidths=[w * mm for w in widths],
        repeatRows=1,
        splitByRow=1,
        splitInRow=1,
    )
    table.setStyle(_pdf_table_style(header_rows=1))
    story.extend(
        [
            table,
            Spacer(1, 4 * mm),
            Paragraph(
                escape(f"ENQ №: {data.get('official_number') or ''}     DATE: {_date(data)}"), body
            ),
            Paragraph(escape(data.get("approved_by_name") or ""), body),
        ]
    )
    if appendix:
        story.extend(pdf_flowables(appendix, data["language"]))

    def decorate(canvas, _doc):
        if preview:
            canvas.saveState()
            canvas.setFillColorRGB(0.65, 0.15, 0.15)
            canvas.setFillAlpha(0.25)
            canvas.setFont(body.fontName, 22)
            canvas.translate(105 * mm, 148 * mm)
            canvas.rotate(38)
            canvas.drawCentredString(0, 0, LABELS[data["language"]][3])
            canvas.restoreState()

    pdf.build(story, onFirstPage=decorate, onLaterPages=decorate)
    return output.getvalue()


def _appendix(db, request, data):
    if data["request_kind"] == "FREE_FORM":
        return None
    live_lines = {line.id: line for line in request.lines}
    frozen = []
    for line in data["lines"]:
        live = live_lines[line["id"]]
        if (live.visual_snapshot.sha256 if live.visual_snapshot else None) != line["visual_sha256"]:
            raise ValueError("approval_visual_integrity_failed")
        frozen.append(
            SimpleNamespace(
                **{
                    **line,
                    "visual_snapshot": live.visual_snapshot,
                    "catalog_part": None,
                    "linked_catalog_part": None,
                }
            )
        )
    return prepare_appendix(db, SimpleNamespace(lines=frozen))


def preview_pdf(db, request):
    data = capture_data(request)
    data.update(official_number=None, approved_at=None, approved_by_name=None)
    template = _template_version(db, DocumentType.PART_REQUEST.value, request.language)
    content = source_bytes(template)
    appendix = _appendix(db, request, data)
    docx = build_docx(data, content, appendix)
    # One native print layout; the draft watermark is the only PDF overlay.
    return request_layout_v2.build_pdf(data, docx, preview=True, watermark=LABELS[data["language"]][3])


def archive(db, request, actor):
    snapshot = request.approval_snapshot
    if canonical_hash(snapshot.data) != snapshot.sha256:
        raise ValueError("approval_snapshot_integrity_failed")
    prepared = snapshot.data.get("prepared_by", {})
    if not (
        prepared.get("first_name")
        and prepared.get("last_name")
        and prepared.get("job_title")
    ):
        raise ValueError("approval_preparer_profile_incomplete")
    existing = list(
        db.scalars(select(GeneratedDocument).where(GeneratedDocument.part_request_id == request.id))
    )
    if existing:
        if (
            {d.format for d in existing} != {"pdf", "docx"}
            or len(existing) != 2
            or any(
                d.document_number != snapshot.official_number
                or hashlib.sha256(d.content).hexdigest() != d.sha256
                for d in existing
            )
        ):
            raise ValueError("request_archive_integrity_failed")
        return existing
    if not snapshot.template_version_id or not snapshot.template_content or not snapshot.data.get("template_sha256"):
        raise ValueError("approval_template_evidence_missing")
    template_id = snapshot.template_version_id
    content = snapshot.template_content
    if (
        snapshot.data["template_sha256"]
        and hashlib.sha256(content).hexdigest() != snapshot.data["template_sha256"]
    ):
        raise ValueError("approval_template_integrity_failed")
    appendix = _appendix(db, request, snapshot.data)
    header = db.get(PartVisualArtifact, snapshot.data["header_image_sha256"])
    if (
        header is None
        or header.byte_length != len(header.content)
        or hashlib.sha256(header.content).hexdigest() != header.sha256
    ):
        raise ValueError("approval_header_integrity_failed")
    document_snapshot = {**snapshot.data, "approval_snapshot_sha256": snapshot.sha256}
    if appendix is not None:
        document_snapshot["visual_appendix"] = appendix_manifest(appendix)
    resources = None
    if snapshot.data.get("document_layout_version") in (2, 3):
        resources = {}
        for name, evidence in snapshot.data["company_header"]["parts"].items():
            resource = db.get(PartVisualArtifact, evidence["sha256"])
            if resource is None or resource.byte_length != len(resource.content):
                raise ValueError("approval_company_header_integrity_failed")
            resources[name] = resource.content
        company_header.verify(resources, snapshot.data["company_header"])
    docx = build_docx(
        snapshot.data, content, appendix, header_content=header.content, resources=resources
    )
    from ..document_studio.renderer import manifest_from_source
    pdf = build_pdf(
        {**snapshot.data, "studio_source": manifest_from_source(content) is not None}, appendix, header_content=header.content, resources=resources, docx=docx
    )
    _register_official_version(
        db,
        number=snapshot.official_number,
        document_type=DocumentType.PART_REQUEST.value,
        language=snapshot.data["language"],
        docx=docx,
        pdf=pdf,
        snapshot=document_snapshot,
        created_by_id=snapshot.approved_by_id,
        machine_id=request.machine_id,
        template_version_id=template_id,
        prepared_by_snapshot=snapshot.data.get("prepared_by"),
    )
    documents = _generated_documents(
        number=snapshot.official_number,
        document_type=DocumentType.PART_REQUEST.value,
        language=snapshot.data["language"],
        template_version=SimpleNamespace(id=template_id),
        docx=docx,
        pdf=pdf,
        snapshot=document_snapshot,
        created_by_id=snapshot.approved_by_id,
        machine_id=request.machine_id,
        part_request_id=request.id,
    )
    db.add_all(documents)
    db.flush()
    add_audit_log(
        db,
        actor,
        "part_request",
        request.id,
        "REQUEST_DOCUMENTS_ARCHIVED",
        {
            "official_number": snapshot.official_number,
            "sha256": {d.format: d.sha256 for d in documents},
        },
    )
    return documents


def _studio_values(data):
    from ..localization import status_label
    from .templates import _signature_status
    machine = data.get("machine") or {}
    prepared = data.get("prepared_by") or {}
    return {"DOCUMENT_NUMBER": data.get("official_number") or "", "CREATION_DATE": _date(data),
        "MACHINE_NAME": machine.get("name") or "", "MACHINE_NUMBER": machine.get("inventory_number") or "",
        "BRAND": machine.get("brand") or "", "MODEL": machine.get("model") or "",
        "SERIAL_NUMBER": machine.get("serial_number") or "", "PRESSURE_BAR": machine.get("pressure_bar") if machine.get("pressure_bar") is not None else "",
        "EQUIPMENT_TYPE": (data.get("studio_machine_context") or {}).get("category") or "",
        "MACHINE_LOCATION": (data.get("studio_machine_context") or {}).get("location") or "",
        "BATCH_REFERENCE": machine.get("batch_reference") or "", "CONDITION_TEXT": "", "USAGE_TEXT": "",
        "MANUFACTURER": (data.get("studio_machine_context") or {}).get("manufacturer") or machine.get("brand") or "",
        "MODEL_DISPLAY": " ".join(str(machine.get(k) or "") for k in ("brand", "model")).strip(),
        "LEFT_SIGNER_ROLE": "", "RIGHT_SIGNER_ROLE": "",
        "LEFT_SIGNER_ORGANIZATION": data.get("department") or "", "RIGHT_SIGNER_ORGANIZATION": "",
        "CATALOG_REFERENCES": "; ".join(dict.fromkeys(str(line.get("source_document") or "") for line in data.get("lines", []) if line.get("source_document"))),
        "PREPARER_NAME": prepared.get("display_name") or "", "PREPARER_JOB_TITLE": prepared.get("job_title") or "",
        "SIGNATURE_STATUS": _signature_status(data["language"]), "LEFT_SIGNATURE": "[[ASSETCORE_LEFT_SIGNATURE]]",
        "RIGHT_SIGNATURE": "[[ASSETCORE_RIGHT_SIGNATURE]]",
        "LEFT_SIGNER_NAME": data.get("requested_by_name") or "", "LEFT_SIGNER_JOB_TITLE": data.get("requested_by_job_title") or "",
        "RIGHT_SIGNER_NAME": data.get("approved_by_name") or "", "RIGHT_SIGNER_JOB_TITLE": data.get("approved_by_job_title") or "",
        "REQUESTER_NAME": data.get("requested_by_name") or "", "APPROVER_NAME": data.get("approved_by_name") or "",
        "DEPARTMENT": data.get("department") or "", "APPROVAL_DATE": _date(data),
        "REPAIR_REFERENCE": data.get("repair_reference") or "",
        "REMARKS": data.get("reason") or "", "DECISION": data.get("decision_note") or status_label(data.get("status") or "APPROVED", data["language"])}


def _studio_rows(data):
    localized = _rows(data)[1:]
    return [{"position": row[0], "part_number": "" if data["request_kind"] == "FREE_FORM" else row[1],
             "description": row[-2], "quantity": row[-1].partition(" ")[0],
             "unit": UNIT_LABELS[data["language"]].get(line["unit"], line["unit"] or ""),
             "note": line.get("note") or "", "assembly": line.get("assembly") or ""} for row, line in zip(localized, data["lines"], strict=True)]


def generate_safely(db, request, actor):
    """A rendering failure rolls back only its savepoint, never the issued approval."""
    try:
        with db.begin_nested():
            documents = archive(db, request, actor)
        request.generation_status, request.generation_error = "READY", None
        return documents
    except Exception:
        # Exception messages can contain paths or document contents. Persist only a stable code.
        request.generation_status, request.generation_error = (
            "FAILED",
            "request_document_generation_failed",
        )
        add_audit_log(
            db,
            actor,
            "part_request",
            request.id,
            "REQUEST_DOCUMENT_GENERATION_FAILED",
            {"official_number": request.approval_snapshot.official_number},
        )
        return []
