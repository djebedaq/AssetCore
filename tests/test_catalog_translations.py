from __future__ import annotations

import copy
import hashlib

from app.catalog.sources import dataset_sources, load_all_records, source_path
from app.catalog.translations import (
    TRANSLATION_VERSION,
    load_translation_payload,
    translation_for,
    validate_translation_payload,
)
from app.models import Machine, PartCatalog
from sqlalchemy import select


def test_translation_layer_has_exact_complete_en_bg_coverage():
    report = validate_translation_payload()

    assert report["valid"] is True, report["errors"]
    assert report["translation_record_count"] == 611
    assert report["english_translation_coverage"] == 611
    assert report["bulgarian_translation_coverage"] == 611
    assert report["orphan_translation_count"] == 0
    assert report["missing_translation_count"] == 0
    assert report["duplicate_translation_key_count"] == 0


def test_every_translation_maps_to_one_canonical_source_record():
    source_keys = {row["source_record_key"] for row in load_all_records()}
    translation_keys = {
        row["source_record_key"] for row in load_translation_payload()["records"]
    }

    assert len(source_keys) == 611
    assert translation_keys == source_keys


def test_orphan_translation_is_detected():
    payload = copy.deepcopy(load_translation_payload())
    payload["records"].append(
        {
            "source_record_key": "test-only-orphan-translation",
            "description_en": "Test-only orphan",
            "description_bg": "Тестов осиротял запис",
            "qa_status": "VERIFIED",
        }
    )

    report = validate_translation_payload(payload, verify_source_files=False)

    assert report["valid"] is False
    assert report["orphan_translation_count"] == 1
    assert any("orphan translations" in error for error in report["errors"])


def test_duplicate_canonical_translation_identity_is_detected():
    payload = copy.deepcopy(load_translation_payload())
    payload["records"].append(copy.deepcopy(payload["records"][0]))

    report = validate_translation_payload(payload, verify_source_files=False)

    assert report["valid"] is False
    assert report["duplicate_translation_key_count"] == 1
    assert any("duplicate translation identities" in error for error in report["errors"])


def test_stable_identity_covers_repeated_positions_variants_and_blank_part_numbers():
    source_records = load_all_records()
    translated_keys = {
        row["source_record_key"] for row in load_translation_payload()["records"]
    }
    repeated_position = [
        row
        for row in source_records
        if row["source_id"] == "falch_500_pump" and row["position"] == "0"
    ]
    blank_part_numbers = [row for row in source_records if not row["part_number"]]

    assert len(repeated_position) == 7
    assert len({row["source_record_key"] for row in repeated_position}) == 7
    assert all(row["source_record_key"] in translated_keys for row in repeated_position)
    assert len(blank_part_numbers) == 3
    assert all(row["source_record_key"] in translated_keys for row in blank_part_numbers)


def test_source_descriptions_and_fingerprints_are_unchanged_by_enrichment():
    source_records = load_all_records()
    hose = next(
        row
        for row in source_records
        if row["source_id"] == "falch_1000_liquid_part"
        and row["description_de"] == "schlauch"
    )
    translation = translation_for(hose["source_record_key"])

    assert hose["description"] == "hose"
    assert hose["original_name"] == "schlauch"
    assert translation["description_en"] == "Hose"
    assert translation["description_bg"] == "Шланг"
    assert translation_for(hose["source_record_key"])["source_record_key"] == hose[
        "source_record_key"
    ]

    declared = load_translation_payload()["authoritative_source_fingerprints"]
    assert len(declared) == 9
    for source in dataset_sources():
        actual = hashlib.sha256(source_path(source).read_bytes()).hexdigest()
        assert actual == source["sha256"] == declared[source["source_id"]]


def test_hydwin_position_34_translation_anchor_and_source_data_are_exact():
    row = next(
        row
        for row in load_all_records()
        if row["source_id"] == "hydwin_fussen_500_plunger_pump"
        and row["position"] == "34"
    )
    translation = translation_for(row["source_record_key"])

    assert translation["description_en"] == "Main water seal"
    assert translation["description_bg"] == "Основно водно уплътнение"
    assert translation["qa_status"] == "VERIFIED"
    assert row["part_number"] == "7.906-007.11"
    assert row["description"] == "Main water seal"
    assert row["original_name"] == "Main water seal"
    assert row["description_2"] == "15*24*9.3"


def test_catalog_api_exposes_en_bg_name_and_separate_manufacturer_source(
    client, auth_headers, session_factory
):
    with session_factory() as session:
        machine_id = session.scalar(
            select(Machine.id).where(Machine.inventory_number == "7")
        )
        hose = session.scalar(
            select(PartCatalog).where(
                PartCatalog.source_id == "falch_1000_liquid_part",
                PartCatalog.original_name == "schlauch",
            )
        )
        assert hose is not None
        source_record_key = hose.source_record_key

    response = client.get(
        f"/api/catalog/v2/assemblies/falch_1000_liquid_part?machine_id={machine_id}",
        headers=auth_headers,
    )

    assert response.status_code == 200, response.text
    body = next(
        item
        for item in response.json()["parts"]
        if item["source_record_key"] == source_record_key
    )
    assert body["description"] == "hose"
    assert body["source_description"] == "schlauch"
    assert body["original_name"] == "schlauch"
    assert body["description_en"] == "Hose"
    assert body["description_bg"] == "Шланг"
    assert body["translation_version"] == TRANSLATION_VERSION


def test_catalog_search_matches_bulgarian_enrichment(
    client, auth_headers, session_factory
):
    with session_factory() as session:
        machine_id = session.scalar(
            select(Machine.id).where(Machine.inventory_number == "7")
        )

    response = client.get(
        f"/api/catalog/v2/search?machine_id={machine_id}&q=Шланг",
        headers=auth_headers,
    )

    assert response.status_code == 200, response.text
    assert response.json()
    assert all("шланг" in item["description_bg"].casefold() for item in response.json())


def test_catalog_search_fails_closed_when_translation_integrity_fails(
    client, auth_headers, session_factory, monkeypatch
):
    from app.catalog import service
    from app.catalog.translations import CatalogTranslationError

    with session_factory() as session:
        machine_id = session.scalar(
            select(Machine.id).where(Machine.inventory_number == "7")
        )

    def fail_translation_lookup(_query: str) -> set[str]:
        raise CatalogTranslationError("test-only translation integrity failure")

    monkeypatch.setattr(
        service, "matching_source_record_keys", fail_translation_lookup
    )
    response = client.get(
        f"/api/catalog/v2/search?machine_id={machine_id}&q=Шланг",
        headers=auth_headers,
    )

    assert response.status_code == 503
    detail = response.json()["detail"]
    assert detail["code"] == "catalog_translation_integrity_failed"
    assert detail["operation"] == "catalog_read"
    assert detail["stage"] == "translation_integrity"
