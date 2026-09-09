"""Read-only production probes, also sent on stdin to a previous release image."""

from __future__ import annotations

import json
import sys
import urllib.request


def smoke() -> None:
    # Loopback-only probes; never follow a redirect to a public host.
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *_args, **_kwargs):
            return None

    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    for path, expected in (("/api/ready", "ready"), ("/api/health", "ok")):
        with opener.open(f"http://127.0.0.1:10000{path}", timeout=5) as response:
            if response.status != 200 or json.load(response).get("status") != expected:
                raise ValueError("probe_failed")
    with opener.open("http://127.0.0.1:10000/", timeout=5) as response:
        if response.status != 200 or b"<html" not in response.read(65536).lower():
            raise ValueError("shell_probe_failed")


def database_state(mode: str, actor: int | None = None) -> dict:
    from app.settings import settings
    from sqlalchemy import create_engine, text
    from sqlalchemy.engine import make_url

    if not settings.production_mode or settings.migration_strategy != "external":
        raise ValueError("production_configuration_required")
    url = make_url(settings.database_url)
    # This runbook owns a Compose PostgreSQL installation, not an arbitrary remote DB.
    if (url.host, url.port or 5432, url.database) != ("db", 5432, "assetcore"):
        raise ValueError("compose_database_required")
    engine = create_engine(url, connect_args={"connect_timeout": 10})
    try:
        with engine.connect() as connection:
            connection.execute(text("SET TRANSACTION READ ONLY"))
            relation_count = connection.scalar(text(
                "SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
                "WHERE n.nspname NOT LIKE 'pg_%' AND n.nspname <> 'information_schema' "
                "AND c.relkind IN ('r','p','v','m','S','f')"
            ))
            if mode == "empty":
                if relation_count:
                    raise ValueError("initialization_requires_empty_database")
                return {"empty": True}
            revisions = list(connection.scalars(text("SELECT version_num FROM alembic_version")))
            if len(revisions) != 1:
                raise ValueError("single_existing_revision_required")
            if actor is not None and not connection.scalar(text(
                "SELECT id FROM users WHERE id=:actor AND is_active=true"
            ), {"actor": actor}):
                raise ValueError("active_audit_actor_required")
            identity = list(connection.execute(text(
                "SELECT current_database(), inet_server_addr()::text, inet_server_port(), "
                "(SELECT oid FROM pg_database WHERE datname=current_database())"
            )).one())
            return {"revision": revisions[0], "identity": identity}
    finally:
        engine.dispose()


def main() -> int:
    try:
        mode = sys.argv[1]
        if mode == "smoke":
            smoke()
            result = {"runtime_ready": True, "fully_commissioned": False}
        elif mode in {"empty", "existing"}:
            result = database_state(mode, int(sys.argv[2]) if len(sys.argv) > 2 else None)
        else:
            raise ValueError("invalid_probe")
        print(json.dumps(result))
        return 0
    except Exception:
        # No SQLAlchemy/settings exception, connection URL, or personal data in logs.
        print("production_probe_failed", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
