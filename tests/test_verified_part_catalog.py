from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path

from app.catalog.importer import import_authoritative_catalog
from app.catalog.sources import CATALOG_VERSION, dataset_sources, source_relative_path
from app.catalog.validation import validate_catalog_v2
from app.models import (
    AuditLog,
    CatalogDiagram,
    CatalogPositionHotspot,
    Machine,
    PartCatalog,
    PartRequest,
    RepairKit,
    RepairKitComponent,
    TechnicalDocument,
    User,
)
from sqlalchemy import func, select

ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = ROOT / "backend" / "resources" / "technical_docs" / "PARTS_CATALOG"


def _machine_ids(session_factory) -> dict[str, int]:
    with session_factory() as session:
        return {
            machine.inventory_number: machine.id
            for machine in session.scalars(select(Machine))
        }


def test_authoritative_catalog_import_preserves_all_source_rows_and_traceability(
    session_factory,
):
    with session_factory() as session:
        parts = list(session.scalars(select(PartCatalog)))
        active = [part for part in parts if part.is_active]

        assert len(parts) == 611
        assert len(active) == 611
        assert Counter(part.family for part in active) == {
            "FALCH_500": 309,
            "FALCH_1000": 244,
            "HYDWIN_FUSSEN_500": 58,
        }
        assert Counter(part.source_id for part in active) == {
            "falch_500_wheel_jet": 147,
            "falch_500_pump": 65,
            "falch_500_unloader_valve": 65,
            "falch_500_valve_500bar": 32,
            "falch_1000_wheel_jet": 164,
            "falch_1000_drive_pump": 34,
            "falch_1000_liquid_part": 46,
            "hydwin_fussen_500_plunger_pump": 58,
        }
        assert len({part.source_record_key for part in active}) == 611
        assert all(part.source_record_key for part in active)
        assert all(part.source_id for part in active)
        assert all(part.source_row_index is not None for part in active)
        assert all(part.is_verified for part in active)
        assert all(part.verification_status == "VERIFIED_SOURCE_ROW" for part in active)
        assert all(part.source_version == CATALOG_VERSION for part in active)
        assert all(part.source_document and part.source_page for part in active)
        assert all(
            part.source_document_sha256
            and len(part.source_document_sha256) == 64
            for part in active
        )


def test_source_hashes_pages_scope_and_old_catalog_sources_are_absent(session_factory):
    expected_files = {source["filename"] for source in dataset_sources()}
    bundled_files = {
        path.relative_to(SOURCE_ROOT).as_posix()
        for path in SOURCE_ROOT.rglob("*")
        if path.is_file()
    }
    assert bundled_files == expected_files
    assert len(expected_files) == 9
    assert not (ROOT / "backend" / "resources" / "catalog" / "verified_parts_v1.json").exists()

    for source in dataset_sources():
        path = SOURCE_ROOT / source["filename"]
        assert hashlib.sha256(path.read_bytes()).hexdigest() == source["sha256"]
        if source["source_id"] == "hydwin_fussen_500_plunger_pump":
            assert source["allowed_pages"] == [21, 22]
            assert source["allowed_scope"] == "PLUNGER_PUMP_ONLY"
            assert source["record_pages"] == [22]
            assert source["diagram_pages"] == [21]

    with session_factory() as session:
        documents = list(
            session.scalars(
                select(TechnicalDocument).where(TechnicalDocument.is_active.is_(True))
            )
        )
        assert len(documents) == 9
        assert {document.file_path for document in documents} == {
            source_relative_path(source) for source in dataset_sources()
        }
        assert all(document.dataset_version == CATALOG_VERSION for document in documents)


def test_regression_anchors_blank_codes_and_unusual_quantity_are_exact(session_factory):
    anchors = [
        ("hydwin_fussen_500_plunger_pump", "13", "7.906-002.1", "Plunger rod", "FS C16/50 22*145.5", "3"),
        ("hydwin_fussen_500_plunger_pump", "15", "7.906-003.4", "Ceramic tube", "Φ15*Φ8*46 C1650", "3"),
        ("hydwin_fussen_500_plunger_pump", "34", "7.906-007.11", "Main water seal", "15*24*9.3", "3"),
        ("hydwin_fussen_500_plunger_pump", "35", "7.906-031", "Pump head", "166*89*86", "1"),
        ("falch_500_valve_500bar", "3", "E1230058", "valve seat", None, "1,00"),
        ("falch_500_valve_500bar", "4", "E1230059", "holder", None, "1,00"),
        ("falch_1000_liquid_part", "6", "X4720000", "safety ring", None, "3,00"),
        ("falch_1000_liquid_part", "16", "E1230967", "valve guide", None, "3,00"),
    ]
    with session_factory() as session:
        for source_id, position, number, description, specification, quantity_raw in anchors:
            part = session.scalar(
                select(PartCatalog).where(
                    PartCatalog.source_id == source_id,
                    PartCatalog.position == position,
                    PartCatalog.part_number == number,
                )
            )
            assert part is not None, (source_id, position, number)
            assert part.description == description
            if specification is not None:
                assert part.description_2 == specification
            assert part.quantity_raw == quantity_raw

        falch_kit_rows = list(
            session.scalars(
                select(PartCatalog).where(
                    PartCatalog.source_id == "falch_500_valve_500bar",
                    PartCatalog.position.in_(["3", "4"]),
                )
            )
        )
        assert {part.repair_kit_code for part in falch_kit_rows} == {"E1800023"}
        liquid_rows = list(
            session.scalars(
                select(PartCatalog).where(
                    PartCatalog.source_id == "falch_1000_liquid_part",
                    PartCatalog.position.in_(["6", "16"]),
                )
            )
        )
        assert {(part.position, part.repair_kit_code) for part in liquid_rows} == {
            ("6", "E1800040"),
            ("16", "E0113687"),
        }

        blanks = list(
            session.scalars(
                select(PartCatalog).where(
                    PartCatalog.source_id == "hydwin_fussen_500_plunger_pump",
                    PartCatalog.part_number == "",
                )
            )
        )
        assert {part.position for part in blanks} == {"1", "2", "29"}
        unusual = session.scalar(
            select(PartCatalog).where(
                PartCatalog.source_id == "hydwin_fussen_500_plunger_pump",
                PartCatalog.position == "22",
            )
        )
        assert unusual is not None
        assert unusual.quantity_raw == "1 each"
        assert unusual.quantity is None


def test_repeated_positions_replacements_kits_and_hotspots_remain_source_exact(
    session_factory,
):
    with session_factory() as session:
        pump_zero = list(
            session.scalars(
                select(PartCatalog).where(
                    PartCatalog.source_id == "falch_500_pump",
                    PartCatalog.position == "0",
                )
            )
        )
        assert len(pump_zero) == 7
        assert len({part.source_record_key for part in pump_zero}) == 7
        assert len({part.valid_for_raw for part in pump_zero}) > 1

        replacements = list(
            session.scalars(
                select(PartCatalog).where(PartCatalog.replaced_by_part_number.is_not(None))
            )
        )
        assert {(part.part_number, part.replaced_by_part_number) for part in replacements} == {
            ("E0111569-R", "E0112546"),
            ("E0112546", "E0112917"),
            ("E1220030-R", "E1220041"),
        }

        assert session.scalar(select(func.count(RepairKit.id))) == 7
        assert session.scalar(select(func.count(RepairKitComponent.id))) == 84
        assert session.scalar(select(func.count(CatalogDiagram.id))) == 12
        assert session.scalar(
            select(func.count(CatalogPositionHotspot.id)).where(
                CatalogPositionHotspot.is_verified.is_(True)
            )
        ) == 818
        assert all(
            kit.is_active and kit.is_approved and kit.source_version == CATALOG_VERSION
            for kit in session.scalars(select(RepairKit))
        )


def test_machine_first_api_enforces_exact_family_mapping_and_unsupported_models(
    client, auth_headers, session_factory
):
    machine_ids = _machine_ids(session_factory)
    expected = {
        "9": ("FALCH_500", 4, 309),
        "7": ("FALCH_1000", 3, 244),
        "20": ("HYDWIN_FUSSEN_500", 1, 58),
    }
    for number, (family, assembly_count, part_count) in expected.items():
        response = client.get(
            f"/api/catalog/v2/machines/{machine_ids[number]}", headers=auth_headers
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["supported"] is True
        assert body["family"] == family
        assert len(body["assemblies"]) == assembly_count
        assert sum(item["part_count"] for item in body["assemblies"]) == part_count

    for number in ("4", "5", "19"):
        response = client.get(
            f"/api/catalog/v2/machines/{machine_ids[number]}", headers=auth_headers
        )
        assert response.status_code == 200
        assert response.json()["supported"] is False
        assert response.json()["assemblies"] == []
        assert response.json()["message"] == (
            "Няма потвърдена каталожна документация за този модел."
        )

    mismatch = client.get(
        f"/api/catalog/v2/assemblies/falch_500_pump?machine_id={machine_ids['7']}",
        headers=auth_headers,
    )
    assert mismatch.status_code == 409
    assert mismatch.json()["detail"]["code"] == "catalog_family_mismatch"


def test_multi_part_request_keeps_server_side_machine_compatibility_guard(
    client, auth_headers, session_factory
):
    machine_ids = _machine_ids(session_factory)
    with session_factory() as session:
        falch_part = session.scalar(
            select(PartCatalog).where(
                PartCatalog.source_id == "falch_500_valve_500bar",
                PartCatalog.position == "3",
                PartCatalog.is_active.is_(True),
                PartCatalog.is_verified.is_(True),
            )
        )
        assert falch_part is not None
        part_id = falch_part.id
        before = session.scalar(select(func.count(PartRequest.id)))

    rejected = client.post(
        "/api/part-requests/multi",
        headers=auth_headers,
        json={
            "machine_id": machine_ids["20"],
            "language": "bg",
            "lines": [
                {
                    "catalog_part_id": part_id,
                    "description": "test-only client value",
                    "quantity": 1,
                }
            ],
        },
    )
    assert rejected.status_code == 409, rejected.text
    assert (
        rejected.json()["detail"]["code"]
        == "catalog_parts_not_compatible_with_machine"
    )
    with session_factory() as session:
        assert session.scalar(select(func.count(PartRequest.id))) == before


def test_search_supports_number_description_position_kit_and_replaced_number(
    client, auth_headers, session_factory
):
    machine_id = _machine_ids(session_factory)["9"]
    cases = {
        "E1230058": "E1230058",
        "E123005": "E1230058",
        "valve seat": "E1230058",
        "E1800023": "E1230058",
        "E0112917": "E0112546",
    }
    for query, expected_number in cases.items():
        response = client.get(
            f"/api/catalog/v2/search?machine_id={machine_id}&q={query}",
            headers=auth_headers,
        )
        assert response.status_code == 200, response.text
        assert expected_number in {item["part_number"] for item in response.json()}

    position = client.get(
        f"/api/catalog/v2/search?machine_id={machine_id}&source_id=falch_500_valve_500bar&q=3",
        headers=auth_headers,
    )
    assert position.status_code == 200
    assert any(item["position"] == "3" for item in position.json())
    replacement = next(
        item
        for item in client.get(
            f"/api/catalog/v2/search?machine_id={machine_id}&q=E0112917",
            headers=auth_headers,
        ).json()
        if item["part_number"] == "E0112546"
    )
    assert replacement["order_part_number"] == "E0112917"


def test_diagram_position_api_returns_exact_hydwin_position_34(
    client, auth_headers, session_factory
):
    machine_id = _machine_ids(session_factory)["20"]
    context = client.get(
        f"/api/catalog/v2/machines/{machine_id}", headers=auth_headers
    ).json()
    diagram_id = context["assemblies"][0]["diagrams"][0]["id"]
    response = client.get(
        f"/api/catalog/v2/diagrams/{diagram_id}/hotspots?machine_id={machine_id}&verified_only=true",
        headers=auth_headers,
    )
    assert response.status_code == 200, response.text
    hotspot = next(item for item in response.json() if item["position"] == "34")
    assert hotspot["is_verified"] is True
    assert hotspot["provenance"]
    assert hotspot["confidence"] == 1.0
    assert len(hotspot["variants"]) == 1
    part = hotspot["variants"][0]
    assert part["part_number"] == "7.906-007.11"
    assert part["description"] == "Main water seal"
    assert part["description_2"] == "15*24*9.3"
    assert part["quantity_raw"] == "3"


def test_repair_kit_api_is_source_scoped_and_authorized(
    client, auth_headers, viewer_headers, session_factory
):
    machine_id = _machine_ids(session_factory)["9"]
    response = client.get(
        f"/api/catalog/v2/repair-kits?machine_id={machine_id}&source_id=falch_500_valve_500bar",
        headers=auth_headers,
    )
    assert response.status_code == 200, response.text
    kit = next(item for item in response.json() if item["code"] == "E1800023")
    assert kit["is_approved"] is True
    assert kit["source_id"] == "falch_500_valve_500bar"
    assert all(component["source_record_key"] for component in kit["components"])
    assert all(component["source_document"] for component in kit["components"])

    anonymous = client.get(f"/api/catalog/v2/machines/{machine_id}")
    assert anonymous.status_code == 401
    viewer_read = client.get(
        f"/api/catalog/v2/machines/{machine_id}", headers=viewer_headers
    )
    assert viewer_read.status_code == 403

    with session_factory() as session:
        hotspot_id = session.scalar(select(CatalogPositionHotspot.id))
    forbidden = client.patch(
        f"/api/catalog/v2/hotspots/{hotspot_id}",
        headers=viewer_headers,
        json={"x": 0.5, "y": 0.5, "width": 0.03, "height": 0.03, "is_verified": True, "reason": "Проверка на правата"},
    )
    assert forbidden.status_code == 403


def test_admin_hotspot_correction_is_audited(client, auth_headers, session_factory):
    with session_factory() as session:
        hotspot = session.scalar(select(CatalogPositionHotspot))
        hotspot_id = hotspot.id
        old_x = hotspot.x
        audit_before = session.scalar(
            select(func.count(AuditLog.id)).where(
                AuditLog.entity_type == "catalog_position_hotspot"
            )
        )
    response = client.patch(
        f"/api/catalog/v2/hotspots/{hotspot_id}",
        headers=auth_headers,
        json={"x": min(old_x + 0.001, 0.97), "y": 0.5, "width": 0.03, "height": 0.03, "is_verified": True, "reason": "Тестова визуална повторна проверка"},
    )
    assert response.status_code == 200, response.text
    with session_factory() as session:
        audits = list(
            session.scalars(
                select(AuditLog).where(
                    AuditLog.entity_type == "catalog_position_hotspot"
                )
            )
        )
        assert len(audits) == audit_before + 1
        assert json.loads(audits[-1].details)["reason"] == "Тестова визуална повторна проверка"


def test_position_mapping_is_complete_traceable_and_allows_repeat_occurrences():
    result = validate_catalog_v2()
    assert result["valid"] is True, result["errors"]
    assert result["record_count"] == 611
    assert result["diagram_position_count"] == 581
    assert result["hotspot_count"] == 818
    assert result["duplicate_callout_count"] == 237
    assert result["unresolved_position_count"] == 0
    assert result["positions_not_drawn_count"] == 2
    assert result["false_numeric_candidate_count"] == 28
    assert result["pdf_text_geometry_verified_count"] == 0
    assert result["manual_visual_verification_count"] == 818


def test_position_mapping_coverage_endpoint_is_admin_only(
    client, auth_headers, viewer_headers
):
    response = client.get(
        "/api/catalog/v2/position-mapping/coverage", headers=auth_headers
    )
    assert response.status_code == 200, response.text
    assert response.json()["reviewed_diagram_page_count"] == 12
    assert response.json()["totals"]["mapped_position_count"] == 581

    forbidden = client.get(
        "/api/catalog/v2/position-mapping/coverage", headers=viewer_headers
    )
    assert forbidden.status_code == 403


def test_unverified_qa_geometry_is_not_exposed_to_standard_catalog_users(
    client, session_factory
):
    from app.security import hash_password

    with session_factory() as session:
        session.add(
            User(
                email="mapping-mechanic@assetcore.test",
                full_name="Тестов каталожен механик",
                password_hash=hash_password("MappingMechanic123!"),
                role="mechanic",
            )
        )
        session.commit()
        machine_id = session.scalar(
            select(Machine.id).where(Machine.inventory_number == "9")
        )
        diagram_id = session.scalar(
            select(CatalogDiagram.id).where(
                CatalogDiagram.source_id == "falch_500_valve_500bar"
            )
        )
    login = client.post(
        "/api/auth/login",
        json={
            "email": "mapping-mechanic@assetcore.test",
            "password": "MappingMechanic123!",
        },
    )
    assert login.status_code == 200
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    verified = client.get(
        f"/api/catalog/v2/diagrams/{diagram_id}/hotspots?machine_id={machine_id}&verified_only=true",
        headers=headers,
    )
    assert verified.status_code == 200
    unverified = client.get(
        f"/api/catalog/v2/diagrams/{diagram_id}/hotspots?machine_id={machine_id}&verified_only=false",
        headers=headers,
    )
    assert unverified.status_code == 403


def test_hotspot_geometry_cannot_leave_the_pdf_page(
    client, auth_headers, session_factory
):
    with session_factory() as session:
        hotspot_id = session.scalar(select(CatalogPositionHotspot.id))
        before = session.scalar(
            select(func.count(AuditLog.id)).where(
                AuditLog.entity_type == "catalog_position_hotspot"
            )
        )
    response = client.patch(
        f"/api/catalog/v2/hotspots/{hotspot_id}",
        headers=auth_headers,
        json={
            "x": 0.99,
            "y": 0.99,
            "width": 0.03,
            "height": 0.03,
            "is_verified": True,
            "reason": "Невалидна тестова геометрия",
        },
    )
    assert response.status_code == 422
    with session_factory() as session:
        after = session.scalar(
            select(func.count(AuditLog.id)).where(
                AuditLog.entity_type == "catalog_position_hotspot"
            )
        )
    assert after == before


def test_original_pdf_preview_and_download_are_available(
    client, auth_headers, session_factory
):
    with session_factory() as session:
        document = session.scalar(
            select(TechnicalDocument).where(
                TechnicalDocument.source_id == "hydwin_fussen_500_plunger_pump"
            )
        )
        assert document is not None
        document_id = document.id
        digest = document.sha256

    preview = client.get(
        f"/api/technical-library/{document_id}/pages/21/preview?scale=1",
        headers=auth_headers,
    )
    assert preview.status_code == 200, preview.text
    assert preview.headers["content-type"].startswith("image/png")
    assert preview.content.startswith(b"\x89PNG\r\n\x1a\n")
    assert preview.headers["x-document-sha256"] == digest

    download = client.get(
        f"/api/technical-library/{document_id}/download", headers=auth_headers
    )
    assert download.status_code == 200
    assert hashlib.sha256(download.content).hexdigest() == digest


def test_import_is_idempotent_and_archives_legacy_rows_without_deleting_history(
    session_factory,
):
    with session_factory() as session:
        verifier = session.scalar(select(User).where(User.email == "admin@assetcore.local"))
        legacy = PartCatalog(
            source_record_key="legacy-source-record-for-test",
            brand="Legacy test only",
            model="Legacy test only",
            assembly="Legacy test only",
            position="1",
            part_number="LEGACY-TEST-ONLY",
            description="Legacy test-only historical row",
            source_version="LEGACY_TEST_ONLY",
            is_active=True,
            is_verified=True,
        )
        session.add(legacy)
        session.commit()
        legacy_id = legacy.id

        first = import_authoritative_catalog(session, verifier)
        second = import_authoritative_catalog(session, verifier)
        third = import_authoritative_catalog(session, verifier)
        session.commit()

        assert first["archived_parts"] == 1
        assert second.get("archived_parts", 0) == 0
        assert third.get("archived_parts", 0) == 0
        assert session.scalar(select(func.count(PartCatalog.id))) == 612
        assert session.scalar(
            select(func.count(PartCatalog.id)).where(
                PartCatalog.source_version == CATALOG_VERSION
            )
        ) == 611
        retained = session.get(PartCatalog, legacy_id)
        assert retained is not None
        assert retained.is_active is False


def test_catalog_fails_closed_when_source_integrity_does_not_match(
    client, auth_headers, session_factory, monkeypatch, tmp_path
):
    from app.catalog import sources

    machine_id = _machine_ids(session_factory)["20"]
    real_source_path = sources.source_path
    changed = tmp_path / "changed.pdf"
    changed.write_bytes(b"not-the-authoritative-source")

    def fake_source_path(source):
        if source["source_id"] == "hydwin_fussen_500_plunger_pump":
            return changed
        return real_source_path(source)

    monkeypatch.setattr(sources, "source_path", fake_source_path)
    response = client.get(
        f"/api/catalog/v2/machines/{machine_id}", headers=auth_headers
    )
    assert response.status_code == 503
    detail = response.json()["detail"]
    assert detail["code"] == "catalog_source_integrity_failed"
    assert detail["operation"] == "catalog_read"
    assert detail["stage"] == "source_integrity"
