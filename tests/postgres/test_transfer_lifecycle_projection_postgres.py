"""Same signed HTTP lifecycle/cancellation regressions on a migrated PostgreSQL schema."""
import pytest
from test_concurrency import pg_factory as pg_factory  # noqa: F401
from test_transfer_lifecycle_projection import (  # noqa: F401
    qa_machines,
    test_full_return_preserves_operations_documents_signatures_and_read_only_projection,
    test_independent_batches_and_reissue_same_machine_remain_distinct,
    test_legacy_issue_without_manifest_and_view_validation,
    test_pending_cross_batch_return_cancels_exact_operation_and_preserves_issue,
    test_pending_issue_and_completed_history_cancellation,
    test_successive_partial_returns_keep_one_lifecycle,
)

pytestmark = pytest.mark.postgres


@pytest.fixture()
def session_factory(pg_factory):
    return pg_factory
