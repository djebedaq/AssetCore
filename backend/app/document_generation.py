"""Compatibility imports for the document generation API.

Implementations live in app.documents. Existing route/service/QA imports remain
valid; transaction ownership, templates and all document outputs are unchanged.
New code should import the owning domain module directly.
"""

from .documents.common import (
    ASSETS as ASSETS,
)
from .documents.common import (
    DOCX_MEDIA_TYPE as DOCX_MEDIA_TYPE,
)
from .documents.common import (
    PARTS_REFERENCE as PARTS_REFERENCE,
)
from .documents.common import (
    PDF_MEDIA_TYPE as PDF_MEDIA_TYPE,
)
from .documents.common import (
    REPAIR_REFERENCE as REPAIR_REFERENCE,
)
from .documents.common import (
    RESOURCES as RESOURCES,
)
from .documents.common import (
    TEXT as TEXT,
)
from .documents.common import (
    ConfirmedTemplateUnavailableError as ConfirmedTemplateUnavailableError,
)
from .documents.common import (
    _language as _language,
)
from .documents.common import (
    _reference_by_sha256 as _reference_by_sha256,
)
from .documents.common import (
    safe_filename as safe_filename,
)
from .documents.daily_report_documents import (
    build_daily_report_pdf as build_daily_report_pdf,
)
from .documents.part_request_documents import (
    _part_request_line_description as _part_request_line_description,
)
from .documents.part_request_documents import (
    _request_snapshot as _request_snapshot,
)
from .documents.part_request_documents import (
    build_part_request_docx as build_part_request_docx,
)
from .documents.part_request_documents import (
    build_part_request_pdf as build_part_request_pdf,
)
from .documents.part_request_documents import (
    make_part_request_documents as make_part_request_documents,
)
from .documents.registration import (
    _generated_documents as _generated_documents,
)
from .documents.registration import (
    _next_generated_number as _next_generated_number,
)
from .documents.registration import (
    _register_official_version as _register_official_version,
)
from .documents.rendering import (
    _add_centered as _add_centered,
)
from .documents.rendering import (
    _add_section_title as _add_section_title,
)
from .documents.rendering import (
    _clear_body as _clear_body,
)
from .documents.rendering import (
    _keep_with_next as _keep_with_next,
)
from .documents.rendering import (
    _pdf_header as _pdf_header,
)
from .documents.rendering import (
    _pdf_styles as _pdf_styles,
)
from .documents.rendering import (
    _pdf_table_style as _pdf_table_style,
)
from .documents.rendering import (
    _prepare_document as _prepare_document,
)
from .documents.rendering import (
    _register_pdf_fonts as _register_pdf_fonts,
)
from .documents.rendering import (
    _rina_image as _rina_image,
)
from .documents.rendering import (
    _set_cell as _set_cell,
)
from .documents.rendering import (
    _set_repeat_table_header as _set_repeat_table_header,
)
from .documents.rendering import (
    _set_run_font as _set_run_font,
)
from .documents.repair_documents import (
    make_repair_correction as make_repair_correction,
)
from .documents.repair_documents import (
    make_repair_documents as make_repair_documents,
)
from .documents.repair_rendering import (
    _build_repair_protocol_pdf_legacy as _build_repair_protocol_pdf_legacy,
)
from .documents.repair_rendering import (
    _repair_duration as _repair_duration,
)
from .documents.repair_rendering import (
    _repair_test_summary as _repair_test_summary,
)
from .documents.repair_rendering import (
    build_repair_protocol_docx as build_repair_protocol_docx,
)
from .documents.repair_rendering import (
    build_repair_protocol_pdf as build_repair_protocol_pdf,
)
from .documents.templates import (
    _preparer_values as _preparer_values,
)
from .documents.templates import (
    _signature_status as _signature_status,
)
from .documents.templates import (
    _template_version as _template_version,
)
from .documents.transfer_documents import (
    CHECKLIST as CHECKLIST,
)
from .documents.transfer_documents import (
    CHECKLIST_CODES as CHECKLIST_CODES,
)
from .documents.transfer_documents import (
    _build_protocol_docx as _build_protocol_docx,
)
from .documents.transfer_documents import (
    _build_protocol_pdf as _build_protocol_pdf,
)
from .documents.transfer_documents import (
    _checklist_rows as _checklist_rows,
)
from .documents.transfer_documents import (
    _equipment_text as _equipment_text,
)
from .documents.transfer_documents import (
    _identity_rows as _identity_rows,
)
from .documents.transfer_documents import (
    _machine_model as _machine_model,
)
from .documents.transfer_documents import (
    _protocol_remarks as _protocol_remarks,
)
from .documents.transfer_documents import (
    _protocol_snapshot as _protocol_snapshot,
)
from .documents.transfer_documents import (
    _protocol_template_values as _protocol_template_values,
)
from .documents.transfer_documents import (
    _return_findings as _return_findings,
)
from .documents.transfer_documents import (
    _usage_text as _usage_text,
)
from .documents.transfer_documents import (
    build_protocol_docx as build_protocol_docx,
)
from .documents.transfer_documents import (
    build_protocol_pdf as build_protocol_pdf,
)
from .documents.transfer_documents import (
    build_return_protocol_docx as build_return_protocol_docx,
)
from .documents.transfer_documents import (
    build_return_protocol_pdf as build_return_protocol_pdf,
)
from .documents.transfer_documents import (
    make_protocol_documents as make_protocol_documents,
)
from .documents.transfer_documents import (
    make_return_documents as make_return_documents,
)
from .template_engine import (
    TemplateValidationError as TemplateValidationError,
)
from .template_engine import (
    convert_docx_to_pdf as convert_docx_to_pdf,
)
from .template_engine import (
    render_docx as render_docx,
)
