from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass
from enum import Enum
from typing import Iterable

from fastapi import FastAPI
from fastapi.dependencies.models import Dependant
from fastapi.routing import APIRoute
from starlette.routing import Mount, Route

from .security import get_authenticated_user, get_current_active_user

READ_METHODS = frozenset({"GET", "HEAD"})
MUTATING_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})


class AuthorizationKind(str, Enum):
    PERMISSION = "permission"
    AUTHENTICATED = "authenticated"
    AUTHENTICATED_SPECIAL = "authenticated_special"
    PUBLIC_EXEMPT = "public_exempt"
    STATIC_PUBLIC = "static_public"
    UNCLASSIFIED = "unclassified"


@dataclass(frozen=True)
class RouteKey:
    method: str
    path: str
    name: str


@dataclass(frozen=True)
class AllowlistEntry:
    key: RouteKey
    reason: str
    optional: bool = False


@dataclass(frozen=True)
class RouteAuthorization:
    method: str
    path: str
    name: str
    kind: str
    permission: str | None
    reason: str
    mutating: bool


@dataclass(frozen=True)
class AuthorizationInventory:
    routes: tuple[RouteAuthorization, ...]
    errors: tuple[str, ...]

    @property
    def valid(self) -> bool:
        return not self.errors

    def summary(self) -> dict[str, object]:
        by_kind = Counter(route.kind for route in self.routes)
        by_method = Counter(route.method for route in self.routes)
        mutating = [route for route in self.routes if route.mutating]
        return {
            "valid": self.valid,
            "route_count": len(self.routes),
            "mutating_route_count": len(mutating),
            "by_kind": dict(sorted(by_kind.items())),
            "by_method": dict(sorted(by_method.items())),
            "errors": list(self.errors),
            "routes": [asdict(route) for route in self.routes],
        }


def _key(method: str, path: str, name: str) -> RouteKey:
    return RouteKey(method=method, path=path, name=name)


# This is intentionally an exact allowlist. New public routes must be reviewed
# and added with a reason; a URL prefix alone can never grant public access.
PUBLIC_ALLOWLIST = (
    AllowlistEntry(_key("GET", "/api/health", "health"), "Read-only health probe."),
    AllowlistEntry(
        _key("POST", "/api/auth/login", "login"),
        "Credential exchange must be reachable before authentication.",
    ),
    AllowlistEntry(
        _key("GET", "/api/signing/{token}", "signing_summary"),
        "Capability-token signing summary; the signed token is the domain authorization.",
    ),
    AllowlistEntry(
        _key("POST", "/api/signing/{token}", "submit_signature"),
        "Capability-token signature submission; the signed token is the domain authorization.",
    ),
    AllowlistEntry(
        _key("POST", "/api/signing/{token}/confirm", "confirm_signature"),
        "Capability-token signature confirmation; the signed token is the domain authorization.",
    ),
    AllowlistEntry(
        _key("POST", "/api/signing/{token}/reject", "reject_signature"),
        "Capability-token signature rejection; the signed token is the domain authorization.",
    ),
    AllowlistEntry(_key("GET", "/openapi.json", "openapi"), "FastAPI API schema."),
    AllowlistEntry(_key("HEAD", "/openapi.json", "openapi"), "FastAPI API schema."),
    AllowlistEntry(_key("GET", "/docs", "swagger_ui_html"), "FastAPI API documentation."),
    AllowlistEntry(_key("HEAD", "/docs", "swagger_ui_html"), "FastAPI API documentation."),
    AllowlistEntry(
        _key("GET", "/docs/oauth2-redirect", "swagger_ui_redirect"),
        "FastAPI documentation OAuth redirect helper.",
    ),
    AllowlistEntry(
        _key("HEAD", "/docs/oauth2-redirect", "swagger_ui_redirect"),
        "FastAPI documentation OAuth redirect helper.",
    ),
    AllowlistEntry(_key("GET", "/redoc", "redoc_html"), "FastAPI ReDoc documentation."),
    AllowlistEntry(_key("HEAD", "/redoc", "redoc_html"), "FastAPI ReDoc documentation."),
    AllowlistEntry(
        _key("GET", "/assets/{path:path}", "assets"),
        "Compiled public frontend assets.",
        optional=True,
    ),
    AllowlistEntry(
        _key("HEAD", "/assets/{path:path}", "assets"),
        "Compiled public frontend assets.",
        optional=True,
    ),
    AllowlistEntry(
        _key("GET", "/{full_path:path}", "spa"),
        "Public SPA shell and PWA files; API authorization remains server-side.",
        optional=True,
    ),
)


# These mutations have narrower domain checks inside their endpoint bodies.
# Keeping the exact method/path/name here makes each exception reviewable.
AUTHENTICATED_SPECIAL_MUTATIONS = (
    AllowlistEntry(
        _key("POST", "/api/auth/change-password", "change_password"),
        "Authenticated self-service password change with current-password validation.",
    ),
    AllowlistEntry(
        _key("PATCH", "/api/users/me/preferences", "update_user_preferences"),
        "Authenticated self-service language preference update.",
    ),
    AllowlistEntry(
        _key("PUT", "/api/users/me/profile", "complete_my_profile"),
        "Authenticated self-service profile completion with legal-name controls.",
    ),
    AllowlistEntry(
        _key("POST", "/api/emergency-access/start", "start_emergency_access"),
        "Authenticated owner-only emergency workflow with reauthentication and audit.",
    ),
    AllowlistEntry(
        _key("POST", "/api/emergency-access/{session_id}/end", "end_emergency_access"),
        "Authenticated owner-only emergency session closure with audit.",
    ),
    AllowlistEntry(
        _key("POST", "/api/owner/transfer", "transfer_owner"),
        "Authenticated current-owner transfer with reauthentication and row locking.",
    ),
    AllowlistEntry(
        _key("POST", "/api/license/install", "install_license"),
        "Authenticated owner-administrator licence installation with signature validation.",
    ),
)


def _dependency_calls(dependant: Dependant) -> Iterable[object]:
    if dependant.call is not None:
        yield dependant.call
    for child in dependant.dependencies:
        yield from _dependency_calls(child)


def _route_dependencies(route: APIRoute) -> tuple[set[str], bool]:
    permissions: set[str] = set()
    authenticated = False
    for call in _dependency_calls(route.dependant):
        permission = getattr(call, "__assetcore_permission__", None)
        if permission:
            permissions.add(str(permission))
        if call is get_authenticated_user or call is get_current_active_user:
            authenticated = True
    return permissions, authenticated


def _lookup(entries: tuple[AllowlistEntry, ...]) -> dict[RouteKey, AllowlistEntry]:
    return {entry.key: entry for entry in entries}


def _route_rows(
    app: FastAPI,
) -> tuple[list[tuple[RouteKey, APIRoute | Route | Mount]], list[str]]:
    rows: list[tuple[RouteKey, APIRoute | Route | Mount]] = []
    errors: list[str] = []
    for route in app.routes:
        if isinstance(route, Mount):
            # StaticFiles handles GET and HEAD below the mount. Represent those
            # methods explicitly so they are visible in the inventory.
            path = f"{route.path.rstrip('/')}/{{path:path}}"
            rows.extend(
                (_key(method, path, route.name or ""), route) for method in ("GET", "HEAD")
            )
            continue
        if not isinstance(route, Route):
            errors.append(
                "Unsupported route type requires an explicit authorization policy: "
                f"{type(route).__name__} {getattr(route, 'path', '<unknown>')}"
            )
            continue
        rows.extend(
            (_key(method, route.path, route.name or ""), route)
            for method in sorted(route.methods or ())
        )
    return rows, errors


def build_authorization_inventory(app: FastAPI) -> AuthorizationInventory:
    public = _lookup(PUBLIC_ALLOWLIST)
    special = _lookup(AUTHENTICATED_SPECIAL_MUTATIONS)
    seen: set[RouteKey] = set()
    results: list[RouteAuthorization] = []
    route_rows, route_errors = _route_rows(app)
    errors: list[str] = list(route_errors)

    for key, route in route_rows:
        seen.add(key)
        mutating = key.method in MUTATING_METHODS
        permissions: set[str] = set()
        authenticated = False
        if isinstance(route, APIRoute):
            permissions, authenticated = _route_dependencies(route)

        if permissions:
            kind = AuthorizationKind.PERMISSION
            permission = ",".join(sorted(permissions))
            reason = "FastAPI dependency enforces the listed centralized permission."
        elif key in special:
            kind = AuthorizationKind.AUTHENTICATED_SPECIAL
            permission = None
            reason = special[key].reason
            if not authenticated:
                errors.append(f"Special route is not authenticated: {key}")
                kind = AuthorizationKind.UNCLASSIFIED
        elif authenticated and not mutating:
            kind = AuthorizationKind.AUTHENTICATED
            permission = None
            reason = "Authenticated read with endpoint-specific owner/self/domain filtering."
        elif key in public:
            entry = public[key]
            kind = (
                AuthorizationKind.STATIC_PUBLIC
                if isinstance(route, Mount) or key.name == "spa"
                else AuthorizationKind.PUBLIC_EXEMPT
            )
            permission = None
            reason = entry.reason
        else:
            kind = AuthorizationKind.UNCLASSIFIED
            permission = None
            reason = "No reviewed authorization policy was found."
            errors.append(f"Unclassified route: {key.method} {key.path} ({key.name})")

        results.append(
            RouteAuthorization(
                method=key.method,
                path=key.path,
                name=key.name,
                kind=kind.value,
                permission=permission,
                reason=reason,
                mutating=mutating,
            )
        )

    for entry in (*PUBLIC_ALLOWLIST, *AUTHENTICATED_SPECIAL_MUTATIONS):
        if not entry.optional and entry.key not in seen:
            errors.append(
                "Stale authorization allowlist entry: "
                f"{entry.key.method} {entry.key.path} ({entry.key.name})"
            )

    results.sort(key=lambda item: (item.path, item.method, item.name))
    return AuthorizationInventory(routes=tuple(results), errors=tuple(sorted(errors)))
