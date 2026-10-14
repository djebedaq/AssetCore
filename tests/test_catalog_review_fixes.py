"""PR106 final review regressions against an isolated SQLite database."""

import pytest
from catalog_review_fix_helpers import (
    assert_publication_active_binding_count,
    assert_search_fairness,
)


def test_search_fairness_preserves_catalog_scope_and_integrity(session_factory):
    assert_search_fairness(session_factory)


@pytest.mark.parametrize("with_active_binding", [False, True])
def test_publication_audit_counts_only_active_bindings(session_factory, with_active_binding):
    assert_publication_active_binding_count(session_factory, with_active_binding)
