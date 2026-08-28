"""Isolated signed-license cases; never persist keys or display signed material.

This helper is deliberately not an assertion-rewritten test module: equality
failures report bounded messages instead of expanding payloads or signatures.
"""

from __future__ import annotations

import base64
import hashlib
import importlib
import json
import secrets
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timedelta
from uuid import uuid4

from app import database, licensing
from app.database import Base
from app.main import app
from app.models import SoftwareLicense, User
from app.security import hash_password
from app.settings import settings
from app.web_security import CONTENT_SECURITY_POLICY
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi.testclient import TestClient
from sqlalchemy import select

NOW = datetime(2035, 1, 15, 12, 0, 0, 123456)
PROJECTION_CASES = (
    ("expiry_null", "valid_until", None),
    ("expiry_future", "valid_until", NOW + timedelta(days=30)),
    ("expiry_earlier", "valid_until", NOW - timedelta(days=4)),
    ("start_different", "valid_from", NOW - timedelta(days=11)),
    ("start_null", "valid_from", None),
    ("grace_increased", "grace_days", 30),
    ("grace_decreased", "grace_days", 0),
    ("grace_negative", "grace_days", -1),
    ("type_different", "license_type", "PERPETUAL"),
    ("installation_different", "installation_id", "other-isolated-installation"),
    ("identity_different", "license_id", "other-isolated-license"),
    ("client_different", "client_name", "Other isolated QA client"),
)


def signed_material(item):
    return deepcopy(item.payload), item.signature, item.payload_sha256


def assert_signed_material_unchanged(item, before):
    before_payload, before_signature, before_payload_sha256 = before
    assert item.payload == before_payload, "Signed payload changed."
    assert item.signature == before_signature, "Signature changed."
    assert item.payload_sha256 == before_payload_sha256, "Payload digest changed."


def database_fingerprint(factory):
    """Compare every QA table without placing raw rows in assertion output."""
    result = {}
    with factory() as db:
        for name, table in Base.metadata.tables.items():
            query = select(table).order_by(*table.primary_key.columns)
            rows = [dict(row) for row in db.execute(query).mappings()]
            encoded = json.dumps(rows, sort_keys=True, default=str).encode()
            result[name] = hashlib.sha256(encoded).hexdigest()
    return result


class LicenseHarness:
    def __init__(self, factory, client, key):
        self.factory = factory
        self.client = client
        self._key = key
        self.record_id = None

    def envelope(self, **changes):
        payload = {
            "license_id": f"QA-INTEGRITY-{uuid4().hex}",
            "rightsholder": licensing.RIGHTSHOLDER,
            "client_name": "Isolated licence regression",
            "installation_id": settings.installation_id,
            "modules": ["assets"],
            "max_users": 100,
            "max_assets": 100,
            "valid_from": (NOW - timedelta(days=10)).isoformat(),
            "valid_until": (NOW - timedelta(days=3)).isoformat(),
            "issued_at": (NOW - timedelta(days=11)).isoformat(),
            "activated_at": (NOW - timedelta(days=10)).isoformat(),
            "support_until": (NOW + timedelta(days=5)).isoformat(),
            "license_type": "ANNUAL",
            "environment": "test",
            "allowed_domains": ["license-qa.example.invalid"],
            "max_installations": 1,
            "grace_days": 1,
            "version": 1,
            **changes,
        }
        return {
            "payload": payload,
            "signature": base64.b64encode(
                self._key.sign(licensing.canonical_payload(payload))
            ).decode(),
        }

    def install(self, **changes):
        envelope = self.envelope(**changes)
        response = self.client.post("/api/license/install", json=envelope)
        assert response.status_code == 200, "Isolated licence installation failed."
        with self.factory() as db:
            item = db.scalar(
                select(SoftwareLicense).where(
                    SoftwareLicense.license_id == envelope["payload"]["license_id"]
                )
            )
            assert item is not None
            self.record_id = item.id
            assert item.payload == envelope["payload"], "Installed payload differs."
            assert item.signature == envelope["signature"], "Installed signature differs."
            assert item.payload_sha256 == licensing.payload_hash(item.payload)
            assert item.license_id == str(item.payload["license_id"])
            assert item.client_name == str(item.payload["client_name"])
            assert item.license_type == str(item.payload["license_type"])
            assert item.installation_id == str(item.payload["installation_id"])
            assert item.valid_from == licensing._parse_datetime(
                item.payload["valid_from"], "valid_from"
            )
            assert item.valid_until == licensing._parse_datetime(
                item.payload.get("valid_until"), "valid_until", required=False
            )
            assert item.grace_days == int(item.payload["grace_days"])
        return response.json()

    def change_projection(self, field, value):
        with self.factory() as db:
            item = db.get(SoftwareLicense, self.record_id)
            before = signed_material(item)
            setattr(item, field, value)
            db.commit()
        with self.factory() as db:
            assert_signed_material_unchanged(db.get(SoftwareLicense, self.record_id), before)
        return before

    def check_invalid_write_lock(self):
        before_db = database_fingerprint(self.factory)
        with self.factory() as db:
            state = licensing.evaluate_license(db, now=NOW)
            assert state.state == "INVALID", "Integrity mismatch did not fail closed."
            assert state.read_only is True
        response = self.client.get("/api/license/status")
        assert response.status_code == 200
        status = response.json()
        assert status["state"] == "INVALID" and status["read_only"] is True
        # Unvalidated entitlements must not be presented as signed facts.
        for field in (
            "license_id",
            "license_type",
            "client_name",
            "valid_from",
            "valid_until",
            "grace_until",
            "rightsholder",
            "max_users",
            "max_assets",
        ):
            assert status[field] is None, "Invalid status exposed an unverified entitlement."
        assert status["modules"] == []
        machine_id = self.client.get("/api/machines").json()[0]["id"]
        path = f"/api/machines/{machine_id}"
        before = self.client.get(path)
        assert before.status_code == 200
        blocked = self.client.patch(path, json={"notes": "Isolated blocked QA write"})
        assert blocked.status_code == 423
        assert blocked.json()["detail"]["code"] == "license_read_only"
        assert blocked.json()["detail"]["license"] == status
        assert blocked.headers["X-AssetCore-License-State"] == "INVALID"
        assert blocked.headers["content-security-policy"] == CONTENT_SECURITY_POLICY
        assert blocked.headers["cache-control"] == "private, no-store, max-age=0"
        assert blocked.headers["x-content-type-options"] == "nosniff"
        for header in (
            "referrer-policy",
            "permissions-policy",
            "x-frame-options",
            "x-permitted-cross-domain-policies",
            "pragma",
            "expires",
        ):
            assert blocked.headers[header] == response.headers[header]
        after = self.client.get(path)
        assert after.status_code == 200 and after.json() == before.json(), (
            "Blocked write changed machine."
        )
        assert database_fingerprint(self.factory) == before_db, (
            "Evaluation or blocked write changed QA database."
        )


@contextmanager
def isolated_license_harness(factory, monkeypatch):
    # Repoint only DB/configuration. All real auth, owner, CSRF and license
    # dependencies/middleware execute; no FastAPI dependency overrides.
    assert not app.dependency_overrides
    with monkeypatch.context() as patch:
        patch.setattr(database, "SessionLocal", factory)
        patch.setattr(importlib.import_module("app.main"), "SessionLocal", factory)
        patch.setattr(settings, "license_enforcement_enabled", True)
        patch.setattr(settings, "installation_id", "isolated-license-integrity")
        patch.setattr(settings, "deployment_environment", "test")
        patch.setattr(settings, "public_base_url", "https://license-qa.example.invalid")
        patch.setattr(licensing, "utcnow", lambda: NOW)
        key = Ed25519PrivateKey.generate()
        public = key.public_key().public_bytes(
            serialization.Encoding.Raw, serialization.PublicFormat.Raw
        )
        patch.setattr(settings, "license_public_key", base64.b64encode(public).decode())
        password = secrets.token_urlsafe(32)
        with factory() as db:
            owner = db.scalar(select(User).where(User.is_system_owner.is_(True)))
            assert owner is not None and owner.role == "administrator"
            owner.first_name, owner.middle_name, owner.last_name = "QA", "License", "Owner"
            owner.full_name, owner.job_title = "QA License Owner", "QA operator"
            owner.profile_status, owner.must_change_password = "PROFILE_COMPLETE", False
            owner.password_hash = hash_password(password)
            email = owner.email
            db.commit()
        client = TestClient(
            app, base_url="https://license-qa.example.invalid", raise_server_exceptions=True
        )
        try:
            logged_in = client.post(
                "/api/auth/login",
                headers={"X-AssetCore-Auth-Mode": "session"},
                json={"email": email, "password": password},
            )
            assert logged_in.status_code == 200, "Isolated owner session login failed."
            assert "access_token" not in logged_in.json()
            client.headers["X-CSRF-Token"] = client.cookies.get(settings.csrf_cookie_name)
            yield LicenseHarness(factory, client, key)
        finally:
            client.close()
