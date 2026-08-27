"""Document extraction contracts; all samples use the existing isolated QA database.

The golden file was captured before extraction. DOCX member hashes include every
XML/media part, excluding only the ZIP container's non-deterministic timestamps.
PDF byte hashes are checked against the actual registered bytes, not cross-OS
goldens (installed fonts and LibreOffice metadata are environment-dependent).
"""

from __future__ import annotations

import hashlib
import importlib
import io
import json
import zipfile
from datetime import datetime
from pathlib import Path

import pytest
from app import document_generation as compatibility
from app.models import DocumentTemplateVersion, OfficialDocument, OfficialDocumentVersion
from reportlab import rl_config
from sqlalchemy import DateTime, event, inspect, select
from sqlalchemy.orm import Session

from scripts import document_qa

FIXED_TIME = datetime(2026, 8, 27, 10, 30)
GOLDEN = Path(__file__).parent / "fixtures" / "document_generation_baseline.json"
BUILDERS = {
    "issue": "make_protocol_documents",
    "return": "make_return_documents",
    "repair": "make_repair_documents",
    "part_request": "make_part_request_documents",
}


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _json_sha(value: object) -> str:
    return _sha(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode("utf-8")
    )


def _docx_members(content: bytes) -> dict[str, str]:
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        return {name: _sha(archive.read(name)) for name in sorted(archive.namelist())}


def _generate_isolated_qa(monkeypatch, output: Path) -> dict:
    # The standalone QA script fills missing bootstrap settings for its own
    # process. Embedded in pytest, those defaults must not leak to later tests.
    with monkeypatch.context() as scoped:
        for name in ("owner_email", "owner_job_title", "owner_initial_password"):
            scoped.setattr(document_qa.settings, name, getattr(document_qa.settings, name))
        return document_qa.generate(output)


def _check_version(document, version, records) -> None:
    by_format = {record.format: record for record in records}
    assert set(by_format) == {"docx", "pdf"}
    for record in records:
        assert record.sha256 == _sha(record.content)
    assert version.docx_content == by_format["docx"].content
    assert version.pdf_content == by_format["pdf"].content
    assert version.docx_sha256 == by_format["docx"].sha256
    assert version.pdf_sha256 == by_format["pdf"].sha256
    assert version.snapshot_sha256 == _json_sha(version.snapshot)
    assert version.signing_sha256 == _json_sha(
        {
            "document_number": document.document_number,
            "document_type": document.document_type,
            "snapshot_sha256": version.snapshot_sha256,
            "docx_sha256": version.docx_sha256,
            "pdf_sha256": version.pdf_sha256,
            "version": version.version,
        }
    )


def collect_generation_evidence(monkeypatch, output: Path, language: str) -> dict:
    """Exercise real templates, builders, registration and fallback PDF rendering."""
    evidence = {}

    def fixed_defaults(db, *_args):
        # Freeze only the isolated fixture's model defaults, never production code.
        for instance in db.new:
            for column in inspect(type(instance)).columns:
                if (
                    isinstance(column.type, DateTime)
                    and column.default is not None
                    and getattr(instance, column.key) is None
                ):
                    setattr(instance, column.key, FIXED_TIME)

    monkeypatch.setattr(document_qa, "utcnow", lambda: FIXED_TIME)
    registration = importlib.import_module(compatibility._register_official_version.__module__)
    monkeypatch.setattr(registration, "utcnow", lambda: FIXED_TIME)
    monkeypatch.setattr(rl_config, "invariant", 1)

    for kind, name in BUILDERS.items():
        builder = getattr(compatibility, name)
        owner = importlib.import_module(builder.__module__)
        # Deliberately test the real fallback regardless of host LibreOffice setup.
        monkeypatch.setattr(owner, "convert_docx_to_pdf", lambda _docx: None)

        def capture(db, *args, _builder=builder, _kind=kind):
            def forbidden_commit():
                pytest.fail("Document builders must leave transaction ownership to the caller")

            with monkeypatch.context() as scoped:
                scoped.setattr(db, "commit", forbidden_commit)
                records = _builder(db, *args[:-1], language)
            document = db.scalar(
                select(OfficialDocument).where(
                    OfficialDocument.document_number == records[0].document_number,
                )
            )
            version = db.get(OfficialDocumentVersion, document.current_version_id)
            _check_version(document, version, records)
            template = db.get(DocumentTemplateVersion, version.template_version_id)
            evidence[_kind] = {
                "number": document.document_number,
                "type": document.document_type,
                "language": version.language,
                "version": version.version,
                "status": version.status,
                "template_version": template.version,
                "template_sha256": template.source_sha256,
                "snapshot_sha256": version.snapshot_sha256,
                "record_snapshot_sha256": _json_sha(records[0].snapshot),
                "filenames": {record.format: record.filename for record in records},
                "media_types": {record.format: record.media_type for record in records},
                "docx_members": _docx_members(version.docx_content),
            }
            return records

        monkeypatch.setattr(document_qa, name, capture)

    event.listen(Session, "before_flush", fixed_defaults)
    try:
        _generate_isolated_qa(monkeypatch, output)
    finally:
        event.remove(Session, "before_flush", fixed_defaults)
    return evidence


@pytest.mark.parametrize("language", ["bg", "en", "ru"])
def test_canonical_builders_preserve_pre_extraction_output(monkeypatch, tmp_path, language):
    expected = json.loads(GOLDEN.read_text(encoding="utf-8"))["languages"][language]
    assert collect_generation_evidence(monkeypatch, tmp_path, language) == expected


@pytest.mark.parametrize("kind", BUILDERS)
def test_pdf_converter_receives_exact_registered_docx(monkeypatch, tmp_path, kind):
    builder = getattr(compatibility, BUILDERS[kind])
    owner = importlib.import_module(builder.__module__)
    original_fallback = {
        "issue": compatibility.build_protocol_pdf,
        "return": compatibility.build_return_protocol_pdf,
        "repair": compatibility.build_repair_protocol_pdf,
        "part_request": compatibility.build_part_request_pdf,
    }[kind]
    seen = []

    def capture(db, *args):
        # An actual fallback PDF is used as the converter result; the contract here
        # is byte transport, not a substitute for the separate LibreOffice tests.
        pdf = (
            original_fallback(args[0], args[1].batch_reference, "bg")
            if kind in {"issue", "return"}
            else original_fallback(args[0], "bg")
        )

        def converter(docx):
            seen.append(docx)
            return pdf

        with monkeypatch.context() as scoped:
            scoped.setattr(owner, "convert_docx_to_pdf", converter)
            scoped.setattr(
                owner,
                original_fallback.__name__,
                lambda *_a, **_k: pytest.fail(
                    "Fallback must not run after successful conversion",
                ),
            )
            records = builder(db, *args)
        by_format = {record.format: record.content for record in records}
        assert seen == [by_format["docx"]]
        assert by_format["pdf"] == pdf
        return records

    monkeypatch.setattr(document_qa, BUILDERS[kind], capture)
    _generate_isolated_qa(monkeypatch, tmp_path)
    assert len(seen) == 1


COMPATIBILITY_EXPORTS = {
    "common": (
        "DOCX_MEDIA_TYPE",
        "PDF_MEDIA_TYPE",
        "ConfirmedTemplateUnavailableError",
        "RESOURCES",
        "ASSETS",
        "_reference_by_sha256",
        "REPAIR_REFERENCE",
        "PARTS_REFERENCE",
        "TEXT",
        "safe_filename",
        "_language",
    ),
    "rendering": (
        "_set_run_font",
        "_keep_with_next",
        "_set_repeat_table_header",
        "_set_cell",
        "_clear_body",
        "_prepare_document",
        "_add_centered",
        "_register_pdf_fonts",
        "_rina_image",
        "_pdf_styles",
        "_pdf_header",
        "_pdf_table_style",
        "_add_section_title",
    ),
    "templates": (
        "_template_version",
        "_preparer_values",
        "_signature_status",
    ),
    "registration": (
        "_next_generated_number",
        "_generated_documents",
        "_register_official_version",
    ),
    "transfer_documents": (
        "CHECKLIST_CODES",
        "CHECKLIST",
        "_machine_model",
        "_usage_text",
        "_equipment_text",
        "_return_findings",
        "_protocol_remarks",
        "_checklist_rows",
        "_identity_rows",
        "_protocol_snapshot",
        "_build_protocol_docx",
        "build_protocol_docx",
        "build_return_protocol_docx",
        "_build_protocol_pdf",
        "build_protocol_pdf",
        "build_return_protocol_pdf",
        "_protocol_template_values",
        "make_protocol_documents",
        "make_return_documents",
    ),
    "repair_rendering": (
        "build_repair_protocol_docx",
        "_build_repair_protocol_pdf_legacy",
        "build_repair_protocol_pdf",
        "_repair_test_summary",
        "_repair_duration",
    ),
    "repair_documents": (
        "make_repair_documents",
        "make_repair_correction",
    ),
    "part_request_documents": (
        "_request_snapshot",
        "_part_request_line_description",
        "build_part_request_docx",
        "build_part_request_pdf",
        "make_part_request_documents",
    ),
    "daily_report_documents": ("build_daily_report_pdf",),
}


def test_legacy_imports_are_the_exact_domain_objects():
    for module_name, names in COMPATIBILITY_EXPORTS.items():
        module = importlib.import_module(f"app.documents.{module_name}")
        for name in names:
            assert getattr(compatibility, name) is getattr(module, name), name
    template_engine = importlib.import_module("app.template_engine")
    for name in ("TemplateValidationError", "render_docx", "convert_docx_to_pdf"):
        assert getattr(compatibility, name) is getattr(template_engine, name)


def test_repair_correction_keeps_original_evidence_and_canonical_identity(monkeypatch, tmp_path):
    builder = compatibility.make_repair_documents
    seen = []

    def capture(db, repair, actor, language):
        records = builder(db, repair, actor, language)
        db.add_all(records)
        db.flush()
        document = db.scalar(
            select(OfficialDocument).where(
                OfficialDocument.document_number == records[0].document_number,
            )
        )
        previous = db.get(OfficialDocumentVersion, document.current_version_id)
        original = {
            name: getattr(previous, name)
            for name in (
                "docx_content",
                "pdf_content",
                "docx_sha256",
                "pdf_sha256",
                "snapshot_sha256",
                "signing_sha256",
                "snapshot",
                "template_version_id",
            )
        }
        previous_number = document.document_number
        count = len(db.scalars(select(OfficialDocument)).all())
        with monkeypatch.context() as scoped:
            scoped.setattr(db, "commit", lambda: pytest.fail("Caller owns correction transaction"))
            corrected, canonical, corrected_version = compatibility.make_repair_correction(
                db,
                repair,
                actor,
                "QA-only controlled correction",
                language,
            )
        current = db.get(OfficialDocumentVersion, document.current_version_id)
        assert canonical is document
        assert corrected_version is current
        assert document.document_number == previous_number
        assert len(db.scalars(select(OfficialDocument)).all()) == count
        assert current.version == 2
        assert current.supersedes_version_id == previous.id
        assert current.status == "FINALIZED"
        assert previous.status == "SUPERSEDED"
        assert {name: getattr(previous, name) for name in original} == original
        # Detect in-place JSON mutation as well as replacing the snapshot object.
        assert _json_sha(previous.snapshot) == original["snapshot_sha256"]
        _check_version(document, current, corrected)
        assert all(record.document_number == previous_number + "-V2" for record in corrected)
        assert all(record.snapshot["official_document_id"] == document.id for record in corrected)
        assert all(record.snapshot["official_document_version"] == 2 for record in corrected)
        seen.append(document.id)
        return records

    monkeypatch.setattr(document_qa, "make_repair_documents", capture)
    _generate_isolated_qa(monkeypatch, tmp_path)
    assert len(seen) == 1
