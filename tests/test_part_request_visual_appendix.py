"""PARTS-DOC-01B: official output uses retained visual evidence only."""

from __future__ import annotations

import base64
import hashlib
import io
import json
import zipfile

import fitz
import pytest
from app.documents import part_request_documents
from app.documents.part_request_grouped_visuals import prepare_appendix
from app.documents.part_request_visual_appendix import LABELS, _render_page
from app.models import (
    CatalogDiagram,
    CatalogVisualPartMap,
    CatalogVisualSource,
    DocumentTemplateVersion,
    GeneratedDocument,
    OfficialDocument,
    OfficialDocumentVersion,
    PartCatalog,
    PartHotspot,
    PartRequestLine,
    PartVisualArtifact,
    TechnicalDocument,
    TechnicalDocumentRevision,
    User,
)
from app.part_requests.service import load_request
from app.part_requests.visual_snapshots import (
    _page_references,
    _snapshot_payload,
    _visual_source,
    create_request_line,
    fingerprint,
)
from app.template_engine import source_bytes
from docx import Document
from fastapi import HTTPException
from PIL import Image
from sqlalchemy import func, select, text
from visual_snapshot_cases import future_catalog, request_payload


def _request(client, headers, data, *, lines=None):
    payload = request_payload(data)
    if lines is not None:
        payload["lines"] = lines
    created = client.post("/api/part-requests/multi", headers=headers, json=payload)
    assert created.status_code == 201, created.text
    request = created.json()
    approved = client.post(
        f"/api/part-requests/{request['id']}/decision",
        headers=headers,
        json={"decision": "APPROVED", "note": "QA approval"},
    )
    assert approved.status_code == 200, approved.text
    return request


def _generate(client, headers, request, language="bg"):
    return client.post(
        f"/api/part-requests/{request['id']}/documents?language={language}",
        headers=headers,
    )


def _records(factory, request_id):
    with factory() as db:
        records = db.scalars(
            select(GeneratedDocument).where(GeneratedDocument.part_request_id == request_id)
        ).all()
        return {
            record.format: (record.content, record.sha256, record.snapshot) for record in records
        }


def test_appendix_labels_have_bg_en_ru_key_parity():
    assert set(LABELS) == {"bg", "en", "ru"}
    assert set(LABELS["bg"]) == set(LABELS["en"]) == set(LABELS["ru"])


def test_future_catalog_official_docx_and_fallback_pdf(
    client, auth_headers, session_factory, monkeypatch
):
    data = future_catalog(session_factory)
    request = _request(client, auth_headers, data)
    with session_factory() as db:
        template_hashes = {
            version.id: version.source_sha256
            for version in db.scalars(select(DocumentTemplateVersion)).all()
        }
    monkeypatch.setattr(part_request_documents, "convert_docx_to_pdf", lambda _: None)
    generated = _generate(client, auth_headers, request)
    assert generated.status_code == 201, generated.text
    records = _records(session_factory, request["id"])
    assert set(records) == {"docx", "pdf"}
    for content, digest, _ in records.values():
        assert digest == hashlib.sha256(content).hexdigest()
    with zipfile.ZipFile(io.BytesIO(records["docx"][0])) as archive:
        document_xml = archive.read("word/document.xml").decode()
        relations = archive.read("word/_rels/document.xml.rels").decode()
        media = [name for name in archive.namelist() if name.startswith("word/media/")]
        media_hashes = {hashlib.sha256(archive.read(name)).hexdigest() for name in media}
    assert "ТЕХНИЧЕСКА СПЕЦИФИКАЦИЯ ЗА ДОСТАВКА НА РЕЗЕРВНИ ЧАСТИ" in document_xml
    assert "QA-991122" in document_xml
    assert "Източник" not in document_xml
    assert 'w:type="page"' in document_xml
    assert 'TargetMode="External"' not in relations
    assert "075b010ecb086b3f36116943c99ac145fe47599595f37ba268538b15b79bc7b0" in media_hashes
    assert "{{" not in document_xml and "data:image/" not in document_xml
    assert "D:\\" not in document_xml and "C:\\" not in document_xml
    with session_factory() as db:
        official = db.scalar(
            select(OfficialDocument).where(
                OfficialDocument.document_number == request["request_reference"]
            )
        )
        version = db.get(OfficialDocumentVersion, official.current_version_id)
        template = db.get(DocumentTemplateVersion, version.template_version_id)
        original_image_count = len(Document(io.BytesIO(source_bytes(template))).inline_shapes)
    rendered_docx = Document(io.BytesIO(records["docx"][0]))
    assert len(rendered_docx.inline_shapes) == original_image_count + 3
    assert len(rendered_docx.tables) == 3
    assert len(rendered_docx.tables[0].columns) == 2
    assert len(rendered_docx.tables[1].rows) == 4
    assert [cell.text for cell in rendered_docx.tables[2].rows[0].cells] == part_request_documents.REQUEST_HEADERS["bg"]
    assert len(media) >= original_image_count + 3
    manifest = records["docx"][2]["visual_appendix"]
    assert manifest["renderer_version"] == 2
    assert len(manifest["pages"]) == 3
    assert {
        (block["artifact_sha256"], block["page_number"]) for block in manifest["lines"][0]["blocks"]
    } == {(data["sha256"], 1), (data["sha256"], 2)}
    assert sorted(
        len(block["occurrence_ordinals"]) for block in manifest["lines"][0]["blocks"]
    ) == [1, 1, 2]
    with fitz.open(stream=records["pdf"][0], filetype="pdf") as pdf:
        assert pdf.page_count >= 3
        pdf_text = "\n".join(page.get_text() for page in pdf)
        assert "ТЕХНИЧЕСКА СПЕЦИФИКАЦИЯ" in pdf_text
        assert "QA-991122" in pdf_text
        for page in list(pdf)[-3:]:
            images = page.get_images(full=True)
            assert len(images) == 1
            for image in images:
                for rect in page.get_image_rects(image[0]):
                    assert page.rect.contains(rect)
    with session_factory() as db:
        official = db.scalar(
            select(OfficialDocument).where(
                OfficialDocument.document_number == request["request_reference"]
            )
        )
        version = db.get(OfficialDocumentVersion, official.current_version_id)
        assert version.docx_sha256 == records["docx"][1]
        assert version.pdf_sha256 == records["pdf"][1]
        assert {
            v.id: v.source_sha256 for v in db.scalars(select(DocumentTemplateVersion)).all()
        } == template_hashes
    duplicate = _generate(client, auth_headers, request)
    assert duplicate.status_code == 409
    assert duplicate.json()["detail"]["code"] == "part_request_protocol_already_generated"


def test_captured_page_grouping_and_marker_pixels(client, auth_headers, session_factory):
    data = future_catalog(session_factory)
    request = _request(client, auth_headers, data)
    with session_factory() as db:
        lines = prepare_appendix(db, load_request(db, request["id"]))
    assert len(lines) == 1
    assert [(block.role, block.page_number, block.ordinals) for block in lines[0].blocks] == [
        ("EXPLODED_SCHEME", 1, (2, 3)),
        ("EXPLODED_SCHEME", 2, (4,)),
        ("LEGACY_UNCLASSIFIED", 2, (1,)),
    ]
    for block in lines[0].blocks:
        with Image.open(io.BytesIO(block.image)) as image:
            assert image.width == block.width and image.height == block.height
            for x, y in (
                [(0.2, 0.2), (0.3, 0.2)] if block.page_number == 1 else
                [(0.1, 0.2)] if block.role == "EXPLODED_SCHEME" else [(0.6, 0.6)]
            ):
                red = image.getpixel((round(x * image.width), round(y * image.height)))
                assert red[0] > red[1] * 1.5 and red[0] > red[2] * 1.5


def test_live_catalog_changes_do_not_change_appendix(client, auth_headers, session_factory):
    data = future_catalog(session_factory)
    request = _request(client, auth_headers, data)
    with session_factory() as db:
        baseline = prepare_appendix(db, load_request(db, request["id"]))
        before = [hashlib.sha256(block.image).hexdigest() for block in baseline[0].blocks]
    with session_factory() as db:
        part = db.get(PartCatalog, data["part_id"])
        part.description = "QA changed after capture"
        part.source_document = "later.pdf"
        db.get(PartRequestLine, request["lines"][0]["id"]).description = "QA changed request line"
        source = db.get(TechnicalDocument, data["document_id"])
        source.uploaded_content = b"later source"
        source.sha256 = hashlib.sha256(source.uploaded_content).hexdigest()
        db.commit()
    with session_factory() as db:
        current = prepare_appendix(db, load_request(db, request["id"]))
        after = [hashlib.sha256(block.image).hexdigest() for block in current[0].blocks]
    assert before == after
    assert current[0].part_number == "QA-991122"
    assert current[0].description == "Synthetic QA rotor"
    assert all(block.filename == "qa-source.pdf" for block in current[0].blocks)


@pytest.mark.parametrize("corrupt", ["snapshot", "artifact"])
def test_corrupt_immutable_source_aborts_official_generation(
    client, auth_headers, session_factory, corrupt
):
    data = future_catalog(session_factory)
    request = _request(client, auth_headers, data)
    with session_factory() as db:
        table = "part_visual_snapshots" if corrupt == "snapshot" else "part_visual_artifacts"
        triggers = (
            db.execute(
                text("SELECT name FROM sqlite_master WHERE type='trigger' AND tbl_name=:table"),
                {"table": table},
            )
            .scalars()
            .all()
        )
        for trigger in triggers:
            db.execute(text(f'DROP TRIGGER "{trigger}"'))
        if corrupt == "snapshot":
            db.execute(text("UPDATE part_visual_snapshots SET occurrence_count=occurrence_count+1"))
        else:
            artifact = db.get(PartVisualArtifact, data["sha256"])
            changed = b"X" + artifact.content[1:]
            db.execute(
                text("UPDATE part_visual_artifacts SET content=:content WHERE sha256=:sha"),
                {"content": changed, "sha": data["sha256"]},
            )
        db.commit()
    response = _generate(client, auth_headers, request)
    assert response.status_code == 409, response.text
    with session_factory() as db:
        assert db.scalar(select(func.count()).select_from(GeneratedDocument)) == 0
        assert db.scalar(select(func.count()).select_from(OfficialDocument)) == 0
        assert db.scalar(select(func.count()).select_from(OfficialDocumentVersion)) == 0


def test_rotated_landscape_page_marker_geometry():
    with fitz.open() as document:
        page = document.new_page(width=400, height=200)
        page.insert_text((30, 30), "QA rotated drawing")
        page.set_rotation(90)
        content = document.tobytes()
    png, width, height = _render_page(
        content,
        "application/pdf",
        1,
        [{"ordinal": 1, "x": 0.25, "y": 0.4, "width": 0.1, "height": 0.1}],
    )
    assert height > width
    with Image.open(io.BytesIO(png)) as image:
        red = image.getpixel((round(width * 0.25), round(height * 0.4)))
        assert red[0] > red[1] * 1.5


@pytest.mark.parametrize(
    "page,geometry",
    [
        (2, {"x": 0.2, "y": 0.3, "width": 0.1, "height": 0.1}),
        (1, {"x": 0.9, "y": 0.3, "width": 0.2, "height": 0.1}),
        (1, {"x": 0.2, "y": 0.3, "width": 0.0, "height": 0.1}),
    ],
)
def test_unreproducible_page_or_invalid_captured_geometry_fails_closed(page, geometry):
    with fitz.open() as document:
        document.new_page()
        content = document.tobytes()
    with pytest.raises(HTTPException) as failure:
        _render_page(content, "application/pdf", page, [{"ordinal": 1, **geometry}])
    assert failure.value.status_code == 409


@pytest.mark.parametrize(
    "language,title",
    [
        ("bg", "Редове без запазена визуална препратка"),
        ("en", "Lines without retained visual references"),
        ("ru", "Строки без сохранённых визуальных ссылок"),
    ],
)
def test_no_visual_reference_is_truthful_and_localized(
    client, auth_headers, session_factory, monkeypatch, language, title
):
    data = future_catalog(session_factory, visuals=False)
    request = _request(client, auth_headers, data)
    monkeypatch.setattr(part_request_documents, "convert_docx_to_pdf", lambda _: None)
    generated = _generate(client, auth_headers, request, language)
    assert generated.status_code == 201, generated.text
    records = _records(session_factory, request["id"])
    with zipfile.ZipFile(io.BytesIO(records["docx"][0])) as archive:
        xml = archive.read("word/document.xml").decode()
    assert title in xml
    docx = Document(io.BytesIO(records["docx"][0]))
    assert [cell.text for cell in docx.tables[2].rows[0].cells] == (
        part_request_documents.REQUEST_HEADERS[language]
    )
    assert len(docx.tables[2].columns) == 4
    assert not {"Източник", "Source", "Источник"}.intersection(
        cell.text for cell in docx.tables[2].rows[0].cells
    )
    assert not records["docx"][2]["visual_appendix"]["lines"][0]["blocks"]
    assert 'w:type="page"' not in xml
    with fitz.open(stream=records["pdf"][0], filetype="pdf") as pdf:
        assert pdf.page_count == 1
        assert title in "\n".join(page.get_text() for page in pdf)


def test_historical_snapshot_without_role_stays_unclassified(
    client, auth_headers, session_factory
):
    data = future_catalog(session_factory)
    request = _request(client, auth_headers, data)
    with session_factory() as db:
        snapshot = load_request(db, request["id"]).lines[0].visual_snapshot
        payload = _snapshot_payload(snapshot)
        payload["catalog"].pop("visual_pages", None)
        for occurrence in payload["visual_references"]:
            occurrence["source_metadata"].pop("visual_role", None)
            occurrence["source_metadata"].pop("catalog_visual_source_id", None)
            occurrence["source_metadata"].pop("catalog_revision", None)
        for table in ("part_visual_snapshots", "part_visual_occurrences"):
            for trigger in db.execute(text(
                "SELECT name FROM sqlite_master WHERE type='trigger' AND tbl_name=:table"
            ), {"table": table}).scalars().all():
                db.execute(text(f'DROP TRIGGER "{trigger}"'))
        db.execute(text("UPDATE part_visual_snapshots SET catalog=:catalog, sha256=:sha WHERE id=:id"),
                   {"catalog": json.dumps(payload["catalog"]),
                    "sha": fingerprint(payload), "id": snapshot.id})
        for reference, original in zip(payload["visual_references"], snapshot.occurrences, strict=True):
            db.execute(text("UPDATE part_visual_occurrences SET source_metadata=:metadata WHERE id=:id"),
                       {"metadata": json.dumps(reference["source_metadata"]), "id": original.id})
        db.commit()
    with session_factory() as db:
        plan = prepare_appendix(db, load_request(db, request["id"]))
    assert len(plan.pages) == 2
    assert all(page.role == "LEGACY_UNCLASSIFIED" for page in plan.pages)


def test_legacy_and_no_binding_have_distinct_historical_notes(
    client, auth_headers, session_factory, monkeypatch
):
    data = future_catalog(session_factory, visuals=False)
    manual = {"description": "QA manual part", "quantity": 1}
    request = _request(client, auth_headers, data, lines=[manual, manual])
    with session_factory() as db:
        stored = load_request(db, request["id"])
        sorted(stored.lines, key=lambda line: line.id)[0].catalog_part_id = data["part_id"]
        db.commit()
    monkeypatch.setattr(part_request_documents, "convert_docx_to_pdf", lambda _: None)
    assert _generate(client, auth_headers, request).status_code == 201
    records = _records(session_factory, request["id"])
    states = [line["blocks"] for line in records["docx"][2]["visual_appendix"]["lines"]]
    assert states == [[], []]
    with zipfile.ZipFile(io.BytesIO(records["docx"][0])) as archive:
        xml = archive.read("word/document.xml").decode()
    assert "няма неизменима визуална снимка" in xml
    assert "няма потвърдена връзка с каталог" in xml


def test_two_lines_same_source_page_keep_separate_part_identity(
    client, auth_headers, session_factory, monkeypatch
):
    data = future_catalog(session_factory)
    with session_factory() as db:
        second = PartCatalog(
            source_record_key="QA-OTHER-SOURCE:1",
            source_id="QA-OTHER-SOURCE",
            brand="QA-SYNTHETIC",
            position="QA-Q8",
            part_number="QA-OTHER-02",
            description="QA second part",
            is_verified=True,
            verification_status="VERIFIED_QA",
            source_document="qa-source.pdf",
            source_page=2,
            compatible_machine_numbers=["QA-FUTURE-9001"],
        )
        db.add(second)
        db.flush()
        db.add(
            PartHotspot(
                part_id=second.id,
                technical_document_id=data["document_id"],
                page_number=2,
                x=0.75,
                y=0.45,
                width=0.05,
                height=0.05,
                label="QA-Q8",
                is_verified=True,
                created_by_id=data["actor_id"],
            )
        )
        db.commit()
        second_id = second.id
    lines = [
        {"catalog_part_id": data["part_id"], "description": "QA first part", "quantity": 1},
        {"catalog_part_id": second_id, "description": "QA second part", "quantity": 1},
    ]
    request = _request(client, auth_headers, data, lines=lines)
    with session_factory() as db:
        appendix = prepare_appendix(db, load_request(db, request["id"]))
    assert [line.part_number for line in appendix] == ["QA-991122", "QA-OTHER-02"]
    assert len(appendix[0].blocks) == 3 and len(appendix[1].blocks) == 1
    assert len(appendix.pages) == 3
    assert appendix[0].blocks[-1].image == appendix[1].blocks[0].image
    monkeypatch.setattr(part_request_documents, "convert_docx_to_pdf", lambda _: None)
    assert _generate(client, auth_headers, request).status_code == 201
    records = _records(session_factory, request["id"])
    with fitz.open(stream=records["pdf"][0], filetype="pdf") as pdf:
        text_content = "\n".join(page.get_text() for page in pdf)
        assert "QA-991122" in text_content and "QA-OTHER-02" in text_content


def test_multiple_artifacts_and_large_request_remain_bounded(
    client, auth_headers, session_factory, monkeypatch
):
    data = future_catalog(session_factory)
    with fitz.open() as source:
        source.new_page(width=500, height=300).insert_text((40, 50), "QA second artifact")
        content = source.tobytes()
    other_sha = hashlib.sha256(content).hexdigest()
    with session_factory() as db:
        document = TechnicalDocument(
            brand="QA-SYNTHETIC",
            category="QA",
            title="QA second artifact",
            file_path="qa-only/second-artifact.pdf",
            uploaded_content=content,
            uploaded_filename="qa-second.pdf",
            media_type="application/pdf",
            sha256=other_sha,
            page_count=1,
        )
        db.add(document)
        db.flush()
        db.add(
            PartHotspot(
                part_id=data["part_id"],
                technical_document_id=document.id,
                page_number=1,
                x=0.4,
                y=0.3,
                width=0.1,
                height=0.1,
                label="QA second artifact",
                is_verified=True,
                created_by_id=data["actor_id"],
            )
        )
        db.commit()
    request = _request(client, auth_headers, data)
    with session_factory() as db:
        stored = load_request(db, request["id"])
        actor = db.get(User, data["actor_id"])
        for _ in range(8):
            create_request_line(
                db,
                stored.id,
                {"catalog_part_id": data["part_id"], "description": "QA extra line", "quantity": 1},
                actor,
            )
        db.commit()
    monkeypatch.setattr(part_request_documents, "convert_docx_to_pdf", lambda _: None)
    generated = _generate(client, auth_headers, request)
    assert generated.status_code == 201, generated.text
    records = _records(session_factory, request["id"])
    manifest = records["docx"][2]["visual_appendix"]
    assert len(manifest["lines"]) == 9
    assert all(
        {block["artifact_sha256"] for block in line["blocks"]} == {data["sha256"], other_sha}
        for line in manifest["lines"]
    )
    assert len(manifest["pages"]) == 4
    with fitz.open(stream=records["pdf"][0], filetype="pdf") as pdf:
        assert pdf.page_count <= 7


def test_explicit_roles_group_shared_scheme_and_list_pages(
    client, auth_headers, session_factory, monkeypatch
):
    data = future_catalog(session_factory)
    with fitz.open() as source:
        source.new_page(width=500, height=300).insert_text((40, 50), "QA list page one")
        source.new_page(width=500, height=300).insert_text((40, 50), "QA list page two")
        list_content = source.tobytes()
    list_sha = hashlib.sha256(list_content).hexdigest()
    with session_factory() as db:
        list_document = TechnicalDocument(
            brand="QA-SYNTHETIC", category="QA", title="QA explicit parts list",
            file_path="qa-only/grouped-list.pdf", source_id="QA-FUTURE-SOURCE",
            dataset_version="QA-REV-42", uploaded_content=list_content,
            uploaded_filename="qa-list.pdf", media_type="application/pdf",
            sha256=list_sha, page_count=2,
        )
        db.add(list_document)
        db.flush()
        for page in (1, 2):
            db.add(CatalogVisualSource(
                source_id="QA-FUTURE-SOURCE", catalog_revision="QA-REV-42",
                technical_document_id=data["document_id"], page_number=page,
                role="EXPLODED_SCHEME", source_sha256=data["sha256"],
            ))
        list_sources = []
        for page in (1, 2):
            source = CatalogVisualSource(
                source_id="QA-FUTURE-SOURCE", catalog_revision="QA-REV-42",
                technical_document_id=list_document.id, page_number=page,
                role="SPARE_PARTS_LIST", source_sha256=list_sha,
            )
            db.add(source)
            db.flush()
            list_sources.append(source)
        part_ids = [data["part_id"]]
        for index in (2, 3):
            part = PartCatalog(
                source_record_key=f"QA-FUTURE-SOURCE:group-{index}",
                source_id="QA-FUTURE-SOURCE", source_version="QA-REV-42",
                brand="QA-SYNTHETIC", position=f"QA-P{index}",
                part_number=f"QA-GROUP-{index}", description=f"QA group part {index}",
                is_verified=True, verification_status="VERIFIED_QA",
                source_document="qa-list.pdf", source_page=1 if index == 2 else 2,
                compatible_machine_numbers=["QA-FUTURE-9001"],
            )
            db.add(part)
            db.flush()
            part_ids.append(part.id)
            db.add(PartHotspot(
                part_id=part.id, technical_document_id=data["document_id"],
                page_number=1, x=0.45 + index * 0.1, y=0.35,
                width=0.04, height=0.05, label=part.position,
                is_verified=True, created_by_id=data["actor_id"],
            ))
        for index, part_id in enumerate(part_ids):
            db.add(CatalogVisualPartMap(
                visual_source_id=list_sources[0 if index < 2 else 1].id,
                part_id=part_id,
            ))
            if index < 2:
                db.add(PartHotspot(
                    part_id=part_id, technical_document_id=list_document.id,
                    page_number=1, x=0.2 + index * 0.45, y=0.6,
                    width=0.04, height=0.05, label=f"QA row {index}",
                    is_verified=True, created_by_id=data["actor_id"],
                ))
        list_source_ids = [source.id for source in list_sources]
        db.commit()
    request = _request(client, auth_headers, data, lines=[
        {"catalog_part_id": part_id, "quantity": 1, "description": "ignored"}
        for part_id in part_ids
    ])
    with session_factory() as db:
        plan = prepare_appendix(db, load_request(db, request["id"]))
        snapshot = load_request(db, request["id"]).lines[0].visual_snapshot
        assert snapshot.catalog["visual_pages"][0]["visual_role"] == "SPARE_PARTS_LIST"
        assert snapshot.occurrences[0].source_metadata["visual_role"] in {
            "EXPLODED_SCHEME", "SPARE_PARTS_LIST"
        }
    assert len(plan.pages) == 4
    assert [page.role for page in plan.pages] == [
        "EXPLODED_SCHEME", "EXPLODED_SCHEME", "SPARE_PARTS_LIST", "SPARE_PARTS_LIST"
    ]
    scheme = next(page for page in plan.pages if page.role == "EXPLODED_SCHEME" and page.page_number == 1)
    shared_list = next(page for page in plan.pages if page.role == "SPARE_PARTS_LIST" and page.page_number == 1)
    assert {item["line_id"] for item in scheme.contributions} == {line["id"] for line in request["lines"]}
    assert len({item["line_id"] for item in shared_list.contributions}) == 2
    assert len({item["line_id"] for item in plan.pages[-1].contributions}) == 1
    with Image.open(io.BytesIO(shared_list.image)) as image:
        for x in (0.2, 0.65):
            red = image.getpixel((round(x * image.width), round(0.6 * image.height)))
            assert red[0] > red[1] * 1.5
    monkeypatch.setattr(part_request_documents, "convert_docx_to_pdf", lambda _: None)
    assert _generate(client, auth_headers, request).status_code == 201
    records = _records(session_factory, request["id"])
    manifest = records["docx"][2]["visual_appendix"]
    assert len(manifest["pages"]) == 4
    docx = Document(io.BytesIO(records["docx"][0]))
    assert len(docx.inline_shapes) == 5  # Official banner and four source pages.
    request_table = next(table for table in docx.tables if table.rows[0].cells[0].text == "Поз.")
    assert len(request_table.columns) == 4
    assert [cell.text for cell in request_table.rows[0].cells] == [
        "Поз.", "PART №", "Описание", "Количество"
    ]
    with session_factory() as db:
        live = db.get(CatalogVisualSource, list_source_ids[0])
        live.role = "EXPLODED_SCHEME"
        db.commit()
    with session_factory() as db:
        unchanged = prepare_appendix(db, load_request(db, request["id"]))
    assert [hashlib.sha256(page.image).hexdigest() for page in unchanged.pages] == [
        hashlib.sha256(page.image).hexdigest() for page in plan.pages
    ]


def test_catalog_revision_a_b_c_preserves_captured_scheme_and_list_pages(
    client, auth_headers, session_factory, monkeypatch
):
    data = future_catalog(session_factory)
    monkeypatch.setattr(part_request_documents, "convert_docx_to_pdf", lambda _: None)

    def pdf_bytes(revision: str) -> bytes:
        with fitz.open() as pdf:
            for page in (1, 2):
                pdf.new_page().insert_text((70, 90), f"QA {revision} page {page}")
            return pdf.tobytes()

    list_bytes = {revision: pdf_bytes(f"list-{revision}") for revision in "ABC"}
    scheme_bytes = {"A": data["content"], **{
        revision: pdf_bytes(f"scheme-{revision}") for revision in "BC"
    }}
    scheme_hashes = {
        revision: hashlib.sha256(content).hexdigest()
        for revision, content in scheme_bytes.items()
    }
    list_hashes = {
        revision: hashlib.sha256(content).hexdigest()
        for revision, content in list_bytes.items()
    }
    with session_factory() as db:
        part = db.get(PartCatalog, data["part_id"])
        list_document = TechnicalDocument(
            brand=part.brand, category="QA", title="QA versioned parts list",
            file_path="qa-only/versioned-list.pdf", source_id=part.source_id,
            dataset_version=part.source_version, sha256=list_hashes["A"],
            uploaded_content=list_bytes["A"], uploaded_filename="qa-list.pdf",
            media_type="application/pdf", page_count=2,
        )
        db.add(list_document)
        db.flush()
        list_document_id = list_document.id
        db.add(TechnicalDocumentRevision(
            document_id=list_document_id, version=1, revision_label="A",
            filename="qa-list.pdf", media_type="application/pdf",
            content=list_bytes["A"], sha256=list_hashes["A"],
        ))
        db.commit()

    def publish(revision: str, list_page: int) -> None:
        with session_factory() as db:
            part = db.get(PartCatalog, data["part_id"])
            scheme_document = db.get(TechnicalDocument, data["document_id"])
            list_document = db.get(TechnicalDocument, list_document_id)
            catalog_revision = "QA-REV-42" if revision == "A" else f"QA-REV-{revision}"
            if revision != "A":
                version = {"B": 43, "C": 44}[revision]
                for document, content, digest, number in (
                    (scheme_document, scheme_bytes[revision], scheme_hashes[revision], version),
                    (list_document, list_bytes[revision], list_hashes[revision], version - 41),
                ):
                    db.add(TechnicalDocumentRevision(
                        document_id=document.id, version=number,
                        revision_label=revision, filename="qa-source.pdf",
                        media_type="application/pdf", content=content, sha256=digest,
                    ))
                    document.sha256 = digest
                    document.uploaded_content = content
                    document.dataset_version = catalog_revision
                    document.revision = revision
                part.source_version = catalog_revision
                part.source_document_sha256 = scheme_hashes[revision]
                for diagram in db.scalars(select(CatalogDiagram).where(
                    CatalogDiagram.source_id == part.source_id
                )):
                    diagram.source_pdf_sha256 = scheme_hashes[revision]
                db.flush()
                if revision == "B":
                    diagram = db.get(CatalogDiagram, data["diagram_ids"][0])
                    with pytest.raises(HTTPException):
                        _visual_source(db, part, scheme_document, 1, diagram=diagram)
                    with pytest.raises(HTTPException):
                        _page_references(db, part)
            for document, role, digest in (
                (scheme_document, "EXPLODED_SCHEME", scheme_hashes[revision]),
                (list_document, "SPARE_PARTS_LIST", list_hashes[revision]),
            ):
                for page in (1, 2):
                    source = CatalogVisualSource(
                        source_id=part.source_id, catalog_revision=catalog_revision,
                        technical_document_id=document.id, page_number=page,
                        role=role, source_sha256=digest,
                    )
                    db.add(source)
                    db.flush()
                    if role == "SPARE_PARTS_LIST" and page == list_page:
                        db.add(CatalogVisualPartMap(
                            visual_source_id=source.id, part_id=part.id,
                        ))
            db.commit()

    def evidence(request: dict, revision: str, list_page: int) -> list[tuple[str, str, int, str]]:
        with session_factory() as db:
            line = load_request(db, request["id"]).lines[0]
            snapshot = line.visual_snapshot
            catalog_revision = "QA-REV-42" if revision == "A" else f"QA-REV-{revision}"
            assert snapshot.catalog["source_version"] == catalog_revision
            assert [(value["visual_role"], value["artifact_sha256"], value["page_number"])
                    for value in snapshot.catalog["visual_pages"]] == [
                ("SPARE_PARTS_LIST", list_hashes[revision], list_page)
            ]
            assert snapshot.catalog["visual_pages"][0]["catalog_revision"] == catalog_revision
            assert {value.artifact_sha256 for value in snapshot.occurrences} == {
                scheme_hashes[revision]
            }
            assert {value.page_number for value in snapshot.occurrences} == {1, 2}
            assert all(value.source_metadata["visual_role"] == "EXPLODED_SCHEME"
                       and value.source_metadata["catalog_revision"] == catalog_revision
                       for value in snapshot.occurrences)
            plan = prepare_appendix(db, load_request(db, request["id"]))
            return [
                (page.role, page.artifact_sha256, page.page_number,
                 hashlib.sha256(page.image).hexdigest())
                for page in plan.pages
            ]

    # The fixture's initial published catalog revision is QA-REV-42.
    publish("A", 1)
    request_a = _request(client, auth_headers, data)
    pages_a = evidence(request_a, "A", 1)
    publish("B", 2)
    request_b = _request(client, auth_headers, data)
    pages_b = evidence(request_b, "B", 2)
    publish("C", 1)
    request_c = _request(client, auth_headers, data)
    pages_c = evidence(request_c, "C", 1)

    assert evidence(request_a, "A", 1) == pages_a
    assert evidence(request_b, "B", 2) == pages_b
    assert evidence(request_c, "C", 1) == pages_c
    assert {page[1] for page in pages_a} == {scheme_hashes["A"], list_hashes["A"]}
    assert {page[1] for page in pages_b} == {scheme_hashes["B"], list_hashes["B"]}
    assert {page[1] for page in pages_c} == {scheme_hashes["C"], list_hashes["C"]}
    assert [page[:3] for page in pages_b if page[0] == "SPARE_PARTS_LIST"] == [
        ("SPARE_PARTS_LIST", list_hashes["B"], 2)
    ]
    with session_factory() as db:
        sources = db.scalars(select(CatalogVisualSource).where(
            CatalogVisualSource.source_id == "QA-FUTURE-SOURCE"
        )).all()
        maps = db.scalars(select(CatalogVisualPartMap).where(
            CatalogVisualPartMap.part_id == data["part_id"]
        )).all()
        assert len(sources) == 12  # Two pages per role in each of three revisions.
        assert len(maps) == 3
        assert {mapping.visual_source.catalog_revision for mapping in maps} == {
            "QA-REV-42", "QA-REV-B", "QA-REV-C"
        }
        assert {revision.sha256 for revision in db.get(
            TechnicalDocument, data["document_id"]
        ).revisions} == set(scheme_hashes.values())
        assert {revision.sha256 for revision in db.get(
            TechnicalDocument, list_document_id
        ).revisions} == set(list_hashes.values())
    for request, revision in ((request_a, "A"), (request_b, "B"), (request_c, "C")):
        response = _generate(client, auth_headers, request)
        assert response.status_code == 201, response.text
        manifest = _records(session_factory, request["id"])["docx"][2]["visual_appendix"]
        assert {page["artifact_sha256"] for page in manifest["pages"]} == {
            scheme_hashes[revision], list_hashes[revision]
        }


def test_unknown_part_uses_link_time_snapshot_without_rewriting_original(
    client, auth_headers, session_factory, monkeypatch
):
    data = future_catalog(session_factory)
    photo = io.BytesIO()
    Image.new("RGB", (8, 8), "white").save(photo, format="PNG")
    created = client.post(
        "/api/part-requests/unknown",
        headers=auth_headers,
        json={
            "machine_id": data["machine_id"],
            "assembly": "QA original assembly",
            "description": "QA original unknown description",
            "quantity": 1,
            "photo": {
                "filename": "qa-unknown.png",
                "media_type": "image/png",
                "content_base64": base64.b64encode(photo.getvalue()).decode(),
            },
        },
    )
    assert created.status_code == 201, created.text
    request = created.json()
    line_id = request["lines"][0]["id"]
    linked = client.post(
        f"/api/part-requests/{request['id']}/lines/{line_id}/link-catalog-part",
        headers=auth_headers,
        json={"catalog_part_id": data["part_id"]},
    )
    assert linked.status_code == 200, linked.text
    assert linked.json()["lines"][0]["description"] == "QA original unknown description"
    with session_factory() as db:
        appendix = prepare_appendix(db, load_request(db, request["id"]))
    assert appendix[0].state == "verified_visual_references"
    assert appendix[0].part_number == "QA-991122"
    assert appendix[0].description == "Synthetic QA rotor"
    assert appendix[0].captured_at == linked.json()["lines"][0]["linked_at"]
    submitted = client.post(f"/api/part-requests/{request['id']}/submit", headers=auth_headers)
    assert submitted.status_code == 200, submitted.text
    approved = client.post(
        f"/api/part-requests/{request['id']}/decision",
        headers=auth_headers,
        json={"decision": "APPROVED", "note": "QA approval"},
    )
    assert approved.status_code == 200, approved.text
    monkeypatch.setattr(part_request_documents, "convert_docx_to_pdf", lambda _: None)
    assert _generate(client, auth_headers, request).status_code == 201
    records = _records(session_factory, request["id"])
    assert records["docx"][2]["visual_appendix"]["lines"][0]["visual_snapshot_sha256"]
