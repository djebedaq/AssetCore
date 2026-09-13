from __future__ import annotations

import base64
import hashlib
import io
import json
import subprocess
import sys
import tarfile
from pathlib import Path
from types import SimpleNamespace

import pytest
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from scripts import backup_assetcore as backup
from scripts import postgres_toolchain as pg
from scripts import restore_assetcore as restore
from scripts import verify_backup as verifier

TEST_URL = "postgresql+psycopg://qa_user:test-credential-sentinel@localhost/assetcore_test"
VERSION = {"major": 16, "version": "16.15"}
PROVENANCE = {name: dict(VERSION) for name in ("server", "pg_dump", "pg_restore", "psql")}


def archive_listing(producer: str = "16.15", server: str = "16.15") -> str:
    return (
        "; Archive created at a test timestamp\n"
        f";     Dumped from database version: {server} (test package)\n"
        f";     Dumped by pg_dump version: {producer} (test package)\n"
    )


def encrypted_backup(tmp_path, monkeypatch, *, provenance=None, valid_checksum=True):
    key = bytes(range(32))
    monkeypatch.setenv("BACKUP_ENCRYPTION_KEY", base64.b64encode(key).decode())
    dump = b"isolated technical test archive"
    manifest = {
        "format": "assetcore-backup-v1",
        "database_sha256": hashlib.sha256(dump if valid_checksum else b"altered").hexdigest(),
        "documents_included": False,
    }
    if provenance is not None:
        manifest["postgresql"] = provenance
    payload = io.BytesIO()
    with tarfile.open(fileobj=payload, mode="w:gz") as bundle:
        for name, content in (("database.dump", dump), ("manifest.json", json.dumps(manifest).encode())):
            member = tarfile.TarInfo(name)
            member.size = len(content)
            bundle.addfile(member, io.BytesIO(content))
    nonce = bytes(range(12))
    target = tmp_path / "isolated.acbackup"
    target.write_bytes(b"ASSETCORE-BACKUP-1\n" + nonce + AESGCM(key).encrypt(nonce, payload.getvalue(), b"AssetCore backup v1"))
    return target, manifest


@pytest.fixture
def operational_tools(monkeypatch):
    calls = []
    audits = []
    monkeypatch.setenv("DATABASE_URL", TEST_URL)
    monkeypatch.setenv("BACKUP_ENCRYPTION_KEY", base64.b64encode(bytes(range(32))).decode())
    for variable in pg.TOOLS.values():
        monkeypatch.delenv(variable, raising=False)
    monkeypatch.setattr(pg, "inspect_server", lambda url: dict(VERSION))

    def run(command, **kwargs):
        calls.append((command, kwargs))
        if "--version" in command:
            return SimpleNamespace(returncode=0, stdout=f"{command[0]} (PostgreSQL) 16.15\n")
        if "--list" in command:
            return SimpleNamespace(returncode=0, stdout=archive_listing())
        if "--file" in command:
            Path(command[command.index("--file") + 1]).write_bytes(b"isolated test dump")
        return SimpleNamespace(returncode=0, stdout=b"", stderr=b"")

    monkeypatch.setattr(pg.subprocess, "run", run)
    monkeypatch.setattr(backup, "record_operation", lambda *args: audits.append(args))
    monkeypatch.setattr(restore, "record_operation", lambda *args: audits.append(args))
    return calls, audits


@pytest.mark.parametrize("tool,output,version", [
    ("pg_dump", "pg_dump (PostgreSQL) 16.15\n", "16.15"),
    ("pg_restore", "pg_restore (PostgreSQL) 16.3 (Debian 16.3-1.pgdg12+1)\n", "16.3"),
    ("psql", "psql (PostgreSQL) 17.11 (Debian 17.11-1)\r\n", "17.11"),
    ("pg_dump", "pg_dump (PostgreSQL) 9.6.24", "9.6.24"),
])
def test_safe_numeric_version_parsing(tool, output, version):
    assert pg.parse_tool_version(tool, output) == {"major": int(version.split(".")[0]), "version": version}


@pytest.mark.parametrize("output", [
    "", "16.15", "pg_restore (PostgreSQL) 16.15", "pg_dump (PostgreSQL) 16beta1",
    "pg_dump (PostgreSQL) 16", "pg_dump (PostgreSQL) 16.1.2.3",
    "prefix pg_dump (PostgreSQL) 16.15", "pg_dump (PostgreSQL) 16.15\nsecret-sentinel",
    "pg_dump (PostgreSQL) 16.15 " + "x" * 600,
])
def test_malformed_tool_versions_fail_closed_without_echo(output):
    with pytest.raises(pg.ToolchainError) as error:
        pg.parse_tool_version("pg_dump", output)
    assert str(error.value) == "postgresql_tool_version_invalid"


@pytest.mark.parametrize("failure", [
    OSError("test-credential-sentinel"),
    subprocess.TimeoutExpired("test-credential-sentinel", 15),
    UnicodeError("test-credential-sentinel"),
])
def test_unavailable_tool_version_does_not_leak(monkeypatch, failure):
    def run(*args, **kwargs):
        raise failure
    monkeypatch.setattr(pg.subprocess, "run", run)
    with pytest.raises(pg.ToolchainError, match="^postgresql_tool_version_unavailable$"):
        pg.inspect_tool("pg_dump")


def test_nonzero_tool_version_does_not_echo_stderr(monkeypatch):
    monkeypatch.setattr(pg.subprocess, "run", lambda *args, **kwargs: SimpleNamespace(
        returncode=1, stdout=TEST_URL, stderr=TEST_URL,
    ))
    with pytest.raises(pg.ToolchainError, match="^postgresql_tool_version_unavailable$"):
        pg.inspect_tool("pg_dump")


def test_16_clients_and_server_accepted(operational_tools):
    assert pg.check_compatibility(TEST_URL) == PROVENANCE


@pytest.mark.parametrize("component,major", [("server", 17), ("server", 15), ("pg_dump", 17), ("pg_restore", 17), ("psql", 18)])
def test_exact_16_contract_rejects_mismatches(monkeypatch, component, major):
    monkeypatch.setattr(pg, "inspect_tool", lambda tool: {"major": major if tool == component else 16, "version": "numeric"})
    monkeypatch.setattr(pg, "inspect_server", lambda url: {"major": major if component == "server" else 16, "version": "numeric"})
    with pytest.raises(pg.ToolchainError, match="^postgresql_toolchain_incompatible$"):
        pg.check_compatibility(TEST_URL)


def test_clients_only_does_not_connect_to_database(monkeypatch, operational_tools, capsys):
    def forbidden(*args):
        pytest.fail("Image build assertion must not access a database")
    monkeypatch.setattr(pg, "inspect_server", forbidden)
    monkeypatch.setattr(sys, "argv", ["postgres_toolchain.py", "--clients-only"])
    pg.main()
    assert set(json.loads(capsys.readouterr().out)) == {"pg_dump", "pg_restore", "psql"}


def test_server_probe_is_read_only_and_discards_package_details(monkeypatch):
    queries = []
    options = []

    class Connection:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def execute(self, query):
            queries.append(str(query))
            return SimpleNamespace(scalar_one=lambda: "160015")

    def create_engine(url, **kwargs):
        options.append(kwargs)
        return SimpleNamespace(connect=Connection, dispose=lambda: None)

    monkeypatch.setattr(pg, "create_engine", create_engine)
    assert pg.inspect_server(TEST_URL) == VERSION
    assert queries == ["SHOW server_version_num"]
    assert options[0]["hide_parameters"] is True


def test_server_connection_errors_do_not_leak_credentials(monkeypatch):
    def fail(*args, **kwargs):
        raise RuntimeError(TEST_URL)
    monkeypatch.setattr(pg, "create_engine", fail)
    with pytest.raises(pg.ToolchainError, match="^postgresql_server_version_unavailable$"):
        pg.inspect_server(TEST_URL)


def test_connection_options_and_credentials_stay_in_child_environment():
    environment = pg.postgres_environment("postgresql://qa_user:p%40ss@localhost:5432/assetcore_test?sslmode=require")
    assert environment["PGUSER"] == "qa_user"
    assert environment["PGPASSWORD"] == "p@ss"
    assert environment["PGDATABASE"] == "assetcore_test"
    assert environment["PGSSLMODE"] == "require"
    assert environment["PGPORT"] == "5432"


@pytest.mark.parametrize("url", ["sqlite:///test.db", "postgresql://", "postgresql://localhost/test?unsupported=secret-sentinel"])
def test_unsupported_connection_configuration_fails_closed(url):
    with pytest.raises(pg.ToolchainError) as error:
        pg.postgres_environment(url)
    assert "secret-sentinel" not in str(error.value)


def test_backup_mismatch_prevents_dump_and_publication(tmp_path, monkeypatch, operational_tools, capsys):
    calls, audits = operational_tools
    monkeypatch.setattr(pg, "inspect_tool", lambda tool: {"major": 17, "version": "17.11"})
    output = tmp_path / "unpublished"
    monkeypatch.setattr(sys, "argv", ["backup_assetcore.py", "--output-dir", str(output), "--actor-user-id", "1"])
    with pytest.raises(SystemExit, match="postgresql_toolchain_incompatible") as error:
        backup.main()
    assert not output.exists()
    assert not calls and not audits
    assert "test-credential-sentinel" not in str(error.value) + capsys.readouterr().out


def test_backup_checks_actual_archive_before_publication(tmp_path, monkeypatch, operational_tools):
    calls, audits = operational_tools
    monkeypatch.setattr(backup, "check_archive_compatibility", lambda *args: (_ for _ in ()).throw(pg.ToolchainError("postgresql_archive_incompatible")))
    monkeypatch.setattr(sys, "argv", ["backup_assetcore.py", "--output-dir", str(tmp_path), "--actor-user-id", "1"])
    with pytest.raises(SystemExit, match="postgresql_archive_incompatible"):
        backup.main()
    assert any("--file" in command for command, _ in calls)
    assert not list(tmp_path.glob("*.acbackup"))
    assert not audits


def test_backup_provenance_is_authenticated_without_format_change(tmp_path, monkeypatch, operational_tools):
    calls, audits = operational_tools
    monkeypatch.setattr(sys, "argv", ["backup_assetcore.py", "--output-dir", str(tmp_path), "--actor-user-id", "1"])
    backup.main()
    created = list(tmp_path.glob("*.acbackup"))
    assert len(created) == 1
    manifest = verifier.verify(created[0])
    assert manifest["format"] == "assetcore-backup-v1"
    assert manifest["postgresql"] == PROVENANCE
    assert "test-credential-sentinel" not in json.dumps(manifest)
    dump_command, kwargs = next((command, kwargs) for command, kwargs in calls if "--file" in command)
    assert "test-credential-sentinel" not in str(dump_command)
    assert kwargs["capture_output"] is True
    assert kwargs["env"]["PGDATABASE"] == "assetcore_test"
    assert len(audits) == 1


@pytest.mark.parametrize("with_provenance", [False, True])
def test_existing_v1_cryptographic_verification_does_not_require_tools(tmp_path, monkeypatch, with_provenance):
    path, manifest = encrypted_backup(tmp_path, monkeypatch, provenance=PROVENANCE if with_provenance else None)
    monkeypatch.setattr(pg.subprocess, "run", lambda *args, **kwargs: pytest.fail("Crypto verification must remain offline"))
    assert verifier.verify(path) == manifest


@pytest.mark.parametrize("authenticated", [False, True])
def test_crypto_or_checksum_failure_precedes_compatibility_check(tmp_path, monkeypatch, authenticated):
    path, _ = encrypted_backup(tmp_path, monkeypatch, valid_checksum=False)
    if not authenticated:
        encrypted = path.read_bytes()
        path.write_bytes(encrypted[:-1] + bytes([encrypted[-1] ^ 1]))
    monkeypatch.setattr(pg.subprocess, "run", lambda *args, **kwargs: pytest.fail("Invalid encrypted archive must not reach tools"))
    with pytest.raises(SystemExit, match="authentication failed|checksum verification failed"):
        verifier.verify(path, require_postgres_compatible=True)


def test_restore_mismatch_precedes_any_destructive_call(tmp_path, monkeypatch, operational_tools):
    calls, audits = operational_tools
    path, _ = encrypted_backup(tmp_path, monkeypatch)
    monkeypatch.setattr(pg, "inspect_tool", lambda tool: {"major": 17, "version": "17.11"})
    monkeypatch.setattr(sys, "argv", ["restore_assetcore.py", str(path), "--confirm", "RESTORE_ASSETCORE", "--actor-user-id", "1"])
    with pytest.raises(SystemExit, match="postgresql_toolchain_incompatible"):
        restore.main()
    assert not any("--clean" in command for command, _ in calls)
    assert not audits


def test_restore_authentication_precedes_toolchain_check(tmp_path, monkeypatch, operational_tools):
    calls, _ = operational_tools
    path, _ = encrypted_backup(tmp_path, monkeypatch)
    payload = path.read_bytes()
    path.write_bytes(payload[:-1] + bytes([payload[-1] ^ 1]))
    monkeypatch.setattr(sys, "argv", ["restore_assetcore.py", str(path), "--confirm", "RESTORE_ASSETCORE", "--actor-user-id", "1"])
    with pytest.raises(SystemExit, match="authentication failed"):
        restore.main()
    assert not calls


@pytest.mark.parametrize("producer,server", [("17.11", "16.15"), ("16.15", "15.8")])
def test_legacy_incompatible_archive_refused_by_restore_before_clean(tmp_path, monkeypatch, operational_tools, producer, server):
    calls, audits = operational_tools
    path, _ = encrypted_backup(tmp_path, monkeypatch)
    original = pg.subprocess.run

    def run(command, **kwargs):
        if "--list" in command:
            calls.append((command, kwargs))
            return SimpleNamespace(returncode=0, stdout=archive_listing(producer, server))
        return original(command, **kwargs)

    monkeypatch.setattr(pg.subprocess, "run", run)
    monkeypatch.setattr(sys, "argv", ["restore_assetcore.py", str(path), "--confirm", "RESTORE_ASSETCORE", "--actor-user-id", "1"])
    with pytest.raises(SystemExit, match="postgresql_archive_incompatible"):
        restore.main()
    assert not any("--clean" in command for command, _ in calls)
    assert not audits


def test_legacy_16_restore_keeps_destructive_flags_and_private_connection(tmp_path, monkeypatch, operational_tools):
    calls, audits = operational_tools
    path, _ = encrypted_backup(tmp_path, monkeypatch)
    monkeypatch.setattr(sys, "argv", ["restore_assetcore.py", str(path), "--confirm", "RESTORE_ASSETCORE", "--actor-user-id", "1"])
    restore.main()
    command, kwargs = next((command, kwargs) for command, kwargs in calls if "--clean" in command)
    assert {"--clean", "--if-exists", "--exit-on-error"}.issubset(command)
    assert "test-credential-sentinel" not in str(command)
    assert "qa_user" not in str(command)
    assert kwargs["capture_output"] is True
    assert kwargs["env"]["PGUSER"] == "qa_user"
    assert len(audits) == 1


@pytest.mark.parametrize("output", ["", "; Dumped by pg_dump version: 16.15\n", archive_listing() + archive_listing()])
def test_missing_or_ambiguous_archive_versions_fail_closed(monkeypatch, tmp_path, output):
    monkeypatch.setattr(pg.subprocess, "run", lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout=output))
    with pytest.raises(pg.ToolchainError, match="postgresql_archive_version_unavailable"):
        pg.check_archive_compatibility(tmp_path / "test.dump", {})


@pytest.mark.parametrize("provenance", [None, {}, {"server": VERSION}, {"server": VERSION, "pg_dump": {"major": 17, "version": "17.11"}}])
def test_inconsistent_authenticated_provenance_is_refused(monkeypatch, tmp_path, operational_tools, provenance):
    with pytest.raises(pg.ToolchainError, match="postgresql_archive_provenance_invalid"):
        pg.check_archive_compatibility(tmp_path / "test.dump", {"postgresql": provenance})


def test_strict_verifier_produces_safe_machine_readable_qualification(tmp_path, monkeypatch, operational_tools):
    path, _ = encrypted_backup(tmp_path, monkeypatch)
    qualification = verifier.verify(path, require_postgres_compatible=True)
    assert qualification == {"format": "assetcore-backup-v1", "postgresql_qualification": {
        "toolchain": {name: VERSION for name in ("pg_restore", "psql", "server")},
        "archive": {name: VERSION for name in ("pg_dump", "server")},
    }}


def test_strict_verifier_rejects_pg17_even_when_crypto_passes(tmp_path, monkeypatch, operational_tools):
    path, expected = encrypted_backup(tmp_path, monkeypatch)
    assert verifier.verify(path) == expected
    monkeypatch.setattr(pg, "inspect_tool", lambda tool: {"major": 17, "version": "17.11"})
    with pytest.raises(SystemExit, match="postgresql_toolchain_incompatible"):
        verifier.verify(path, require_postgres_compatible=True)


def test_verifier_cli_never_echoes_optional_manifest_metadata(monkeypatch, capsys):
    monkeypatch.setattr(verifier, "verify", lambda *args, **kwargs: {
        "format": "assetcore-backup-v1", "database_sha256": "a" * 64,
        "documents_included": False, "created_at": TEST_URL,
        "postgresql": {"unexpected": TEST_URL}, "optional": TEST_URL,
    })
    monkeypatch.setattr(sys, "argv", ["verify_backup.py", "unused.acbackup"])
    verifier.main()
    output = capsys.readouterr().out
    assert "test-credential-sentinel" not in output
    assert "authentication and checksum verification passed" in output
