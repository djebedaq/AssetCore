"""The same UX read contracts on isolated Alembic-migrated PostgreSQL schemas."""

import pytest
from test_concurrency import pg_factory as pg_factory  # noqa: F401
from test_ux_workspace import (  # noqa: F401
    test_activity_uses_bounded_business_evidence_and_excludes_noise,
    test_batch_context_counts_are_based_on_real_issue_and_return_state,
    test_dynamic_dashboard_counts_and_capability_navigation,
    test_machine_search_pagination_capability_and_literal_wildcards,
    test_machine_sort_uses_creation_time_and_stable_ties,
    test_mixed_batches_preserve_exact_membership_and_legacy_access,
    test_observer_can_read_only_limited_assets,
    test_recent_activity_uses_completion_and_decision_evidence_without_duplicates,
    test_repair_category_search_date_sort_pages_and_legacy_access,
    test_requests_follow_machine_or_repair_category_and_keep_general_requests,
    test_signed_partial_returns_move_between_workspace_contexts_and_retain_documents,
    test_verified_machine_inventory_keeps_natural_order_across_pages,
)

pytestmark = pytest.mark.postgres


@pytest.fixture()
def session_factory(pg_factory):
    return pg_factory
