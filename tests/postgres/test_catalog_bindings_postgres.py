"""Real PostgreSQL waits, atomic rollback, uniqueness and stale generations."""

import pytest
import test_catalog_bindings as contracts
from app.assets.service import update_machine
from app.catalog_admin import bindings, service
from app.catalog_admin.schemas import CatalogUpdate
from app.models import CatalogAssetBinding, CatalogDefinition, Machine, User
from app.schemas import MachineUpdate
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from test_concurrency import pg_factory as pg_factory  # noqa: F811
from test_concurrency import race

pytestmark = pytest.mark.postgres


def test_atomic_commit_reactivation_and_history(pg_factory):
    contracts.test_batch_and_single_multiple_catalogs_reactivation_history(pg_factory)


@pytest.mark.parametrize("action", ["bind", "unbind"])
@pytest.mark.parametrize("failure_point", ["audit", "commit"])
def test_atomic_rollback_with_flushed_records_and_audits(pg_factory, monkeypatch, action, failure_point):
    contracts.test_fault_after_prepared_records_rolls_back_bindings_and_audit(pg_factory, monkeypatch, action, failure_point)


def test_stale_pair_spoof_and_aba(pg_factory):
    contracts.test_stale_preview_duplicate_and_removal_pair_spoof_aba(pg_factory)


@pytest.mark.parametrize("operation", ["bind", "unbind"])
def test_two_overlapping_batches_only_one_commits(pg_factory, operation):
    actor_id, _, catalog, ids = contracts.setup(pg_factory)
    with pg_factory() as db:
        actor = db.get(User, actor_id)
        if operation == "unbind":
            bindings.bind(db, actor, contracts.payload(db, catalog, ids))
        data = contracts.payload(db, catalog, ids) if operation == "bind" else contracts.removal(db)
    outcomes = race(pg_factory, Machine, ids[0], [lambda db, actor: getattr(bindings, operation)(db, actor, data)] * 2)
    assert sorted(row.status for row in outcomes) == [201, 409]
    with pg_factory() as db:
        assert contracts.counts(db) == ((5, 5) if operation == "bind" else (0, 10))
        assert db.scalar(select(func.count(CatalogAssetBinding.id))) == 5


@pytest.mark.parametrize("target", ["machine", "catalog"])
def test_batch_racing_identity_edit_never_creates_incompatible_pairs(pg_factory, target):
    _, _, catalog, ids = contracts.setup(pg_factory)
    with pg_factory() as db:
        data = contracts.payload(db, catalog, ids)
    edit = (lambda db, actor: update_machine(ids[-1], MachineUpdate(model="OTHER"), actor, db)) if target == "machine" else (
        lambda db, actor: service.update_catalog(db, actor, catalog, CatalogUpdate(model_reference="OTHER")))
    model, identity = (Machine, ids[-1]) if target == "machine" else (CatalogDefinition, catalog)
    results = race(pg_factory, model, identity, [lambda db, actor: bindings.bind(db, actor, data), edit], success_status=200)
    assert sorted(row.status for row in results) == [200, 409]
    with pg_factory() as db:
        for pair in db.scalars(select(CatalogAssetBinding).where(CatalogAssetBinding.is_active.is_(True))):
            assert service.compatibility(db.get(CatalogDefinition, pair.catalog_id), db.get(Machine, pair.machine_id)) != "INCOMPATIBLE"
        assert contracts.counts(db) in [(0, 0), (5, 5)]


def test_database_unique_pair_constraint_is_preserved(pg_factory):
    actor_id, _, catalog, ids = contracts.setup(pg_factory)
    with pg_factory() as db:
        bindings.bind(db, db.get(User, actor_id), contracts.payload(db, catalog, ids[:1]))
        db.add(CatalogAssetBinding(catalog_id=catalog, machine_id=ids[0], created_by_id=actor_id))
        with pytest.raises(IntegrityError):
            db.flush()
        db.rollback()
        assert contracts.counts(db) == (1, 1)


def test_unconfirmed_ambiguous_and_pending_retention(pg_factory):
    contracts.test_legacy_pending_preserved_runtime_hidden_and_removable(pg_factory)
