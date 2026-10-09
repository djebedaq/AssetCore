"""ASSETCORE-02 on real migrated PostgreSQL, including overlapping approvals."""

import pytest
from app.catalog.references import ReferenceCreate, create
from app.models import CatalogReferenceAssociation, Machine
from sqlalchemy import func, select
from test_concurrency import pg_factory as pg_factory  # noqa: F401
from test_concurrency import race
from test_registry_catalog_02 import (  # noqa: F401
    builtin_selection,
    test_all_eight_corrected_falch_physical_identities_keep_original_catalog,
    test_builder_drafts_excluded_published_revision_pinned,
    test_builtin_references_multiple_machines_exact_variants_and_revoke,
    test_correction_refuses_unverified_states,
    test_identity_preserves_ids_signed_bytes_and_seed,
    test_registry_filters_use_real_signature_evidence_before_pagination,
)

pytestmark = pytest.mark.postgres


@pytest.fixture()
def session_factory(pg_factory):
    return pg_factory


def test_overlapping_reference_approvals_are_atomic(client, auth_headers, session_factory):
    payload, _ = builtin_selection(client, auth_headers, session_factory)
    data = ReferenceCreate.model_validate(payload)
    race(session_factory, Machine, payload["machine_ids"][0], [lambda db, actor: create(db, actor, data)] * 2)
    with session_factory() as db:
        assert db.scalar(select(func.count(CatalogReferenceAssociation.id))) == 2
