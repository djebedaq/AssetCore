"""Identical signed HTTP scenarios on a migrated isolated PostgreSQL schema."""

import pytest
from test_concurrency import pg_factory as pg_factory  # noqa: F401
from test_transfer_lifecycle_projection import qa_machines as qa_machines  # noqa: F401
from test_transfers_ux01 import (  # noqa: F401
    test_cancelled_return_stays_reachable_after_later_successful_completion,
    test_cycle_documents_stay_pinned_when_a_correcting_draft_is_created,
    test_cycle_history_filters_pagination_and_exact_detail_read,
    test_partial_return_reissue_independent_cycles_and_protocols,
    test_special_records_are_reachable_without_becoming_completed,
)

pytestmark = pytest.mark.postgres


@pytest.fixture()
def session_factory(pg_factory):
    return pg_factory
