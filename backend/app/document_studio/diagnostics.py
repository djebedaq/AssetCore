"""Read-only selection diagnostics and previews; no official ORM mutations."""
from __future__ import annotations

from sqlalchemy import select

from ..models import DocumentTemplate, DocumentTemplateVersion
from ..template_engine import render_docx, source_bytes
from .publication import active_selection
from .renderer import digest, inspect_pdf, pdf_required, synthetic_values


def configuration(db, document_type, language):
    from ..documents.common import ConfirmedTemplateUnavailableError
    from ..documents.templates import _template_version
    selected = active_selection(db, document_type, language)
    result = {"document_type": document_type, "language": language,
        "selection_kind": selected.selection_kind if selected else "LEGACY",
        "activation_revision": selected.revision if selected else 0,
        "selected_version_id": selected.version_id if selected else None,
        "programmatic_layout_versions": {"MACHINE": 3, "FREE_FORM": 2} if document_type == "PART_REQUEST" else None}
    try:
        version = _template_version(db, document_type, language)
        result.update(selected_version_id=version.id, template_id=version.template_id,
            source_version=version.version, source_sha256=version.source_sha256,
            actual_source_sha256=digest(source_bytes(version)), published_at=version.published_at,
            effective_from=version.effective_from, effective_to=version.effective_to,
            studio=bool(version.layout_contract.get("studio")),
            valid=version.source_sha256 == digest(source_bytes(version)))
    except (ConfirmedTemplateUnavailableError, ValueError, OSError):
        result.update(valid=False, error_code="studio_activation_invalid")
    candidates = db.scalars(select(DocumentTemplateVersion).join(DocumentTemplate).where(
        DocumentTemplate.document_type == document_type, DocumentTemplateVersion.language == language))
    result["legacy_candidates"] = [{"id": v.id, "template_id": v.template_id, "source_version": v.version,
        "source_sha256": v.source_sha256, "is_published": v.is_published,
        "validation_status": v.validation_status, "effective_from": v.effective_from,
        "effective_to": v.effective_to} for v in candidates if not v.layout_contract.get("studio")]
    return result


def request_sample(language, count, request_variant):
    from ..documents import company_header
    from ..documents.request_issue_documents import _studio_rows, _studio_values
    values, _ = synthetic_values(language, count)
    machine = None if request_variant == "FREE_FORM" else {"name": values["MACHINE_NAME"],
        "inventory_number": values["MACHINE_NUMBER"], "brand": values["BRAND"], "model": values["MODEL"],
        "serial_number": values["SERIAL_NUMBER"], "pressure_bar": None, "batch_reference": None}
    data = {"request_kind": "FREE_FORM" if machine is None else "CATALOG", "language": language,
        "document_layout_version": 2 if machine is None else 3, "machine": machine,
        "company_header": company_header.manifest(), "official_number": "PREVIEW",
        "approved_at": "2026-01-01T12:00:00+00:00", "department": values["DEPARTMENT"],
        "requested_by_name": values["REQUESTER_NAME"], "approved_by_name": values["APPROVER_NAME"],
        "reason": values["REMARKS"], "repair_reference": None,
        "prepared_by": {"display_name": values["PREPARER_NAME"], "job_title": values["PREPARER_JOB_TITLE"]},
        "lines": [{"position": str(i), "part_number": "" if machine is None else f"SYNTHETIC-{i}",
            "linked_part_number": None, "description": f"SYNTHETIC QA ONLY {i}",
            "quantity": "0.75" if machine is None else "1", "unit": "kg" if machine is None else "pcs"}
            for i in range(1, count + 1)]}
    return data, {**_studio_values(data), "REQUEST_VARIANT": request_variant}, {"REQUEST_LINES": _studio_rows(data)}


def legacy_preview(version, count=5, request_variant="MACHINE", *, raster=True):
    from .files import validate_docx
    validate_docx(source_bytes(version))
    typ, language = version.template.document_type, version.language
    if typ == "PART_REQUEST":
        from ..documents.request_issue_documents import build_docx
        data, _, _ = request_sample(language, count, request_variant)
        docx = build_docx(data, source_bytes(version))
    else:
        from ..documents.common import TEXT
        values, tables = synthetic_values(language, count)
        values["CONDITION_LABEL"] = TEXT[language]["overall_condition"]
        for i, row in enumerate(tables["EQUIPMENT_CHECKLIST"], 1):
            values[f"CHECK_{i}"] = row["condition"]
        from .native_contract import HEADERS
        for code, labels in HEADERS.items():
            if tables[code] and isinstance(tables[code][0], dict):
                from .native_contract import KEYS
                tables[code] = [list(labels)] + [[r.get(k, "") for k in KEYS[code]] for r in tables[code]]
            else:
                tables[code] = [list(labels)] + tables[code][1:] if tables[code] else [list(labels)]
        docx = render_docx(version, values, tables)
    pdf = pdf_required(docx)
    return docx, pdf, {**inspect_pdf(pdf, raster=raster), "docx_sha256": digest(docx),
                       "rows": count, "request_variant": request_variant, "renderer": "LEGACY"}
