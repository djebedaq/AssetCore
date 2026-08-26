from __future__ import annotations

from collections.abc import Iterable
from urllib.parse import urlsplit

from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from .settings import Settings

ALLOWED_CORS_METHODS = ("GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS")
ALLOWED_CORS_HEADERS = (
    "Accept",
    "Accept-Language",
    "Authorization",
    "Content-Type",
    "X-Correlation-ID",
)
EXPOSED_CORS_HEADERS = (
    "Content-Disposition",
    "X-AssetCore-License-State",
    "X-Diagnostic-ID",
)

# React uses style attributes for progress indicators and verified diagram
# coordinates. No inline script or eval permission is granted. Blob object/image
# sources are required by authenticated PDF previews and catalog diagrams.
CONTENT_SECURITY_POLICY = "; ".join(
    (
        "default-src 'self'",
        "base-uri 'self'",
        "form-action 'self'",
        "frame-ancestors 'none'",
        "script-src 'self'",
        "style-src 'self' 'unsafe-inline'",
        "img-src 'self' data: blob:",
        "font-src 'self'",
        "connect-src 'self'",
        "worker-src 'self'",
        "manifest-src 'self'",
        "object-src 'self' blob:",
        "media-src 'self' blob:",
    )
)


def normalize_origin(value: str) -> str:
    candidate = value.strip()
    if not candidate or candidate == "*":
        raise ValueError("CORS origin must be an explicit http(s) origin")
    parsed = urlsplit(candidate)
    if parsed.scheme.casefold() not in {"http", "https"}:
        raise ValueError(f"CORS origin has an unsupported scheme: {candidate!r}")
    if (
        not parsed.hostname
        or "*" in parsed.hostname
        or parsed.username
        or parsed.password
    ):
        raise ValueError(f"CORS origin must contain only a host and optional port: {candidate!r}")
    if parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
        raise ValueError(f"CORS origin must not contain a path, query or fragment: {candidate!r}")
    try:
        port = parsed.port
    except ValueError as exc:
        raise ValueError(f"CORS origin has an invalid port: {candidate!r}") from exc
    scheme = parsed.scheme.casefold()
    hostname = parsed.hostname.casefold()
    rendered_host = f"[{hostname}]" if ":" in hostname else hostname
    default_port = 80 if scheme == "http" else 443
    suffix = f":{port}" if port is not None and port != default_port else ""
    return f"{scheme}://{rendered_host}{suffix}"


def _split_origins(value: str | None) -> Iterable[str]:
    if not value:
        return ()
    return (item for item in value.split(",") if item.strip())


def configured_cors_origins(configuration: Settings) -> tuple[str, ...]:
    if configuration.frontend_origins is not None:
        configured = list(_split_origins(configuration.frontend_origins))
    else:
        configured = [configuration.frontend_origin]
    if configuration.deployment_environment in {"development", "test"}:
        # Vite's preview port is a development-only convenience. It is never
        # injected into staging or production.
        configured.append("http://localhost:4173")

    normalized: list[str] = []
    for value in configured:
        origin = normalize_origin(value)
        if origin not in normalized:
            normalized.append(origin)
    if not normalized:
        raise ValueError("At least one explicit CORS origin is required")
    return tuple(normalized)


def is_production_https(configuration: Settings, scope: Scope) -> bool:
    production = configuration.production_mode or (
        configuration.deployment_environment == "production"
    )
    return production and scope.get("scheme") == "https"


class WebSecurityMiddleware:
    """Apply browser guardrails without changing authentication/session semantics."""

    def __init__(self, app: ASGIApp, configuration: Settings) -> None:
        self.app = app
        self.configuration = configuration

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = str(scope.get("path", ""))

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                headers["X-Content-Type-Options"] = "nosniff"
                headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
                headers["Permissions-Policy"] = (
                    "camera=(), microphone=(), geolocation=(), payment=(), "
                    "usb=(), serial=()"
                )
                headers["Content-Security-Policy"] = CONTENT_SECURITY_POLICY
                headers["X-Frame-Options"] = "DENY"
                headers["X-Permitted-Cross-Domain-Policies"] = "none"

                if is_production_https(self.configuration, scope):
                    headers["Strict-Transport-Security"] = (
                        "max-age=31536000; includeSubDomains"
                    )

                if path.startswith("/api/"):
                    headers["Cache-Control"] = "private, no-store, max-age=0"
                    headers["Pragma"] = "no-cache"
                    headers["Expires"] = "0"
                elif path.startswith("/assets/") and 200 <= message["status"] < 300:
                    headers["Cache-Control"] = "public, max-age=31536000, immutable"
                else:
                    # The SPA shell, manifest and service worker must be
                    # revalidated so deployments and PWA updates are detected.
                    headers["Cache-Control"] = "no-cache"
            await send(message)

        await self.app(scope, receive, send_with_headers)
