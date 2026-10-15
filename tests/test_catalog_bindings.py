"""CATALOG-UX-06: disposable synthetic records, transaction and API contracts."""

import json

import pytest
from app.catalog.runtime_context import published_bindings
from app.catalog_admin import bindings, service
from app.catalog_admin.schemas import BatchBind, BatchUnbind, CatalogUpdate
from app.database import Base
from app.models import (
    AssetCategory,
    AuditLog,
    CatalogAssetBinding,
    CatalogDefinition,
    CatalogRevision,
    Machine,
    User,
)
from fastapi import HTTPException
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

BASE = "/api/admin/catalog-builder"


@pytest.fixture()
def binding_factory(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'bindings.db'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, autoflush=False)
    with factory() as db:
        db.add(User(email="bindings@qa.invalid", full_name="Synthetic QA", role="administrator",
                    password_hash="unavailable", is_system_owner=True))
        db.add(AssetCategory(code="QA_OTHER", name_bg="QA", name_en="QA", name_ru="QA"))
        db.commit()
    yield factory
    engine.dispose()


def setup(factory, count=5):
    with factory() as db:
        actor = db.scalar(select(User).where(User.is_system_owner.is_(True)))
        category = AssetCategory(code="QA_UX06", name_bg="QA only", name_en="QA only", name_ru="QA only",
                                 capabilities=["HAS_PARTS_CATALOG"])
        db.add(category)
        db.flush()
        item = CatalogDefinition(code="QA_UX06", asset_category_id=category.id, name_bg="QA only",
                                 name_en="QA only", name_ru="QA only", manufacturer="QA", model_reference="MODEL", created_by_id=actor.id)
        machines = [Machine(inventory_number=f"QA_UX06_{i:04}", name=f"Synthetic QA {i}", brand="QA", model="MODEL",
                            serial_number=f"QA_SERIAL_{i:04}", category=category.code, category_id=category.id) for i in range(count)]
        db.add_all([item, *machines])
        db.flush()
        db.add(CatalogRevision(catalog_id=item.id, revision_code="QA-PUBLISHED", status="PUBLISHED", created_by_id=actor.id))
        db.commit()
        return actor.id, category.id, item.id, [m.id for m in machines]


def payload(db, catalog_id, ids, confirmed=()):
    data = BatchBind(catalog_id=catalog_id, machine_ids=ids, confirmed_machine_ids=list(confirmed))
    return data.model_copy(update={"expected_digest": bindings.preview(db, data)["digest"]})


def removal(db, ids=None):
    rows = bindings.binding_page(db, identities=ids, limit=500)["items"]
    return BatchUnbind(bindings=[{"binding_id": row["id"], "machine_id": row["machine_id"],
                                 "catalog_id": row["catalog_id"], "expected_digest": row["expected_digest"]} for row in rows])


def counts(db):
    return (db.scalar(select(func.count(CatalogAssetBinding.id)).where(CatalogAssetBinding.is_active.is_(True))),
            db.scalar(select(func.count(AuditLog.id)).where(AuditLog.entity_type == "catalog_asset_binding")))


def test_batch_and_single_multiple_catalogs_reactivation_history(binding_factory):
    actor_id, category, catalog, ids = setup(binding_factory)
    with binding_factory() as db:
        actor = db.get(User, actor_id)
        result = bindings.bind(db, actor, payload(db, catalog, ids[:3]))
        assert result["count"] == 3 and counts(db) == (3, 3)
        events = db.scalars(select(AuditLog).where(AuditLog.entity_type == "catalog_asset_binding")).all()
        assert len({json.loads(event.details)["operation_id"] for event in events}) == 1
        assert all(json.loads(event.details)["compatibility"] == "EXACT" for event in events)
        first = result["machines"][0]["binding_id"]
        created = db.get(CatalogAssetBinding, first).created_at
        plan = removal(db)
        assert bindings.unbind(db, actor, plan)["count"] == 3
        assert counts(db) == (0, 6)
        assert len(db.scalars(select(CatalogAssetBinding)).all()) == 3
        service.bind_asset(db, actor, catalog, ids[0])
        assert db.get(CatalogAssetBinding, first).created_at == created
        assert counts(db) == (1, 7)
        assert db.scalar(select(CatalogAssetBinding.id).where(CatalogAssetBinding.machine_id == ids[0])) == first
        second = CatalogDefinition(code="QA_UX06_SECOND", asset_category_id=category, name_bg="QA", name_en="QA", name_ru="QA",
                                   manufacturer="QA", model_reference="MODEL", created_by_id=actor_id)
        db.add(second)
        db.flush()
        db.add(CatalogRevision(catalog_id=second.id, revision_code="QA", status="PUBLISHED", created_by_id=actor_id))
        db.commit()
        service.bind_asset(db, actor, second.id, ids[0])
        service.unbind_asset(db, actor, catalog, ids[0])
        assert [row.catalog_id for row in published_bindings(db, db.get(Machine, ids[0]))] == [second.id]
        assert db.get(CatalogRevision, result["published_revision"]["id"]).status == "PUBLISHED"


@pytest.mark.parametrize("problem,expected", [
    ("brand", "catalog_asset_model_mismatch"), ("category", "catalog_asset_category_mismatch"),
    ("inactive", "catalog_asset_inactive"), ("missing", "catalog_asset_not_found"),
    ("ambiguous", "catalog_asset_compatibility_confirmation_required"),
    ("unpublished", "catalog_not_published"), ("catalog_inactive", "catalog_inactive"),
    ("category_inactive", "catalog_category_inactive"), ("capability", "catalog_category_not_supported"),
])
def test_batch_rejects_entire_group_and_legacy_endpoint_cannot_bypass(binding_factory, problem, expected):
    actor_id, category, catalog, ids = setup(binding_factory)
    with binding_factory() as db:
        machine = db.get(Machine, ids[-1])
        if problem == "brand":
            machine.brand = "QA_OTHER"
        elif problem == "category":
            machine.category_id = db.scalar(select(AssetCategory.id).where(AssetCategory.id != category).limit(1))
        elif problem == "inactive":
            machine.is_active = False
        elif problem == "ambiguous":
            machine.model = None
        elif problem == "missing":
            ids[-1] = 987654321
        elif problem == "unpublished":
            db.scalar(select(CatalogRevision).where(CatalogRevision.catalog_id == catalog)).status = "DRAFT"
        elif problem == "catalog_inactive":
            db.get(CatalogDefinition, catalog).is_active = False
        elif problem == "category_inactive":
            db.get(AssetCategory, category).is_active = False
        elif problem == "capability":
            db.get(AssetCategory, category).capabilities = []
        db.commit()
        actor = db.get(User, actor_id)
        data = payload(db, catalog, ids)
        with pytest.raises(HTTPException) as failure:
            bindings.bind(db, actor, data)
        assert failure.value.detail["code"] == expected
        assert counts(db) == (0, 0)
        with pytest.raises(HTTPException) as failure:
            service.bind_asset(db, actor, catalog, ids[-1], compatibility_confirmed=problem != "ambiguous")
        assert failure.value.detail["code"] == expected
        assert counts(db) == (0, 0)


def test_individual_confirmations_and_published_catalog_with_new_draft(binding_factory):
    actor_id, _, catalog, ids = setup(binding_factory)
    with binding_factory() as db:
        actor = db.get(User, actor_id)
        for identity in ids[:2]:
            db.get(Machine, identity).model = None
        db.add(CatalogRevision(catalog_id=catalog, revision_code="QA-DRAFT", created_by_id=actor_id))
        db.commit()
        with pytest.raises(HTTPException) as failure:
            bindings.bind(db, actor, payload(db, catalog, ids, confirmed=ids[:1]))
        assert failure.value.detail["issues"][0]["id"] == ids[1]
        assert counts(db) == (0, 0)
        result = bindings.bind(db, actor, payload(db, catalog, ids, confirmed=ids[:2]))
        assert result["published_revision"]["revision_code"] == "QA-PUBLISHED"
        events = db.scalars(select(AuditLog).where(AuditLog.entity_type == "catalog_asset_binding")).all()
        assert {json.loads(e.details)["machine_id"] for e in events if json.loads(e.details)["compatibility_confirmed"]} == set(ids[:2])


@pytest.mark.parametrize("action", ["bind", "unbind"])
@pytest.mark.parametrize("failure_point", ["audit", "commit"])
def test_fault_after_prepared_records_rolls_back_bindings_and_audit(binding_factory, monkeypatch, action, failure_point):
    actor_id, _, catalog, ids = setup(binding_factory)
    with binding_factory() as db:
        actor = db.get(User, actor_id)
        if action == "unbind":
            bindings.bind(db, actor, payload(db, catalog, ids))
        data = payload(db, catalog, ids) if action == "bind" else removal(db)
        before = counts(db)
        original = bindings.add_audit_log
        calls = 0
        def faulty(*args, **kwargs):
            nonlocal calls
            calls += 1
            original(*args, **kwargs)
            args[0].flush()
            if calls == 2:
                raise RuntimeError("synthetic QA fault")
        def faulty_commit():
            db.flush()
            raise RuntimeError("synthetic QA fault")
        if failure_point == "audit":
            monkeypatch.setattr(bindings, "add_audit_log", faulty)
        else:
            monkeypatch.setattr(db, "commit", faulty_commit)
        with pytest.raises(RuntimeError, match="synthetic QA fault"):
            getattr(bindings, action)(db, actor, data)
        assert counts(db) == before


def test_stale_preview_duplicate_and_removal_pair_spoof_aba(binding_factory):
    actor_id, _, catalog, ids = setup(binding_factory)
    with binding_factory() as db:
        actor = db.get(User, actor_id)
        data = payload(db, catalog, ids)
        service.update_catalog(db, actor, catalog, CatalogUpdate(name_bg="QA changed"))
        with pytest.raises(HTTPException, match="catalog_bindings_stale"):
            bindings.bind(db, actor, data)
        assert counts(db) == (0, 0)
        bindings.bind(db, actor, payload(db, catalog, ids))
        with pytest.raises(HTTPException, match="catalog_asset_already_bound"):
            bindings.bind(db, actor, data)
        plan = removal(db)
        bad = plan.model_copy(deep=True)
        bad.bindings[-1].machine_id = 987654321
        with pytest.raises(HTTPException, match="catalog_asset_binding_not_found"):
            bindings.unbind(db, actor, bad)
        assert counts(db) == (5, 5)
        service.unbind_asset(db, actor, catalog, ids[0])
        with pytest.raises(HTTPException):
            bindings.unbind(db, actor, plan)
        assert counts(db) == (4, 6)
        service.bind_asset(db, actor, catalog, ids[0])
        with pytest.raises(HTTPException, match="catalog_bindings_stale"):
            bindings.unbind(db, actor, plan)
        assert counts(db) == (5, 7)


def test_legacy_pending_preserved_runtime_hidden_and_removable(binding_factory):
    actor_id, _, catalog, ids = setup(binding_factory)
    with binding_factory() as db:
        actor = db.get(User, actor_id)
        bindings.bind(db, actor, payload(db, catalog, ids[:1]))
        revision = db.scalar(select(CatalogRevision).where(CatalogRevision.catalog_id == catalog))
        revision.status = "DRAFT"  # Model a pre-UX06 database; no migration rewrites it.
        db.commit()
        row = bindings.binding_page(db)["items"][0]
        assert row["status"] == "PENDING_PUBLICATION"
        assert published_bindings(db, db.get(Machine, ids[0])) == []
        assert service.catalog_dict(db, db.get(CatalogDefinition, catalog))["pending_asset_count"] == 1
        with pytest.raises(HTTPException, match="catalog_not_published"):
            service.bind_asset(db, actor, catalog, ids[1])
        assert bindings.binding_page(db)["items"][0]["id"] == row["id"]
        revision.status = "PUBLISHED"
        db.commit()
        assert len(published_bindings(db, db.get(Machine, ids[0]))) == 1
        bindings.unbind(db, actor, removal(db))
        assert db.get(CatalogAssetBinding, row["id"]) is not None
        assert counts(db) == (0, 2)


def test_machine_search_pagination_has_no_hidden_cap_and_includes_serial(binding_factory):
    _, category, catalog, ids = setup(binding_factory, count=125)
    with binding_factory() as db:
        pages = [bindings.machine_page(db, category, catalog, offset=offset) for offset in [0, 50, 100]]
        assert [page["total"] for page in pages] == [125] * 3
        assert {row["id"] for page in pages for row in page["items"]} == set(ids)
        for query in ["QA_UX06_0124", "Synthetic QA 124", "QA_SERIAL_0124"]:
            assert bindings.machine_page(db, category, catalog, search=query)["items"][0]["id"] == ids[-1]


@pytest.mark.parametrize("ids", [[1, 1], [0], [-1], ["1"], [True], [], [987654321]])
def test_api_invalid_and_duplicate_ids(client, auth_headers, session_factory, ids):
    _, _, catalog, _ = setup(session_factory)
    response = client.post(BASE + "/bindings/batch", headers=auth_headers, json={"catalog_id": catalog, "machine_ids": ids})
    assert response.status_code == (409 if ids == [987654321] else 422)
    with session_factory() as db:
        assert counts(db) == (0, 0)


def test_api_contract_and_permission_gates(client, auth_headers, session_factory):
    _, category, catalog, ids = setup(session_factory)
    paths = ["/bindings/preview", "/bindings/batch", "/bindings/batch-deactivate"]
    for path in paths:
        assert client.post(BASE + path, json={}).status_code == 401
    from app.security import create_access_token
    for role in ["director", "mechanic", "observer"]:
        with session_factory() as db:
            user = User(email=f"ux06-{role}@qa.invalid", full_name="Synthetic QA", role=role,
                        password_hash="unavailable", is_active=True, profile_status="PROFILE_COMPLETE")
            db.add(user)
            db.commit()
            headers = {"Authorization": "Bearer " + create_access_token(user)}
        for path in paths:
            assert client.post(BASE + path, headers=headers, json={}).status_code == 403
        for path in ["/bindings", f"/bindings/machines?category_id={category}"]:
            assert client.get(BASE + path, headers=headers).status_code == 403
    request = {"catalog_id": catalog, "machine_ids": ids}
    plan = client.post(BASE + "/bindings/preview", headers=auth_headers, json=request).json()
    response = client.post(BASE + "/bindings/batch", headers=auth_headers, json={**request, "expected_digest": plan["digest"]})
    assert response.status_code == 201 and response.json()["count"] == len(ids)
    page = client.get(BASE + "/bindings", headers=auth_headers, params={"category_id": category}).json()
    assert page["total"] == 5
    data = {"bindings": [{"binding_id": row["id"], "catalog_id": row["catalog_id"], "machine_id": row["machine_id"], "expected_digest": row["expected_digest"]} for row in page["items"]]}
    assert client.post(BASE + "/bindings/batch-deactivate", headers=auth_headers, json=data).json()["count"] == 5
