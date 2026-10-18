"""The complete analytical SQL/authorization/export contract on migrated PostgreSQL."""

import pytest
from test_concurrency import pg_factory as pg_factory  # noqa: F401
from test_reports01 import (  # noqa: F401
    report_qa,
    test_reports_attention_five_repairs_original_reasons,
    test_reports_cancelled_request_is_not_overdue,
    test_reports_canonical_deliveries_reversals_units_and_delay,
    test_reports_comparison_distinct_machines,
    test_reports_current_categories_and_active_relationship,
    test_reports_current_details_identify_the_read_snapshot,
    test_reports_delay_is_strictly_more_than_fourteen_calendar_days,
    test_reports_detail_dates_and_unique_contract_over_http,
    test_reports_detail_dates_normalize_aware_utc_and_preserve_missing,
    test_reports_details_order_by_the_metric_event,
    test_reports_export_content_matches_statistics,
    test_reports_export_rejects_changed_data_and_accepts_matching_snapshot,
    test_reports_general_requests_are_included_without_machine_scope,
    test_reports_machine_snapshot_matches_each_direction_export,
    test_reports_nonfinal_and_cancelled_issues_excluded,
    test_reports_partial_return_reissue_cycles_are_individual,
    test_reports_pending_return_is_not_a_completed_cycle,
    test_reports_period_intersection_and_missing_duration,
    test_reports_receipt_drill_is_paginated_by_actual_events,
    test_reports_repairs_do_not_count_events_parts_or_linked_returns_twice,
    test_reports_search_does_not_weaken_objective_attention_history,
    test_reports_signed_workflow_reissues_before_original_batch_finishes,
    test_reports_stable_sql_pagination,
    test_reports_uncategorized_and_literal_search,
    test_reports_underlying_permissions_checked,
    test_reports_unique_issued_details_are_paginated_machines,
    test_reports_zero_baseline_and_incomplete_history_are_explicit,
)

pytestmark = pytest.mark.postgres


@pytest.fixture()
def session_factory(pg_factory):
    return pg_factory
