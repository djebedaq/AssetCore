"""Permanent SQLite and real-HTTP signed-entitlement regression coverage."""

from __future__ import annotations

import base64
from datetime import timedelta

import pytest
from app import licensing
from app.models import SoftwareLicense
from license_integrity_cases import (
    NOW,
    PROJECTION_CASES,
    assert_signed_material_unchanged,
    database_fingerprint,
    isolated_license_harness,
)


@pytest.fixture()
def licensed(session_factory, monkeypatch):
    with isolated_license_harness(session_factory, monkeypatch) as harness:
        yield harness


@pytest.mark.parametrize(
    "_case,field,value", PROJECTION_CASES, ids=[case[0] for case in PROJECTION_CASES]
)
def test_projection_consistency_and_http_write_lock(licensed, _case, field, value):
    initial = licensed.install()
    assert initial["state"] == "READ_ONLY" and initial["read_only"] is True
    before = licensed.change_projection(field, value)
    licensed.check_invalid_write_lock()
    with licensed.factory() as db:
        assert_signed_material_unchanged(db.get(SoftwareLicense, licensed.record_id), before)


@pytest.mark.parametrize(
    "expected,changes",
    [
        ("ACTIVE", {"valid_until": (NOW + timedelta(days=5)).isoformat()}),
        ("GRACE_PERIOD", {"valid_until": (NOW - timedelta(days=1)).isoformat(), "grace_days": 2}),
        ("READ_ONLY", {}),
        (
            "NOT_YET_VALID",
            {
                "valid_from": (NOW + timedelta(days=1)).isoformat(),
                "valid_until": (NOW + timedelta(days=5)).isoformat(),
            },
        ),
        ("ACTIVE", {"valid_until": NOW.isoformat()}),
        ("GRACE_PERIOD", {"valid_until": (NOW - timedelta(days=1)).isoformat(), "grace_days": 1}),
    ],
)
def test_normal_signed_states_and_boundaries(licensed, expected, changes):
    status = licensed.install(**changes)
    assert status["state"] == expected
    assert status["read_only"] is (expected in {"READ_ONLY", "NOT_YET_VALID"})
    if expected in {"ACTIVE", "GRACE_PERIOD"}:
        machine_id = licensed.client.get("/api/machines").json()[0]["id"]
        response = licensed.client.patch(
            f"/api/machines/{machine_id}", json={"notes": "Isolated permitted QA write"}
        )
        assert response.status_code == 200


@pytest.mark.parametrize(
    "kind", ["ANNUAL", "TEST", "TRIAL", "EMERGENCY_TEMPORARY", "PERPETUAL", "SUPPORT_ONLY"]
)
def test_supported_license_types_keep_existing_semantics(licensed, kind):
    until = None if kind in {"PERPETUAL", "SUPPORT_ONLY"} else (NOW + timedelta(days=5)).isoformat()
    status = licensed.install(license_type=kind, valid_until=until)
    assert status["state"] == "ACTIVE" and status["read_only"] is False
    assert status["license_type"] == kind and status["valid_until"] == until


@pytest.mark.parametrize("expiry", [None, "", "omit"])
def test_perpetual_optional_expiry_remains_supported(licensed, expiry):
    if expiry == "omit":
        envelope = licensed.envelope(license_type="PERPETUAL")
        del envelope["payload"]["valid_until"]
        envelope["signature"] = base64.b64encode(
            licensed._key.sign(licensing.canonical_payload(envelope["payload"]))
        ).decode()
        response = licensed.client.post("/api/license/install", json=envelope)
        assert response.status_code == 200
        state = response.json()
    else:
        state = licensed.install(license_type="PERPETUAL", valid_until=expiry)
    assert state["state"] == "ACTIVE" and state["valid_until"] is None


def test_dates_use_existing_utc_normalization_and_numeric_compatibility(licensed):
    state = licensed.install(
        valid_from="2035-01-10T15:00:00+03:00",
        valid_until="2035-01-20T07:00:00-05:00",
        grace_days="2",
    )
    assert state["state"] == "ACTIVE"
    assert state["valid_from"] == "2035-01-10T12:00:00"
    assert state["valid_until"] == "2035-01-20T12:00:00"
    assert state["grace_until"] == "2035-01-22T12:00:00"


def test_not_installed_keeps_enforcement_and_read_access(licensed):
    before = database_fingerprint(licensed.factory)
    state = licensed.client.get("/api/license/status").json()
    assert state["state"] == "NOT_INSTALLED" and state["read_only"] is True
    assert licensed.client.get("/api/machines").status_code == 200
    assert database_fingerprint(licensed.factory) == before


@pytest.mark.parametrize(
    "field,value",
    [("signature", base64.b64encode(b"x" * 64).decode()), ("payload_sha256", "0" * 64)],
    ids=["signature", "digest"],
)
def test_invalid_signature_or_digest_remains_fail_closed(licensed, field, value):
    licensed.install(valid_until=(NOW + timedelta(days=5)).isoformat())
    with licensed.factory() as db:
        setattr(db.get(SoftwareLicense, licensed.record_id), field, value)
        db.commit()
    licensed.check_invalid_write_lock()


@pytest.mark.parametrize(
    "changes,code",
    [
        ({"installation_id": "other-isolated-installation"}, "installation_mismatch"),
        ({"environment": "production"}, "environment_mismatch"),
        ({"allowed_domains": ["other.example.invalid"]}, "domain_mismatch"),
        ({"max_assets": 1}, "license_capacity_below_current_usage"),
    ],
)
def test_install_rejections_preserve_current_license(licensed, changes, code):
    licensed.install(valid_until=(NOW + timedelta(days=5)).isoformat())
    before = licensed.client.get("/api/license/status").json()
    response = licensed.client.post("/api/license/install", json=licensed.envelope(**changes))
    assert response.status_code == 409 and response.json()["detail"]["code"] == code
    assert licensed.client.get("/api/license/status").json() == before


def test_serialization_uses_verified_snapshot_not_later_projection_values(licensed):
    licensed.install(valid_until=(NOW + timedelta(days=5)).isoformat())
    with licensed.factory() as db:
        state = licensing.evaluate_license(db, now=NOW)
        before = licensing.serialize_license_state(state)
        state.license.valid_until = NOW + timedelta(days=999)
        state.license.client_name = "Unsigned display change"
        state.license.payload["modules"].append("unsigned-in-place-change")
        state.license.payload = {"modules": ["unsigned-module"]}
        assert licensing.serialize_license_state(state) == before
        db.rollback()
