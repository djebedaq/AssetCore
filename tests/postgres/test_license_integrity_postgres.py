"""Run signed-entitlement/HTTP consistency cases on real migrated PostgreSQL."""

import pytest
from license_integrity_cases import PROJECTION_CASES, isolated_license_harness

# Reuse the existing safety-named, disposable migrated-schema fixture unchanged.
from test_concurrency import pg_factory as pg_factory

pytestmark = pytest.mark.postgres


def test_signed_entitlement_projection_matrix_and_http_lock_on_postgres(pg_factory, monkeypatch):
    assert pg_factory.kw["bind"].dialect.name == "postgresql"
    with isolated_license_harness(pg_factory, monkeypatch) as licensed:
        for _case, field, value in PROJECTION_CASES:
            initial = licensed.install()
            assert initial["state"] == "READ_ONLY"
            licensed.change_projection(field, value)
            licensed.check_invalid_write_lock()
