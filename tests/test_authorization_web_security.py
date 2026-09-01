from __future__ import annotations

from app.authorization_inventory import (
    AUTHENTICATED_SPECIAL_MUTATIONS,
    MUTATING_METHODS,
    PUBLIC_ALLOWLIST,
    AuthorizationKind,
    build_authorization_inventory,
)
from app.main import app
from app.models import UserRole
from app.permissions import ROLE_PERMISSIONS, Permission
from app.settings import Settings, settings
from app.web_security import (
    ALLOWED_CORS_HEADERS,
    ALLOWED_CORS_METHODS,
    CONTENT_SECURITY_POLICY,
    WebSecurityMiddleware,
    configured_cors_origins,
    normalize_origin,
)
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.testclient import TestClient


def _production_settings(**overrides) -> Settings:
    values = {
        "_env_file": None,
        "production_mode": True,
        "deployment_environment": "production",
        "database_url": "postgresql+psycopg://assetcore@database/assetcore",
        "secret_key": "test-only-production-secret-material-0001",
        "owner_email": "owner@example.invalid",
        "owner_job_title": "Test production owner",
        "signature_encryption_key": "test-only-signature-encryption-key-0001",
        "license_enforcement_enabled": True,
        "license_public_key": "test-only-public-key",
        "installation_id": "test-only-installation",
        "frontend_origin": "https://assetcore.example.invalid",
        "public_base_url": "https://assetcore.example.invalid",
        "migration_strategy": "external",
    }
    values.update(overrides)
    return Settings(**values)


def _route_map():
    inventory = build_authorization_inventory(app)
    return {(row.method, row.path, row.name): row for row in inventory.routes}


def _security_test_app(configuration: Settings) -> FastAPI:
    test_app = FastAPI()

    @test_app.get("/api/private")
    def private_api() -> dict[str, bool]:
        return {"ok": True}

    @test_app.get("/assets/index-test.js")
    def asset() -> str:
        return "compiled"

    @test_app.get("/sw.js")
    def service_worker() -> str:
        return "self.addEventListener('fetch', () => {})"

    test_app.add_middleware(
        CORSMiddleware,
        allow_origins=list(configured_cors_origins(configuration)),
        allow_credentials=True,
        allow_methods=list(ALLOWED_CORS_METHODS),
        allow_headers=list(ALLOWED_CORS_HEADERS),
    )
    test_app.add_middleware(WebSecurityMiddleware, configuration=configuration)
    return test_app


def test_complete_runtime_route_inventory_is_classified_and_deterministic():
    inventory = build_authorization_inventory(app)
    summary = inventory.summary()
    static_count = sum(
        row.kind == AuthorizationKind.STATIC_PUBLIC.value for row in inventory.routes
    )

    assert inventory.valid, inventory.errors
    # The backend-only CI job intentionally has no compiled frontend/dist;
    # production/Docker has the mount plus SPA route. Both graphs are explicit.
    assert static_count in {0, 3}
    assert summary["route_count"] == 164 + static_count
    assert summary["mutating_route_count"] == 80
    assert summary["by_kind"] == {
        "authenticated": 6,
        "authenticated_special": 8,
        "permission": 135,
        "public_exempt": 15,
        **({"static_public": 3} if static_count else {}),
    }
    assert not [row for row in inventory.routes if row.kind == "unclassified"]
    assert all(
        row.permission or row.kind in {
            AuthorizationKind.AUTHENTICATED_SPECIAL.value,
            AuthorizationKind.PUBLIC_EXEMPT.value,
        }
        for row in inventory.routes
        if row.method in MUTATING_METHODS
    )


def test_new_unprotected_mutation_fails_closed():
    temporary = FastAPI()

    @temporary.post("/new-write")
    def unprotected_write() -> dict[str, bool]:
        return {"ok": True}

    inventory = build_authorization_inventory(temporary)
    assert not inventory.valid
    assert any(
        "Unclassified route: POST /new-write (unprotected_write)" in error
        for error in inventory.errors
    )


def test_public_and_special_exceptions_are_exact_and_have_review_reasons():
    routes = _route_map()

    for entry in (*PUBLIC_ALLOWLIST, *AUTHENTICATED_SPECIAL_MUTATIONS):
        assert entry.reason.strip()
        if not entry.optional:
            row = routes[(entry.key.method, entry.key.path, entry.key.name)]
            assert row.kind != AuthorizationKind.UNCLASSIFIED.value
    assert all(entry.key.path != "/api/{path:path}" for entry in PUBLIC_ALLOWLIST)


def test_representative_mutation_permissions_cover_all_four_roles():
    routes = _route_map()
    expected = {
        ("PATCH", "/api/machines/{machine_id}", "update_machine"): Permission.ASSETS_EDIT,
        ("POST", "/api/transfers/bulk-issue", "bulk_issue_endpoint"):
            Permission.TRANSFERS_CREATE,
        ("POST", "/api/transfers/bulk-return", "bulk_return_endpoint"):
            Permission.TRANSFERS_RETURN,
        ("POST", "/api/repair-cases", "create_repair_case"): Permission.REPAIRS_CREATE,
        ("PATCH", "/api/repair-cases/{repair_id}", "update_repair_case"):
            Permission.REPAIRS_EDIT,
        ("POST", "/api/part-requests/multi", "create_multi_part_request"):
            Permission.REQUESTS_CREATE,
        ("POST", "/api/part-requests/{request_id}/submit", "submit_part_request"):
            Permission.REQUESTS_CREATE,
        ("POST", "/api/part-requests/{request_id}/decision", "decide_part_request"):
            Permission.REQUESTS_APPROVE,
        ("PATCH", "/api/part-requests/{request_id}/fulfillment", "update_part_request_fulfillment"):
            Permission.REQUESTS_CREATE,
        ("PATCH", "/api/catalog/v2/hotspots/{hotspot_id}", "update_hotspot"):
            Permission.PARTS_MANAGE,
        ("POST", "/api/official-documents/{document_id}/supersede", "supersede_document"):
            Permission.DOCUMENTS_GENERATE,
        ("POST", "/api/document-templates", "create_document_template"):
            Permission.TEMPLATES_MANAGE,
        ("POST", "/api/users", "create_user"): Permission.USERS_CREATE,
        ("PATCH", "/api/users/{user_id}", "update_user"): Permission.USERS_EDIT,
        ("POST", "/api/admin/locations", "create_location"): Permission.SETTINGS_MANAGE,
    }
    expected_roles = {
        permission: {
            role
            for role, permissions in ROLE_PERMISSIONS.items()
            if permission in permissions
        }
        for permission in set(expected.values())
    }

    assert set(ROLE_PERMISSIONS) == {role.value for role in UserRole}
    for key, permission in expected.items():
        assert routes[key].permission == permission.value
    assert expected_roles[Permission.ASSETS_EDIT] == {UserRole.ADMINISTRATOR.value}
    assert expected_roles[Permission.PARTS_MANAGE] == {UserRole.ADMINISTRATOR.value}
    assert expected_roles[Permission.TEMPLATES_MANAGE] == {UserRole.ADMINISTRATOR.value}
    assert expected_roles[Permission.SETTINGS_MANAGE] == {UserRole.ADMINISTRATOR.value}
    assert expected_roles[Permission.REQUESTS_APPROVE] == {
        UserRole.ADMINISTRATOR.value,
        UserRole.DIRECTOR.value,
    }
    assert expected_roles[Permission.DOCUMENTS_GENERATE] == {
        UserRole.ADMINISTRATOR.value,
        UserRole.DIRECTOR.value,
        UserRole.MECHANIC.value,
    }
    assert expected_roles[Permission.TRANSFERS_CREATE] == {
        UserRole.ADMINISTRATOR.value,
        UserRole.DIRECTOR.value,
        UserRole.MECHANIC.value,
    }
    assert expected_roles[Permission.TRANSFERS_RETURN] == {
        UserRole.ADMINISTRATOR.value,
        UserRole.DIRECTOR.value,
        UserRole.MECHANIC.value,
    }


def test_security_headers_and_sensitive_api_no_store(client):
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["referrer-policy"] == "strict-origin-when-cross-origin"
    assert "camera=()" in response.headers["permissions-policy"]
    assert response.headers["content-security-policy"] == CONTENT_SECURITY_POLICY
    assert response.headers["cache-control"] == "private, no-store, max-age=0"
    assert response.headers["pragma"] == "no-cache"
    assert "strict-transport-security" not in response.headers

    rejected_login = client.post(
        "/api/auth/login",
        json={"email": "nobody@example.invalid", "password": "not-a-real-password"},
    )
    assert rejected_login.status_code == 401
    assert rejected_login.headers["cache-control"] == "private, no-store, max-age=0"


def test_static_assets_remain_cacheable_and_pwa_files_revalidate():
    configuration = Settings(_env_file=None, deployment_environment="test")
    with TestClient(_security_test_app(configuration)) as test_client:
        asset = test_client.get("/assets/index-test.js")
        worker = test_client.get("/sw.js")

    assert asset.status_code == 200
    assert asset.headers["cache-control"] == "public, max-age=31536000, immutable"
    assert worker.status_code == 200
    assert worker.headers["cache-control"] == "no-cache"
    assert worker.headers["content-security-policy"] == CONTENT_SECURITY_POLICY


def test_csp_matches_vite_pwa_and_authenticated_blob_previews():
    directives = {
        directive.split(" ", 1)[0]: directive
        for directive in CONTENT_SECURITY_POLICY.split("; ")
    }
    assert directives["script-src"] == "script-src 'self'"
    assert "'unsafe-eval'" not in CONTENT_SECURITY_POLICY
    assert "'self'" in directives["frame-src"]
    assert "blob:" in directives["frame-src"]
    assert "blob:" in directives["object-src"]
    assert "blob:" in directives["img-src"]
    assert directives["worker-src"] == "worker-src 'self'"
    assert directives["frame-ancestors"] == "frame-ancestors 'none'"


def test_production_cors_is_explicit_normalized_and_fail_closed():
    configuration = _production_settings(
        frontend_origins="https://app.example.invalid/, https://director.example.invalid:443"
    )
    assert configured_cors_origins(configuration) == (
        "https://app.example.invalid",
        "https://director.example.invalid",
    )
    assert not any("localhost" in origin for origin in configured_cors_origins(configuration))

    with TestClient(_security_test_app(configuration)) as test_client:
        accepted = test_client.options(
            "/api/private",
            headers={
                "Origin": "https://app.example.invalid",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "authorization,content-type",
            },
        )
        rejected = test_client.options(
            "/api/private",
            headers={
                "Origin": "https://unexpected.example.invalid",
                "Access-Control-Request-Method": "POST",
            },
        )

    assert accepted.status_code == 200
    assert accepted.headers["access-control-allow-origin"] == "https://app.example.invalid"
    assert accepted.headers["access-control-allow-credentials"] == "true"
    assert rejected.status_code == 400
    assert "access-control-allow-origin" not in rejected.headers


def test_development_preview_origin_is_not_injected_into_staging():
    development = Settings(_env_file=None, deployment_environment="development")
    staging = Settings(
        _env_file=None,
        deployment_environment="staging",
        secret_key="test-only-staging-secret-material-0001",
        owner_email="owner@example.invalid",
        owner_job_title="Test staging owner",
        signature_encryption_key="test-only-staging-signature-key-0001",
        frontend_origin="https://staging.example.invalid",
        public_base_url="https://staging.example.invalid",
    )
    assert configured_cors_origins(development) == (
        "http://localhost:5173",
        "http://localhost:4173",
    )
    assert configured_cors_origins(staging) == ("https://staging.example.invalid",)


def test_invalid_or_implicit_production_origin_is_rejected():
    values = {
        "_env_file": None,
        "production_mode": True,
        "deployment_environment": "production",
        "database_url": "postgresql+psycopg://assetcore@database/assetcore",
        "secret_key": "test-production-secret-material-0000001",
        "owner_email": "owner@example.invalid",
        "owner_job_title": "Test production owner",
        "signature_encryption_key": "test-signature-key-material-00000001",
        "license_enforcement_enabled": True,
        "license_public_key": "test-only-public-key",
        "installation_id": "test-only-installation",
        "public_base_url": "https://assetcore.example.invalid",
        "migration_strategy": "external",
    }
    try:
        Settings(**values)
    except ValueError as exc:
        assert "FRONTEND_ORIGIN" in str(exc)
    else:
        raise AssertionError("Implicit production CORS origin was accepted")

    for invalid in (
        "*",
        "https://*.example.invalid",
        "https://example.invalid/path",
        "javascript://example.invalid",
    ):
        try:
            normalize_origin(invalid)
        except ValueError:
            pass
        else:
            raise AssertionError(f"Invalid origin was accepted: {invalid}")


def test_hsts_is_only_emitted_for_production_https():
    production = _production_settings()
    with TestClient(
        _security_test_app(production), base_url="https://assetcore.example.invalid"
    ) as https_client:
        secure = https_client.get("/api/private")
    with TestClient(
        _security_test_app(production), base_url="http://assetcore.example.invalid"
    ) as http_client:
        insecure = http_client.get("/api/private")

    assert secure.headers["strict-transport-security"] == (
        "max-age=31536000; includeSubDomains"
    )
    assert "strict-transport-security" not in insecure.headers


def test_protected_document_download_keeps_working_and_is_not_cacheable(
    client, auth_headers
):
    response = client.get("/api/reports/daily.pdf", headers=auth_headers)
    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("application/pdf")
    assert response.headers["cache-control"] == "private, no-store, max-age=0"
    assert response.headers["x-content-type-options"] == "nosniff"


def test_global_development_cors_preflight_is_limited_to_explicit_headers(client):
    accepted = client.options(
        "/api/transfers/bulk-issue",
        headers={
            "Origin": settings.frontend_origin,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "authorization,content-type",
        },
    )
    rejected_header = client.options(
        "/api/transfers/bulk-issue",
        headers={
            "Origin": settings.frontend_origin,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "x-unreviewed-header",
        },
    )
    assert accepted.status_code == 200
    assert rejected_header.status_code == 400
