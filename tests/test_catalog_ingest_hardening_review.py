"""Persisted schema evidence, explicit corrections and legacy checkpoint upgrade."""

import pytest
from app.models import CatalogIngestCandidate, CatalogIngestPage, CatalogRevisionPart
from catalog_ingest_fixtures import contextual_table
from sqlalchemy import select
from test_catalog_auto_ingest import BASE, analyze, checked, decide, proposals, upload, workspace


def test_ambiguous_schema_is_reviewable_and_never_accepted_as_parts(client, auth_headers, session_factory):
    _, revision = workspace(client, auth_headers, session_factory)
    data = contextual_table(["ID", "Number", "Type", "Qty"], [["1", "51", "Seal", "2"], ["4", "54", "Pump", "1"]], ruled=True)
    artifact = checked(upload(client, auth_headers, revision, data), 201)
    run = analyze(client, auth_headers, artifact)
    page = proposals(client, auth_headers, run, "PAGE")[0]
    assert page["state"] == "NEEDS_REVIEW" and page["payload"]["role"] == "SPARE_PARTS_LIST"
    assert page["evidence"]["tables"][0]["schema"]["margin"] == 0
    group = proposals(client, auth_headers, run, "GROUP")[0]
    assert group["state"] == "NEEDS_REVIEW" and group["confidence"] <= page["confidence"]
    assert not proposals(client, auth_headers, run, "PART")
    ready = checked(client.get(f"{BASE}/revisions/{revision['id']}/publication-readiness", headers=auth_headers))
    assert not ready["ready"] and any(error["code"] == "catalog_ingest_review_required" for error in ready["errors"])
    before = [row["id"] for row in proposals(client, auth_headers, run, "PAGE")]
    checked(client.post(f"{BASE}/analyses/{run['id']}/retry?rerun=true", headers=auth_headers))
    again = analyze(client, auth_headers, artifact)
    assert [row["id"] for row in proposals(client, auth_headers, again, "PAGE")] == before


@pytest.mark.parametrize("missing", ["/", "-"])
@pytest.mark.parametrize("cached_version", [None, 2])
def test_placeholder_requires_human_correction_and_old_cache_reanalysis_preserves_it(client, auth_headers, session_factory, missing, cached_version):
    _, revision = workspace(client, auth_headers, session_factory)
    data = contextual_table(rows=[["1", missing, "Seal", "1"], ["2", "QA-02", "Pump", "2"]])
    artifact = checked(upload(client, auth_headers, revision, data), 201)
    run = analyze(client, auth_headers, artifact)
    for kind in ["GROUP", "PAGE"]:
        for row in proposals(client, auth_headers, run, kind):
            checked(decide(client, auth_headers, run, row))
    row = proposals(client, auth_headers, run, "PART")[0]
    assert decide(client, auth_headers, run, row).status_code == 422
    edited = checked(decide(client, auth_headers, run, row, "EDIT", edit={"part": {
        "position": "1", "part_number": "QA-HUMAN", "description": "Confirmed source", "quantity": "1"}}))
    accepted = checked(decide(client, auth_headers, run, edited))
    rejected = checked(decide(client, auth_headers, run, proposals(client, auth_headers, run, "PART")[1], "REJECT"))
    with session_factory() as db:
        cached = db.scalar(select(CatalogIngestPage).where(CatalogIngestPage.run_id == run["id"]))
        cached.evidence = {key: value for key, value in cached.evidence.items() if key != "schema_version"}
        if cached_version:
            cached.evidence = {**cached.evidence, "schema_version": cached_version}
        db.commit()
    checked(client.post(f"{BASE}/analyses/{run['id']}/retry?rerun=true", headers=auth_headers))
    again = analyze(client, auth_headers, artifact)
    assert again["id"] == run["id"]  # CATALOG_INGEST_1 stable; geometry/schema evidence is version 3.
    with session_factory() as db:
        assert db.scalar(select(CatalogIngestPage).where(CatalogIngestPage.run_id == run["id"])).evidence["schema_version"] == 3
        assert db.get(CatalogIngestCandidate, accepted["id"]).payload["part_number"] == "QA-HUMAN"
        assert db.get(CatalogRevisionPart, accepted["target_id"]).description == "Confirmed source"
        assert db.get(CatalogIngestCandidate, rejected["id"]).state == "REJECTED"
