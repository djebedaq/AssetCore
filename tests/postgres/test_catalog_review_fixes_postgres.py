"""The final-review runtime/audit regressions on migrated PostgreSQL schemas."""

import pytest
from catalog_review_fix_helpers import (
    assert_publication_active_binding_count,
    assert_search_fairness,
)
from test_concurrency import pg_factory as pg_factory  # noqa: F811

pytestmark = pytest.mark.postgres


def test_search_fairness_preserves_catalog_scope_and_integrity(pg_factory):
    assert_search_fairness(pg_factory)


@pytest.mark.parametrize("with_active_binding", [False, True])
def test_publication_audit_counts_only_active_bindings(pg_factory, with_active_binding):
    assert_publication_active_binding_count(pg_factory, with_active_binding)
