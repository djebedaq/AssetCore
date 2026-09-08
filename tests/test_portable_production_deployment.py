from __future__ import annotations

import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from scripts import production_container as container
from scripts import production_deploy as deploy
from scripts import production_preflight as preflight

ROOT = Path(__file__).resolve().parents[1]
REVISION = "a" * 40
OLD_IMAGE = "sha256:" + "1" * 64
NEW_IMAGE = "sha256:" + "2" * 64


def test_compose_start_is_not_an_upgrade_and_network_is_private():
    config = yaml.safe_load((ROOT / "docker-compose.yml").read_text("utf-8"))
    app, migrate, db = (config["services"][key] for key in ("app", "migrate", "db"))
    assert set(app["depends_on"]) == {"db"}
    assert migrate["profiles"] == ["operations"]
    assert migrate["command"] == ["python", "-m", "app.runtime", "prepare"]
    assert app["environment"]["MIGRATION_STRATEGY"] == "external"
    assert "BACKUP_ENCRYPTION_KEY" not in app["environment"]
    assert "ports" not in db
    assert db["volumes"] == ["assetcore_pg:/var/lib/postgresql/data"]
    assert app["ports"] == ["${ASSETCORE_BIND_ADDRESS:-127.0.0.1}:${ASSETCORE_PORT:-10000}:10000"]
    assert app["image"] == migrate["image"] == "${ASSETCORE_IMAGE:-assetcore:local}"
    for service in (app, migrate):
        assert service["read_only"] is True
        assert service["cap_drop"] == ["ALL"]
        assert service["security_opt"] == ["no-new-privileges:true"]
    dev = yaml.safe_load((ROOT / "docker-compose.dev.yml").read_text("utf-8"))
    assert dev["services"]["db"]["ports"] == ["127.0.0.1:5432:5432"]


def test_production_example_has_required_contract_without_usable_secrets():
    values = dict(line.split("=", 1) for line in
                  (ROOT / ".env.production.example").read_text("utf-8").splitlines()
                  if line and not line.startswith("#"))
    empty = {"POSTGRES_PASSWORD", "DATABASE_URL", "SECRET_KEY", "SIGNATURE_ENCRYPTION_KEY",
             "OWNER_FIRST_NAME", "OWNER_MIDDLE_NAME", "OWNER_LAST_NAME", "OWNER_EMAIL",
             "OWNER_JOB_TITLE", "OWNER_INITIAL_PASSWORD", "INSTALLATION_ID", "LICENSE_PUBLIC_KEY",
             "PUBLIC_BASE_URL", "FRONTEND_ORIGIN", "ASSETCORE_IMAGE", "TRUSTED_PROXY_IPS"}
    assert all(values[key] == "" for key in empty)
    assert values["MIGRATION_STRATEGY"] == "external"
    assert values["PRODUCTION_MODE"] == values["LICENSE_ENFORCEMENT_ENABLED"] == "true"
    assert values["DEPLOYMENT_ENVIRONMENT"] == "production"
    assert "BACKUP_ENCRYPTION_KEY" not in values
    assert {"DB_POOL_SIZE", "DB_MAX_OVERFLOW", "DB_POOL_TIMEOUT_SECONDS",
            "DB_POOL_PRE_PING", "DB_POOL_RECYCLE_SECONDS", "DB_CONNECT_TIMEOUT_SECONDS",
            "DB_STATEMENT_TIMEOUT_MS", "FORWARDED_ALLOW_IPS"} <= values.keys()


@pytest.fixture()
def operation(tmp_path, monkeypatch):
    subject = deploy.Deployment(ROOT, REVISION, ROOT / ".env")
    subject.image = NEW_IMAGE
    subject.env["ASSETCORE_IMAGE"] = NEW_IMAGE
    monkeypatch.setenv("BACKUP_ENCRYPTION_KEY", "test-operation-only")
    monkeypatch.setattr(subject, "validate", lambda: None)
    monkeypatch.setattr(deploy, "release_source", lambda *_: None)
    monkeypatch.setattr(subject, "current_image", lambda **_: OLD_IMAGE)
    calls = []
    failure = {"at": None}

    def probe(mode, actor=None, **kwargs):
        calls.append(("probe", mode))
        return {"revision": "20260826_0021", "identity": ["same-test-db"]}

    def dc(*args, **kwargs):
        calls.append(args)
        stage = ("backup" if "scripts/backup_database.py" in args else
                 "verify" if "scripts/verify_backup.py" in args else
                 "prepare" if "migrate" in args else
                 "start" if args[0] == "up" else args[0])
        if stage == failure["at"]:
            raise deploy.DeploymentError("simulated_failure")
        if stage == "backup":
            assert subject.env["ASSETCORE_IMAGE"] == OLD_IMAGE
            mount = args[args.index("-v") + 1].removesuffix(":/backups:rw")
            (Path(mount) / "unique.acbackup").write_bytes(b"isolated-test-backup")
        if stage == "verify":
            assert args[-1] == "/backups/unique.acbackup"
            assert args[args.index("-v") + 1].endswith(":/backups:ro")
        if stage == "prepare":
            assert subject.env["ASSETCORE_IMAGE"] == NEW_IMAGE
        return ""

    monkeypatch.setattr(subject, "probe", probe)
    monkeypatch.setattr(subject, "dc", dc)
    return SimpleNamespace(subject=subject, calls=calls, failure=failure, directory=tmp_path)


def test_upgrade_orders_stop_backup_verify_prepare_ready_and_retains_recovery(operation):
    destination = operation.subject.upgrade(operation.directory, 1)
    mutations = [call for call in operation.calls if call[0] != "probe"]
    assert mutations[0] == ("stop", "app")
    assert "scripts/backup_database.py" in mutations[1]
    assert "scripts/verify_backup.py" in mutations[2]
    assert mutations[3][-1] == "migrate"
    assert mutations[4][0] == "up" and "--no-build" in mutations[4]
    assert operation.calls[-1] == ("probe", "smoke")
    record = json.loads((destination / "release.json").read_text())
    assert record["status"] == "runtime_ready"
    assert record["previous_image_id"] == OLD_IMAGE
    assert record["image_id"] == NEW_IMAGE
    assert record["release_sha"] == REVISION
    assert record["encrypted_sha256"] == deploy.file_sha256(destination / "unique.acbackup")
    assert record["fully_commissioned"] is False
    assert "test-operation-only" not in json.dumps(record)


@pytest.mark.parametrize("failure", ["backup", "verify", "prepare"])
def test_failed_gate_never_starts_new_app_and_backup_failures_never_prepare(operation, failure):
    operation.failure["at"] = failure
    with pytest.raises(deploy.DeploymentError):
        operation.subject.upgrade(operation.directory, 1)
    assert not any(call[0] == "up" for call in operation.calls)
    if failure in {"backup", "verify"}:
        assert not any("migrate" in call for call in operation.calls)
    record = json.loads(next(operation.directory.glob("*/release.json")).read_text())
    assert record["stage"] == failure
    assert record["status"] == "failed_operator_recovery_required"


def test_failed_readiness_stops_app_without_automatic_rollback(operation):
    operation.failure["at"] = "start"
    with pytest.raises(deploy.DeploymentError):
        operation.subject.upgrade(operation.directory, 1)
    assert operation.calls[-1] == ("stop", "app")


def test_interrupted_start_stops_app_and_records_recovery_requirement(operation, monkeypatch):
    original = operation.subject.dc

    def interrupt(*args, **kwargs):
        if args[0] == "up":
            raise KeyboardInterrupt
        return original(*args, **kwargs)

    monkeypatch.setattr(operation.subject, "dc", interrupt)
    with pytest.raises(KeyboardInterrupt):
        operation.subject.upgrade(operation.directory, 1)
    assert operation.calls[-1] == ("stop", "app")
    record = json.loads(next(operation.directory.glob("*/release.json")).read_text())
    assert record["status"] == "failed_operator_recovery_required"


def test_different_database_is_refused_before_stopping_writers(operation, monkeypatch):
    monkeypatch.setattr(operation.subject, "probe", lambda *a, **kw: kw.get("running", False))
    with pytest.raises(deploy.DeploymentError, match="database_must_match"):
        operation.subject.upgrade(operation.directory, 1)
    assert not operation.calls


def test_restart_cannot_bypass_release_upgrade_guard(operation):
    with pytest.raises(deploy.DeploymentError, match="release_change_requires_upgrade"):
        operation.subject.restart()
    assert not operation.calls


def test_same_release_start_never_prepares(operation, monkeypatch):
    monkeypatch.setattr(operation.subject, "current_image", lambda **_: NEW_IMAGE)
    operation.subject.restart()
    assert not any("migrate" in call for call in operation.calls)


def test_initialization_refuses_nonempty_database_before_prepare(operation, monkeypatch):
    def nonempty(*_args, **_kwargs):
        raise deploy.DeploymentError("nonempty")
    monkeypatch.setattr(operation.subject, "probe", nonempty)
    with pytest.raises(deploy.DeploymentError, match="nonempty"):
        operation.subject.initialize()
    assert not any("migrate" in call for call in operation.calls)
    assert not any(call[-1] == "app" and call[0] == "up" for call in operation.calls)


def test_explicit_empty_initialization_orders_check_prepare_start(operation):
    operation.subject.initialize()
    assert operation.calls[2] == ("probe", "empty")
    assert operation.calls[3][-1] == "migrate"
    assert operation.calls[4][0] == "up"


@pytest.mark.parametrize(("actual", "dirty", "error"), [
    ("b" * 40, "", "sha_does_not_match"), (REVISION, " M file", "clean_release"),
    (REVISION, "?? unexpected-file", "clean_release"),
])
def test_release_guards_reject_wrong_sha_and_dirty_source(monkeypatch, actual, dirty, error):
    monkeypatch.setattr(deploy, "run", lambda args, **_: actual if "rev-parse" in args else dirty)
    with pytest.raises(deploy.DeploymentError, match=error):
        deploy.release_source(ROOT, REVISION)


def test_release_guard_accepts_exact_clean_sha(monkeypatch):
    monkeypatch.setattr(deploy, "run", lambda args, **_: REVISION if "rev-parse" in args else "")
    deploy.release_source(ROOT, REVISION)


def test_image_label_must_match_exact_release(monkeypatch):
    subject = deploy.Deployment(ROOT, REVISION, ROOT / ".env")
    replies = iter((json.dumps(NEW_IMAGE), "b" * 40))
    monkeypatch.setattr(subject, "command", lambda *_: next(replies))
    with pytest.raises(deploy.DeploymentError, match="image_revision_mismatch"):
        subject.image_identity()


def test_operational_secret_is_not_passed_to_web_or_regular_commands(monkeypatch):
    monkeypatch.setenv("BACKUP_ENCRYPTION_KEY", "sensitive-test-sentinel")
    subject = deploy.Deployment(ROOT, REVISION, ROOT / ".env")
    environments = []
    monkeypatch.setattr(deploy, "run", lambda *a, **kw: environments.append(kw["env"]))
    subject.dc("up", "app")
    subject.dc("run", "app", backup_secret=True)
    assert "BACKUP_ENCRYPTION_KEY" not in environments[0]
    assert environments[1]["BACKUP_ENCRYPTION_KEY"] == "sensitive-test-sentinel"


def test_command_failure_does_not_echo_subprocess_secrets(monkeypatch, capsys):
    monkeypatch.setattr(subprocess, "run", lambda *a, **kw:
                        SimpleNamespace(returncode=1, stdout="secret-output", stderr="secret-error"))
    with pytest.raises(deploy.DeploymentError) as caught:
        deploy.run(["docker", "test"], cwd=ROOT)
    assert str(caught.value) == "command_failed"
    assert "secret" not in str(caught.value) + capsys.readouterr().out


def test_host_preflight_uses_only_read_only_commands_and_does_not_write(tmp_path, monkeypatch):
    queries = []
    def query(args):
        queries.append(args)
        if "rev-parse" in args:
            return REVISION
        if "status" in args:
            return ""
        return None
    monkeypatch.setattr(preflight, "query", query)
    monkeypatch.setattr(preflight.shutil, "which", lambda _: "docker")
    before = list(tmp_path.iterdir())
    result = preflight.report(tmp_path)
    assert result["git_sha"] == REVISION and result["git_clean"] is True
    assert result["clock_sync_verified"] is False
    assert result["daemon_reachable"] is False
    assert list(tmp_path.iterdir()) == before
    assert all(not {"install", "build", "up", "run", "start", "stop", "pull", "--install"}
               .intersection(command) for command in queries)


def test_os_operation_lock_rejects_second_operator(tmp_path):
    with deploy.operation_lock(tmp_path, "assetcore"):
        with pytest.raises(deploy.DeploymentError, match="another_production"):
            with deploy.operation_lock(tmp_path, "assetcore"):
                pytest.fail("second operator entered")


def test_container_probe_has_no_database_write_or_secret_error_output(monkeypatch, capsys):
    import sys
    monkeypatch.setattr(sys, "argv", ["probe", "existing"])
    monkeypatch.setattr(container, "database_state", lambda *_: (_ for _ in ()).throw(
        ValueError("secret-database-url")))
    assert container.main() == 1
    output = capsys.readouterr()
    assert output.err == "production_probe_failed\n"
    assert "secret" not in output.out + output.err
    code = (ROOT / "scripts/production_container.py").read_text("utf-8")
    assert "SET TRANSACTION READ ONLY" in code
    assert not any(token in code for token in ("INSERT ", "UPDATE ", "DELETE ", "CREATE ", "DROP "))
