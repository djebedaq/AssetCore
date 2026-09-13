"""Fail-closed PostgreSQL 16 operational checks; output contains only safe versions.

This module is deliberately standalone so deployment can pipe the committed source
to a previous immutable image and inspect its tools without trusting old scripts.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
from pathlib import Path

from psycopg.conninfo import conninfo_to_dict
from sqlalchemy import create_engine, text

SUPPORTED_MAJOR = 16
TOOLS = {"pg_dump": "PG_DUMP", "pg_restore": "PG_RESTORE", "psql": "PSQL"}
PG_PARAMETERS = {
    "dbname": "PGDATABASE", "host": "PGHOST", "hostaddr": "PGHOSTADDR",
    "port": "PGPORT", "user": "PGUSER", "password": "PGPASSWORD",
    "passfile": "PGPASSFILE", "service": "PGSERVICE", "options": "PGOPTIONS",
    "application_name": "PGAPPNAME", "client_encoding": "PGCLIENTENCODING",
    "connect_timeout": "PGCONNECT_TIMEOUT", "sslmode": "PGSSLMODE",
    "sslcert": "PGSSLCERT", "sslkey": "PGSSLKEY", "sslrootcert": "PGSSLROOTCERT",
    "sslcrl": "PGSSLCRL", "sslcrldir": "PGSSLCRLDIR",
    "sslsni": "PGSSLSNI", "sslcompression": "PGSSLCOMPRESSION",
    "ssl_min_protocol_version": "PGSSLMINPROTOCOLVERSION",
    "ssl_max_protocol_version": "PGSSLMAXPROTOCOLVERSION",
    "channel_binding": "PGCHANNELBINDING", "gssencmode": "PGGSSENCMODE",
    "krbsrvname": "PGKRBSRVNAME", "gsslib": "PGGSSLIB",
    "target_session_attrs": "PGTARGETSESSIONATTRS",
}


class ToolchainError(RuntimeError):
    """Controlled error codes only; never include subprocess/connection details."""


def parse_version(value: str) -> dict:
    """Extract a stable numeric release, excluding package/vendor strings."""
    match = re.fullmatch(r"([1-9][0-9]?)\.([0-9]{1,3})(?:\.([0-9]{1,3}))?", value)
    if not match:
        raise ToolchainError("postgresql_tool_version_invalid")
    return {"major": int(match[1]), "version": value}


def parse_tool_version(tool: str, output: str) -> dict:
    if tool not in TOOLS or not isinstance(output, str) or len(output) > 512:
        raise ToolchainError("postgresql_tool_version_invalid")
    match = re.fullmatch(
        rf"{re.escape(tool)} \(PostgreSQL\) ([0-9.]+)(?: \([^\r\n]*\))?\r?\n?",
        output,
    )
    if not match:
        raise ToolchainError("postgresql_tool_version_invalid")
    return parse_version(match[1])


def tool_executable(tool: str) -> str:
    if tool not in TOOLS:
        raise ToolchainError("postgresql_tool_unknown")
    return os.environ.get(TOOLS[tool], tool)


def inspect_tool(tool: str) -> dict:
    try:
        result = subprocess.run(
            [tool_executable(tool), "--version"], capture_output=True,
            text=True, timeout=15, check=False,
            env={**os.environ, "LC_ALL": "C"},
        )
    except (OSError, subprocess.SubprocessError, UnicodeError):
        raise ToolchainError("postgresql_tool_version_unavailable") from None
    if result.returncode:
        raise ToolchainError("postgresql_tool_version_unavailable")
    return parse_tool_version(tool, result.stdout)


def postgres_environment(database_url: str) -> dict[str, str]:
    """Keep libpq credentials in the child environment, never in argv or output.

    Unknown connection options fail closed instead of silently dropping e.g. a
    transport-security setting. Version probes and pg_dump/restore use the same
    configured database, including supported libpq URI query parameters.
    """
    if not database_url.startswith(("postgresql://", "postgresql+psycopg://", "postgres://")):
        raise ToolchainError("postgresql_database_url_required")
    try:
        parameters = conninfo_to_dict(database_url.replace("postgresql+psycopg://", "postgresql://", 1))
    except Exception:
        raise ToolchainError("postgresql_database_url_invalid") from None
    if any(key not in PG_PARAMETERS for key in parameters) or not parameters.get("dbname"):
        raise ToolchainError("postgresql_connection_options_unsupported")
    environment = os.environ.copy()
    for key, value in parameters.items():
        environment[PG_PARAMETERS[key]] = value
    environment.setdefault("PGCONNECT_TIMEOUT", "10")
    return environment


def inspect_server(database_url: str) -> dict:
    # Normalize both libpq URL spellings to the installed psycopg3 SQLAlchemy driver.
    postgres_environment(database_url)
    url = re.sub(r"^(?:postgresql(?:\+psycopg)?|postgres)://", "postgresql+psycopg://", database_url)
    engine = None
    try:
        engine = create_engine(url, connect_args={"connect_timeout": 10}, hide_parameters=True)
        with engine.connect() as connection:
            value = str(connection.execute(text("SHOW server_version_num")).scalar_one())
        if not re.fullmatch(r"[1-9][0-9]{5,6}", value):
            raise ValueError
        number = int(value)
        major, minor = divmod(number, 10000)
        return {"major": major, "version": f"{major}.{minor}"}
    except Exception:
        raise ToolchainError("postgresql_server_version_unavailable") from None
    finally:
        if engine is not None:
            engine.dispose()


def check_compatibility(
    database_url: str, tools: tuple[str, ...] = ("pg_dump", "pg_restore", "psql"),
) -> dict:
    if not tools:
        raise ToolchainError("postgresql_toolchain_required")
    versions = {tool: inspect_tool(tool) for tool in tools}
    versions["server"] = inspect_server(database_url)
    if any(version["major"] != SUPPORTED_MAJOR for version in versions.values()):
        raise ToolchainError("postgresql_toolchain_incompatible")
    return versions


def check_clients(tools: tuple[str, ...] = ("pg_dump", "pg_restore", "psql")) -> dict:
    if not tools:
        raise ToolchainError("postgresql_toolchain_required")
    versions = {tool: inspect_tool(tool) for tool in tools}
    if any(version["major"] != SUPPORTED_MAJOR for version in versions.values()):
        raise ToolchainError("postgresql_toolchain_incompatible")
    return versions


def check_archive_compatibility(dump: Path, manifest: dict) -> dict:
    """Read custom-archive metadata without connecting to or modifying a DB.

    A v1 manifest may predate provenance. Its actual archive header still must
    prove a PostgreSQL 16 server and producer; cryptographic validity is separate.
    """
    try:
        result = subprocess.run(
            [tool_executable("pg_restore"), "--list", str(dump)],
            capture_output=True, text=True, timeout=60, check=False,
            env={**os.environ, "LC_ALL": "C"},
        )
    except (OSError, subprocess.SubprocessError, UnicodeError):
        raise ToolchainError("postgresql_archive_version_unavailable") from None
    if result.returncode:
        raise ToolchainError("postgresql_archive_version_unavailable")
    versions = {}
    for key, label in (("server", "Dumped from database version"), ("pg_dump", "Dumped by pg_dump version")):
        matches = re.findall(rf"^;\s+{label}: ([0-9.]+)(?: [^\r\n]*)?$", result.stdout, flags=re.MULTILINE)
        if len(matches) != 1:
            raise ToolchainError("postgresql_archive_version_unavailable")
        versions[key] = parse_version(matches[0])
    if any(version["major"] != SUPPORTED_MAJOR for version in versions.values()):
        raise ToolchainError("postgresql_archive_incompatible")
    if "postgresql" in manifest:
        provenance = manifest["postgresql"]
        if not isinstance(provenance, dict):
            raise ToolchainError("postgresql_archive_provenance_invalid")
        for key in ("server", "pg_dump"):
            # Only the supported major is contractual; a patch update between
            # the live read-only probe and pg_dump is harmless.
            observed = provenance.get(key)
            if not isinstance(observed, dict) or observed.get("major") != SUPPORTED_MAJOR:
                raise ToolchainError("postgresql_archive_provenance_invalid")
            if parse_version(str(observed.get("version", "")))["major"] != SUPPORTED_MAJOR:
                raise ToolchainError("postgresql_archive_provenance_invalid")
    return versions


def main() -> None:
    parser = argparse.ArgumentParser(description="Check the PostgreSQL 16 operational contract")
    parser.add_argument("--tools", nargs="+", choices=tuple(TOOLS), default=list(TOOLS))
    parser.add_argument("--clients-only", action="store_true", help="Image build assertion without a database connection")
    args = parser.parse_args()
    try:
        versions = (check_clients(tuple(args.tools)) if args.clients_only else
                    check_compatibility(os.environ.get("DATABASE_URL", ""), tuple(args.tools)))
    except ToolchainError as exc:
        raise SystemExit(str(exc)) from None
    print(json.dumps(versions, sort_keys=True))


if __name__ == "__main__":
    main()
