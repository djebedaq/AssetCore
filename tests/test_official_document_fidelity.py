"""Controlled native conversion; explicitly synthetic data, no business records."""
import copy
import hashlib
import io
from types import SimpleNamespace

import pytest
from app.document_studio.native_contract import RESOURCES, STEMS, convert, variant
from app.document_studio.renderer import (
    build_source,
    manifest_from_source,
    render,
    synthetic_values,
)
from app.document_studio.schemas import CompanyIdentity, Layout, walk_blocks
from docx import Document
from docx.oxml.ns import qn


def template(workflow, language):
    stem, number = STEMS[workflow]
    content = (RESOURCES / f"{stem}-{language}-v{number}.docx").read_bytes()
    return SimpleNamespace(id=1, version=number, template=SimpleNamespace(document_type=workflow),
        language=language, source_content=content, source_sha256=hashlib.sha256(content).hexdigest(),
        source_filename=f"{stem}-{language}-v{number}.docx", source_path=None,
        source_media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        required_fields=[], layout_contract={"controlled": True})


def manifest(workflow, language):
    return {"renderer": 1, "layout": convert(template(workflow, language)).model_dump(),
        "document_type": workflow, "language": language,
        "company": {"revision": 0, "identity": CompanyIdentity().model_dump()}, "images": {}}


@pytest.mark.parametrize("workflow", STEMS)
@pytest.mark.parametrize("language", ["bg", "en", "ru"])
def test_native_contract_is_real_source_with_editable_projection(workflow, language):
    m = manifest(workflow, language)
    assert any(b["type"] == "grid" for b in m["layout"]["blocks"])
    assert any(b.type == "native_paragraph" for b in walk_blocks(Layout.model_validate(m["layout"]).blocks))
    source = build_source(m)
    assert manifest_from_source(source) == m
    values, tables = synthetic_values(language, 5)
    values.update(REQUEST_VARIANT="MACHINE", CONDITION_LABEL="SYNTHETIC QA")
    result = render(m, values, tables)
    doc = Document(io.BytesIO(result))
    text = "\n".join(t.text or "" for t in doc.element.iter(qn("w:t")))
    assert "PREVIEW" in text
    assert "{{" not in text
    assert manifest_from_source(result) == m


@pytest.mark.parametrize("language", ["bg", "en", "ru"])
@pytest.mark.parametrize("count", [1, 5, 30])
def test_request_variants_are_frozen_together_and_have_distinct_tables(language, count):
    m = manifest("PART_REQUEST", language)
    values, tables = synthetic_values(language, count)
    values["PRESSURE_BAR"] = 0
    documents = {}
    for name in ("MACHINE", "FREE_FORM"):
        values["REQUEST_VARIANT"] = name
        documents[name] = Document(io.BytesIO(render(m, values, tables)))
    machine, free = documents["MACHINE"], documents["FREE_FORM"]
    assert len(machine.tables) == len(free.tables) + 1
    assert len(machine.tables[1].columns) == 4 and len(free.tables[0].columns) == 3
    assert len(free.tables[0].rows) == count + 1
    assert not any(values["MACHINE_NUMBER"] in p.text for t in free.tables for r in t.rows for c in r.cells for p in c.paragraphs)
    assert machine.sections[0].top_margin.mm == pytest.approx(48, abs=.01)


def test_unrecognized_source_does_not_create_a_generic_starter():
    base = template("PART_REQUEST", "bg")
    base.source_sha256 = "0" * 64
    with pytest.raises(ValueError, match="studio_native_incompatible"):
        convert(base)


def test_ambiguous_default_legacy_selection_refuses_arbitrary_registry(session_factory):
    from app.documents.common import ConfirmedTemplateUnavailableError
    from app.documents.templates import _template_version
    from app.models import DocumentTemplate, DocumentTemplateVersion, User
    from sqlalchemy import select
    with session_factory() as db:
        original = _template_version(db, "TRANSFER_ISSUE", "bg")
        actor = db.scalar(select(User).where(User.is_system_owner.is_(True)))
        duplicate = DocumentTemplate(code="QA_AMBIGUOUS_NATIVE", document_type="TRANSFER_ISSUE",
            name_bg="SYNTHETIC QA", name_en="SYNTHETIC QA", name_ru="SYNTHETIC QA")
        db.add(duplicate)
        db.flush()
        db.add(DocumentTemplateVersion(template_id=duplicate.id, version=original.version, language="bg",
            source_content=original.source_content, source_path=original.source_path,
            source_sha256=original.source_sha256, source_filename="synthetic-qa.docx",
            layout_contract={"controlled": True}, validation_status="PASSED", is_published=True,
            created_by_id=actor.id))
        db.flush()
        with pytest.raises(ConfirmedTemplateUnavailableError):
            _template_version(db, "TRANSFER_ISSUE", "bg")


@pytest.mark.parametrize("window", ["future", "expired"])
def test_explicit_legacy_selection_honors_effective_window(session_factory, window):
    from datetime import UTC, datetime, timedelta

    from app.documents.common import ConfirmedTemplateUnavailableError
    from app.documents.templates import _template_version
    from app.models import DocumentTemplateVersion, StudioActivation, User
    from sqlalchemy import select
    with session_factory() as db:
        original = _template_version(db, "TRANSFER_ISSUE", "bg")
        actor = db.scalar(select(User).where(User.is_system_owner.is_(True)))
        now = datetime.now(UTC).replace(tzinfo=None)
        version = DocumentTemplateVersion(template_id=original.template_id, version=400, language="bg",
            source_content=original.source_content, source_path=original.source_path,
            source_sha256=original.source_sha256, source_filename="synthetic-qa.docx",
            layout_contract={"controlled": True}, validation_status="PASSED", is_published=True,
            effective_from=now + timedelta(days=1) if window == "future" else now - timedelta(days=2),
            effective_to=None if window == "future" else now - timedelta(days=1), created_by_id=actor.id)
        db.add(version)
        db.flush()
        db.add(StudioActivation(document_type="TRANSFER_ISSUE", language="bg", version_id=version.id,
            selection_kind="LEGACY", revision=1, created_by_id=actor.id, reason="SYNTHETIC QA INVALID WINDOW"))
        db.flush()
        with pytest.raises(ConfirmedTemplateUnavailableError):
            _template_version(db, "TRANSFER_ISSUE", "bg")


def test_slots_cannot_be_moved_or_deleted_and_static_text_is_editable():
    m = manifest("TRANSFER_ISSUE", "bg")
    blocks = list(walk_blocks(Layout.model_validate(m["layout"]).blocks))
    slot = next(b for b in blocks if b.type == "native_paragraph" and "{{LEFT_SIGNATURE}}" in b.text)
    raw = next(b for b in walk_blocks(Layout.model_validate(m["layout"]).blocks) if b.id == slot.id)
    raw.text = ""
    bad = copy.deepcopy(m)
    def replace(items):
        for b in items:
            if b["id"] == slot.id:
                b["text"] = ""
            for row in b.get("grid_rows", []):
                for cell in row["cells"]:
                    replace(cell["blocks"])
    replace(bad["layout"]["blocks"])
    values, tables = synthetic_values("bg", 1)
    values["CONDITION_LABEL"] = "QA"
    with pytest.raises(ValueError, match="studio_native_incompatible"):
        render(bad, values, tables)
    def edit(items):
        for b in items:
            if b["type"] == "native_paragraph" and b["text"] and "{{" not in b["text"]:
                b["text"] = "SYNTHETIC EDITED LABEL"
                return True
            for row in b.get("grid_rows", []):
                for cell in row["cells"]:
                    if edit(cell["blocks"]):
                        return True
        return False
    assert edit(m["layout"]["blocks"])
    assert b"SYNTHETIC EDITED LABEL" in render(m, values, tables) or "SYNTHETIC EDITED LABEL" in "\n".join(p.text for p in Document(io.BytesIO(render(m, values, tables))).paragraphs)


def test_variant_comes_from_canonical_snapshot_and_rejects_contradiction():
    assert variant({"request_kind": "FREE_FORM", "machine": None}) == "FREE_FORM"
    assert variant({"request_kind": "CATALOG", "machine": {"name": "SYNTHETIC"}}) == "MACHINE"
    for data in ({"request_kind": "FREE_FORM", "machine": {"name": "SYNTHETIC"}}, {"request_kind": "CATALOG", "machine": None}):
        with pytest.raises(ValueError, match="studio_request_variant_mismatch"):
            variant(data)


def test_native_text_edit_preserves_original_run_and_paragraph_format():
    m = manifest("PART_REQUEST", "bg")
    title = next(b for b in m["layout"]["blocks"] if b["type"] == "native_paragraph" and b["id"].startswith("machine_") and "TECHNICAL SPECIFICATION" in b["text"])
    values, tables = synthetic_values("bg", 1)
    values["REQUEST_VARIANT"] = "MACHINE"
    before = Document(io.BytesIO(render(m, values, tables)))
    original = next(p for p in before.paragraphs if "TECHNICAL SPECIFICATION" in p.text)
    title["text"] = "SYNTHETIC EDITED TITLE"
    after = Document(io.BytesIO(render(m, values, tables)))
    edited = next(p for p in after.paragraphs if p.text == "SYNTHETIC EDITED TITLE")
    assert edited.runs[0]._r.rPr.xml == original.runs[0]._r.rPr.xml
    assert edited._p.pPr.xml == original._p.pPr.xml
    title["style"]["bold"] = not title["style"]["bold"]
    changed = next(p for p in Document(io.BytesIO(render(m, values, tables))).paragraphs if p.text == "SYNTHETIC EDITED TITLE")
    assert changed.runs[0].font.name == edited.runs[0].font.name
    assert changed.runs[0].font.size == edited.runs[0].font.size
    assert changed.runs[0].bold != edited.runs[0].bold


def test_native_image_replacement_uses_frozen_bytes_without_changing_origin():
    import base64
    import zipfile

    from PIL import Image
    m = manifest("TRANSFER_ISSUE", "bg")
    origin = copy.deepcopy(m["layout"]["native"])
    image_block = next(b for b in walk_blocks(Layout.model_validate(m["layout"]).blocks) if b.type == "native_image")
    def replace(items):
        for block in items:
            if block["id"] == image_block.id:
                block["image_id"] = 1
            for row in block.get("grid_rows", []):
                for cell in row["cells"]:
                    replace(cell["blocks"])
    replace(m["layout"]["blocks"])
    output = io.BytesIO()
    Image.new("RGB", (180, 120), "#184c72").save(output, "PNG")
    content = output.getvalue()
    m["images"]["1"] = {"sha256": hashlib.sha256(content).hexdigest(), "content": base64.b64encode(content).decode()}
    values, tables = synthetic_values("bg", 1)
    rendered = render(m, values, tables)
    with zipfile.ZipFile(io.BytesIO(rendered)) as archive:
        hashes = {hashlib.sha256(archive.read(name)).hexdigest() for name in archive.namelist() if name.startswith("word/media/")}
    assert m["images"]["1"]["sha256"] in hashes
    assert m["layout"]["native"] == origin
    assert manifest_from_source(rendered) == m


@pytest.mark.parametrize("variant_name", ["MACHINE", "FREE_FORM"])
def test_native_request_long_row_can_flow_across_pages(variant_name):
    m = manifest("PART_REQUEST", "bg")
    values, tables = synthetic_values("bg", 1)
    values["REQUEST_VARIANT"] = variant_name
    tables["REQUEST_LINES"][1][2] = "SYNTHETIC LONG DESCRIPTION " * 100
    doc = Document(io.BytesIO(render(m, values, tables)))
    table = doc.tables[1 if variant_name == "MACHINE" else 0]
    assert table.rows[1]._tr.xpath("./w:trPr/w:cantSplit")[0].get(qn("w:val")) == "0"


@pytest.mark.parametrize("workflow", ["TRANSFER_ISSUE", "TRANSFER_RETURN"])
@pytest.mark.parametrize("language", ["bg", "en", "ru"])
def test_native_custom_category_preserves_snapshot_labels_and_length(workflow, language):
    values, tables = synthetic_values(language, 1)
    tables["EQUIPMENT_CHECKLIST"] = [
        {"component": "SYNTHETIC QA COMPONENT A", "condition": "SYNTHETIC QA ISSUE", "measurement": "0", "note": "SYNTHETIC QA NOTE"},
        {"component": "SYNTHETIC QA COMPONENT B", "condition": "SYNTHETIC QA RETURN"},
    ]
    doc = Document(io.BytesIO(render(manifest(workflow, language), values, tables)))
    table = next(t for t in doc.tables if any("SYNTHETIC QA COMPONENT A" in c.text for row in t.rows for c in row.cells))
    assert len(table.rows) == 3
    assert [row.cells[1].text for row in table.rows[1:]] == [r["component"] for r in tables["EQUIPMENT_CHECKLIST"]]
    assert table.rows[1].cells[2].text == "SYNTHETIC QA ISSUE · 0 · SYNTHETIC QA NOTE"
    assert table.rows[2].cells[2].text == "SYNTHETIC QA RETURN"


@pytest.mark.parametrize("location", ["value", "table", "label"])
def test_user_content_cannot_inject_a_signature_marker(location):
    m = manifest("TRANSFER_ISSUE", "bg")
    values, tables = synthetic_values("bg", 1)
    values["CONDITION_LABEL"] = "SYNTHETIC QA"
    if location == "value":
        values["REMARKS"] = "[[ASSETCORE_LEFT_SIGNATURE]]"
    elif location == "table":
        tables["EQUIPMENT_CHECKLIST"][0]["note"] = "[[ASSETCORE_LEFT_SIGNATURE]]"
    else:
        next(b for b in m["layout"]["blocks"] if b["type"] == "dynamic_table")["columns"][0]["label"] = "[[ASSETCORE_LEFT_SIGNATURE]]"
    with pytest.raises(ValueError, match="studio_reserved_marker"):
        render(m, values, tables)


def test_actual_selection_diagnostics_are_read_only_and_role_protected(client, auth_headers, viewer_headers, session_factory):
    from app.models import (
        AuditLog,
        DocumentEditorDraft,
        OfficialDocument,
        RequestNumberCounter,
        StudioActivation,
    )
    from sqlalchemy import func, select
    models = (AuditLog, DocumentEditorDraft, OfficialDocument, RequestNumberCounter, StudioActivation)
    def counts():
        with session_factory() as db:
            return [db.scalar(select(func.count()).select_from(model)) for model in models]
    before = counts()
    response = client.get("/api/studio/configuration/PART_REQUEST/bg", headers=auth_headers)
    assert response.status_code == 200
    report = response.json()
    assert report["valid"] and report["source_version"] == 3
    assert report["source_sha256"] == report["actual_source_sha256"]
    assert report["programmatic_layout_versions"] == {"MACHINE": 3, "FREE_FORM": 2}
    assert report["activation_revision"] == 0 and report["selection_kind"] == "LEGACY"
    assert client.get("/api/studio/configuration/PART_REQUEST/bg").status_code == 401
    assert client.get("/api/studio/configuration/PART_REQUEST/bg", headers=viewer_headers).status_code == 403
    assert counts() == before


def test_native_transfer_diagnostics_distinguish_origin_without_kk_layout_numbers(session_factory):
    from app.document_studio.diagnostics import configuration
    from app.documents.templates import _template_version
    from app.models import DocumentTemplateVersion, StudioActivation, User
    from sqlalchemy import select
    with session_factory() as db:
        original = _template_version(db, "TRANSFER_ISSUE", "bg")
        actor = db.scalar(select(User).where(User.is_system_owner.is_(True)))
        source = build_source(manifest("TRANSFER_ISSUE", "bg"))
        version = DocumentTemplateVersion(template_id=original.template_id, version=400, language="bg",
            source_content=source, source_sha256=hashlib.sha256(source).hexdigest(),
            source_filename="synthetic-qa.docx", layout_contract={"studio": 1},
            validation_status="PASSED", is_published=True, created_by_id=actor.id)
        db.add(version)
        db.flush()
        db.add(StudioActivation(document_type="TRANSFER_ISSUE", language="bg", version_id=version.id,
            selection_kind="STUDIO", revision=1, created_by_id=actor.id, reason="SYNTHETIC QA DIAGNOSTICS"))
        db.flush()
        report = configuration(db, "TRANSFER_ISSUE", "bg")
        assert report["valid"] and report["source_version"] == 400
        assert report["native_origin"]["source_version"] == 3
        assert report["native_origin"]["source_sha256"] == template("TRANSFER_ISSUE", "bg").source_sha256
        assert report["programmatic_layout_versions"] is None and report["request_variants"] == []


def test_legacy_base_creates_native_draft_and_cannot_change_its_provenance(client, auth_headers, session_factory):
    from app.models import DocumentTemplateVersion
    from sqlalchemy import select
    with session_factory() as db:
        version = db.scalar(select(DocumentTemplateVersion).where(DocumentTemplateVersion.language == "bg").join(DocumentTemplateVersion.template).where(DocumentTemplateVersion.template.has(document_type="PART_REQUEST")))
        version_id, template_id = version.id, version.template_id
    created = client.post(f"/api/studio/templates/{template_id}/drafts", headers=auth_headers,
        json={"title": "SYNTHETIC QA COPY", "language": "bg", "base_version_id": version_id})
    assert created.status_code == 201
    draft = created.json()
    assert draft["layout"]["schema_version"] == 4
    assert set(draft["layout"]["native"]["sources"]) == {"MACHINE", "FREE_FORM"}
    assert draft["native_images"]
    image = client.get("/api" + draft["native_images"][0]["download_endpoint"], headers=auth_headers)
    assert image.status_code == 200
    assert {"private", "no-store"} <= set(image.headers["cache-control"].split(", "))
    draft["layout"]["native"]["source_version_id"] += 1
    result = client.put(f"/api/studio/drafts/{draft['id']}", headers=auth_headers,
        json={"expected_revision": draft["revision"], "title": draft["title"], "layout": draft["layout"]})
    assert result.status_code == 422 and result.json()["detail"]["code"] == "studio_native_incompatible"


@pytest.mark.parametrize("language", ["bg", "en", "ru"])
def test_professional_request_starter_also_has_two_server_validated_variants(language):
    from app.document_studio.schemas import validate_publication_fields
    from app.document_studio.starter_layouts import professional_layout
    layout = professional_layout("PART_REQUEST", language)
    validate_publication_fields(layout, "PART_REQUEST")
    m = {"renderer": 1, "layout": layout.model_dump(), "document_type": "PART_REQUEST", "language": language,
        "company": {"revision": 0, "identity": CompanyIdentity().model_dump()}, "images": {}}
    values, tables = synthetic_values(language, 5)
    values["REQUEST_VARIANT"] = "FREE_FORM"
    doc = Document(io.BytesIO(render(m, values, tables)))
    text = "\n".join(n.text or "" for n in doc.element.iter(qn("w:t")))
    assert values["MACHINE_NUMBER"] not in text and values["SERIAL_NUMBER"] not in text
    assert any(len(t.columns) == 3 and len(t.rows) == 6 for t in doc.tables)
    bad = layout.model_copy(deep=True)
    next(b for b in bad.blocks if b.type == "grid" and b.request_variant == "MACHINE").request_variant = None
    with pytest.raises(ValueError, match="studio_request_variant_mismatch"):
        render({**m, "layout": bad.model_dump()}, values, tables)


def test_missing_template_refuses_approval_before_any_number_is_reserved(client, auth_headers, session_factory, monkeypatch):
    from app.documents.common import ConfirmedTemplateUnavailableError
    from app.models import PartRequest, RequestApprovalSnapshot, RequestNumberCounter
    from sqlalchemy import func, select
    from test_requests01 import create
    item = create(client, auth_headers, submit_for_approval=True)
    def unavailable(*_args):
        raise ConfirmedTemplateUnavailableError("PART_REQUEST", "bg")
    monkeypatch.setattr("app.documents.templates._template_version", unavailable)
    result = client.post(f"/api/part-requests/{item['id']}/decision", headers=auth_headers, json={"decision": "APPROVED"})
    assert result.status_code == 409 and result.json()["detail"]["code"] == "approval_template_unavailable"
    with session_factory() as db:
        assert db.get(PartRequest, item["id"]).status == "WAITING_APPROVAL"
        assert db.scalar(select(func.count()).select_from(RequestApprovalSnapshot)) == 0
        counter = db.get(RequestNumberCounter, 1)
        assert counter is None or counter.next_value == 1000


def test_native_transfer_markers_remain_in_the_correct_cells():
    from app.signature_rendering import _embed_signature_image
    from PIL import Image
    m = manifest("TRANSFER_ISSUE", "bg")
    values, tables = synthetic_values("bg", 1)
    values.update(LEFT_SIGNATURE="[[ASSETCORE_LEFT_SIGNATURE]]", RIGHT_SIGNATURE="[[ASSETCORE_RIGHT_SIGNATURE]]")
    doc = Document(io.BytesIO(render(m, values, tables)))
    signature_table = next(t for t in doc.tables if len(t.rows) == 2 and len(t.columns) == 3)
    out = io.BytesIO()
    Image.new("RGB", (160, 60), "black").save(out, "PNG")
    for index, side in enumerate(("LEFT", "RIGHT")):
        assert _embed_signature_image(doc, f"[[ASSETCORE_{side}_SIGNATURE]]", out.getvalue())
        assert len(signature_table.rows[index].cells[2]._tc.xpath(".//w:drawing")) == 1
        assert not signature_table.rows[index].cells[1]._tc.xpath(".//w:drawing")


def test_native_kk_without_graphic_cells_refuses_signers_before_sessions_exist():
    from app.document_studio.diagnostics import request_sample
    from app.signature_rendering import validate_studio_request_signer
    from fastapi import HTTPException
    m = manifest("PART_REQUEST", "bg")
    _, values, tables = request_sample("bg", 1, "MACHINE")
    data = {"approval_snapshot_sha256": "SYNTHETIC", "requested_by_id": 1,
            "requested_by_name": "SYNTHETIC QA", "requested_by_job_title": "SYNTHETIC QA"}
    version = SimpleNamespace(snapshot=data, language="bg", docx_content=render(m, values, tables))
    with pytest.raises(HTTPException) as error:
        validate_studio_request_signer(version, "REQUESTED_BY", {"user_id": 1, "display_name": "SYNTHETIC QA", "job_title": "SYNTHETIC QA"}, m)
    assert error.value.status_code == 409 and error.value.detail["code"] == "studio_signature_markers_missing"


def test_native_official_kk_variants_share_sequence_and_keep_frozen_bytes(client, auth_headers, session_factory):
    import os
    import shutil
    if os.name == "nt" or not shutil.which("libreoffice"):
        pytest.skip("Real bounded native publication/archive runs on Linux/Docker and CI")
    from app.models import (
        GeneratedDocument,
        Machine,
        RequestApprovalSnapshot,
        User,
    )
    from sqlalchemy import select
    from test_document_studio_publication import activate, publish
    from test_requests01 import approve, create
    from visual_snapshot_cases import future_catalog, request_payload
    with session_factory() as db:
        actor = db.scalar(select(User).where(User.is_system_owner.is_(True)))
        actor.first_name, actor.middle_name, actor.last_name = "SYNTHETIC", "QA", "ONLY"
        actor.full_name, actor.job_title = "SYNTHETIC QA ONLY", "SYNTHETIC QA ROLE"
        db.commit()
    templates = client.get("/api/studio/templates", headers=auth_headers).json()
    t = next(t for t in templates if t["document_type"] == "PART_REQUEST")
    base = next(v for v in t["versions"] if v["language"] == "bg" and not v["studio"])
    draft = client.post(f"/api/studio/templates/{t['id']}/drafts", headers=auth_headers,
        json={"title": "SYNTHETIC NATIVE OFFICIAL QA", "language": "bg", "base_version_id": base["id"]}).json()
    published, _ = publish(client, auth_headers, draft)
    assert len(published["validation_report"]["cases"]) == 6
    activate(client, auth_headers, published["id"])
    free = approve(client, auth_headers, create(client, auth_headers, submit_for_approval=True,
        lines=[{"description": "SYNTHETIC QA DECIMAL", "quantity": "0.75", "unit": "kg"}]))
    assert free["generation_status"] == "READY"
    catalog = future_catalog(session_factory)
    created = client.post("/api/part-requests/multi", headers=auth_headers, json=request_payload(catalog))
    assert created.status_code == 201
    machine_request = approve(client, auth_headers, created.json())
    assert machine_request["generation_status"] == "READY"
    with session_factory() as db:
        evidence = {d.id: (d.content, d.sha256) for d in db.scalars(select(GeneratedDocument))}
        snapshots = {s.request_id: (s.sha256, s.template_content) for s in db.scalars(select(RequestApprovalSnapshot))}
        free_doc = db.scalar(select(GeneratedDocument).where(GeneratedDocument.part_request_id == free["id"], GeneratedDocument.format == "docx"))
        free_parsed = Document(io.BytesIO(free_doc.content))
        assert len(free_parsed.tables[0].columns) == 3 and len(free_parsed.tables) == 2
        assert "0,75 кг" in "\n".join(n.text or "" for n in free_parsed.element.iter(qn("w:t")))
        machine_doc = db.scalar(select(GeneratedDocument).where(GeneratedDocument.part_request_id == machine_request["id"], GeneratedDocument.format == "docx"))
        assert machine_doc.snapshot["visual_appendix"]["lines"][0]["blocks"]
        assert len(Document(io.BytesIO(machine_doc.content)).inline_shapes) >= 2
        import fitz
        machine_pdf = db.scalar(select(GeneratedDocument).where(GeneratedDocument.part_request_id == machine_request["id"], GeneratedDocument.format == "pdf"))
        with fitz.open(stream=machine_pdf.content, filetype="pdf") as pdf:
            assert len(pdf) >= 3
        db.get(Machine, catalog["machine_id"]).name = "SYNTHETIC QA LATER VALUE"
        db.commit()
    profile = client.get("/api/studio/company", headers=auth_headers).json()
    assert client.put("/api/studio/company", headers=auth_headers, json={"expected_revision": profile["revision"],
        "identity": {**profile["identity"], "legal_name": "SYNTHETIC QA LATER COMPANY"}}).status_code == 200
    restored = client.post("/api/studio/selections/PART_REQUEST/bg/restore-legacy", headers=auth_headers,
        json={"expected_version_id": published["id"], "expected_revision": 1, "reason": "SYNTHETIC QA RESTORE", "confirmed": True})
    assert restored.status_code == 201
    next_free = approve(client, auth_headers, create(client, auth_headers, submit_for_approval=True))
    assert [free["official_number"], machine_request["official_number"], next_free["official_number"]] == ["KK1000", "KK1001", "KK1002"]
    with session_factory() as db:
        for identifier, saved in evidence.items():
            row = db.get(GeneratedDocument, identifier)
            assert (row.content, row.sha256) == saved
        for identifier, saved in snapshots.items():
            row = db.get(RequestApprovalSnapshot, identifier)
            assert (row.sha256, row.template_content) == saved
