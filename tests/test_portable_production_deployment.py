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
DB_CONTAINER = "b" * 64
DB_HEALTH_FORMAT = "{{.State.Status}} {{if .State.Health}}{{.State.Health.Status}}{{end}}"


def test_compose_start_is_not_an_upgrade_and_network_is_private():
    config = yaml.safe_load((ROOT / "docker-compose.yml").read_text("utf-8"))
    app, migrate, db = (config["services"][key] for key in ("app", "migrate", "db"))
    assert set(app["depends_on"]) == {"db"}
    assert migrate["profiles"] == ["operations"]
    assert migrate["command"] == ["python", "-m", "app.runtime", "prepare"]
    assert app["environment"]["MIGRATION_STRATEGY"] == "external"
    assert "BACKUP_ENCRYPTION_KEY" not in app["environment"]
    assert "ports" not in db
    assert db["restart"] == "unless-stopped"
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
    state = {"current_image": OLD_IMAGE, "backup_image": OLD_IMAGE,
             "revision": deploy.PG16_BASELINE_REVISION, "source_changes": ""}
    toolchains = {OLD_IMAGE: 16, NEW_IMAGE: 16, deploy.PG16_BASELINE_IMAGE: 17}
    monkeypatch.setattr(subject, "current_image", lambda **_: state["current_image"])
    calls = []
    failure = {"at": None}

    def probe(mode, actor=None, **kwargs):
        calls.append(("probe", mode))
        return {"revision": state["revision"], "identity": ["same-test-db"]}

    def dc(*args, **kwargs):
        calls.append(args)
        if args == ("ps", "--all", "--quiet", "db"):
            return DB_CONTAINER
        stage = ("toolchain" if "--tools" in args else
                 "backup" if "scripts/backup_database.py" in args else
                 "verify" if "scripts/verify_backup.py" in args else
                 "prepare" if "migrate" in args else
                 "start" if args[0] == "up" else args[0])
        if stage == failure["at"]:
            raise deploy.DeploymentError("simulated_failure")
        if stage == "toolchain":
            assert args[-4:] == ("--tools", "pg_dump", "pg_restore", "psql")
            assert "check_compatibility" in kwargs["input_text"]
            assert not kwargs.get("backup_secret")
            if toolchains[subject.env["ASSETCORE_IMAGE"]] != 16:
                raise deploy.DeploymentError("incompatible_postgresql_toolchain")
            return json.dumps({name: {"major": 16, "version": "16.15"}
                               for name in ("server", "pg_dump", "pg_restore", "psql")})
        if stage == "backup":
            assert subject.env["ASSETCORE_IMAGE"] == state["backup_image"]
            mount = args[args.index("-v") + 1].removesuffix(":/backups:rw")
            (Path(mount) / "unique.acbackup").write_bytes(b"isolated-test-backup")
        if stage == "verify":
            assert args[-2:] == ("/backups/unique.acbackup", "--require-postgres-compatible")
            assert subject.env["ASSETCORE_IMAGE"] == NEW_IMAGE
            assert args[args.index("-v") + 1].endswith(":/backups:ro")
        if stage == "prepare":
            assert subject.env["ASSETCORE_IMAGE"] == NEW_IMAGE
        return ""

    monkeypatch.setattr(subject, "probe", probe)
    monkeypatch.setattr(subject, "dc", dc)
    def command(args, **kwargs):
        if "merge-base" in args:
            return deploy.PG16_BASELINE_SHA
        if "diff" in args:
            return state["source_changes"]
        if args[:3] == ["docker", "image", "inspect"]:
            assert args[3] == deploy.PG16_BASELINE_IMAGE
            return deploy.PG16_BASELINE_SHA
        assert args == ["docker", "inspect", "--format", DB_HEALTH_FORMAT, DB_CONTAINER]
        calls.append(("inspect", "db_health"))
        return "running healthy"
    monkeypatch.setattr(subject, "command", command)
    return SimpleNamespace(subject=subject, calls=calls, failure=failure, directory=tmp_path,
                           state=state, toolchains=toolchains)


def test_upgrade_orders_stop_backup_verify_prepare_ready_and_retains_recovery(operation):
    destination = operation.subject.upgrade(operation.directory, 1)
    preflights = [call for call in operation.calls if "--tools" in call]
    assert len(preflights) == 2
    mutations = [call for call in operation.calls if call[0] != "probe" and "--tools" not in call]
    assert mutations[0] == ("stop", "app")
    assert "scripts/backup_database.py" in mutations[1]
    assert "scripts/verify_backup.py" in mutations[2]
    assert mutations[3][-1] == "migrate"
    assert mutations[4][0] == "up" and "--no-build" in mutations[4]
    assert operation.calls[-1] == ("probe", "smoke")
    record = json.loads((destination / "release.json").read_text())
    assert record["status"] == "runtime_ready"
    assert record["previous_image_id"] == OLD_IMAGE
    assert record["backup_image_id"] == OLD_IMAGE
    assert record["backup_mode"] == "previous_image"
    assert record["backup_toolchain"]["pg_dump"]["major"] == 16
    assert record["image_id"] == NEW_IMAGE
    assert record["release_sha"] == REVISION
    assert record["encrypted_sha256"] == deploy.file_sha256(destination / "unique.acbackup")
    assert record["fully_commissioned"] is False
    assert "test-operation-only" not in json.dumps(record)


@pytest.mark.parametrize("image", [OLD_IMAGE, NEW_IMAGE])
def test_incompatible_backup_or_target_tools_fail_before_stopping_writers(operation, image):
    operation.toolchains[image] = 17
    with pytest.raises(deploy.DeploymentError, match="incompatible_postgresql_toolchain"):
        operation.subject.upgrade(operation.directory, 1)
    assert not any(call[0] == "stop" or "migrate" in call for call in operation.calls)
    assert not any("scripts/backup_database.py" in call for call in operation.calls)
    assert not list(operation.directory.iterdir())
    assert operation.subject.env["ASSETCORE_IMAGE"] == NEW_IMAGE


def test_real_pg17_baseline_requires_explicit_bridge_before_any_downtime(operation):
    operation.state["current_image"] = deploy.PG16_BASELINE_IMAGE
    with pytest.raises(deploy.DeploymentError, match="incompatible_postgresql_toolchain"):
        operation.subject.upgrade(operation.directory, 1)
    assert not any(call[0] == "stop" for call in operation.calls)
    assert not list(operation.directory.iterdir())


def test_exact_baseline_bridge_creates_pg16_backup_with_target_before_prepare(operation):
    operation.state.update(current_image=deploy.PG16_BASELINE_IMAGE, backup_image=NEW_IMAGE)
    destination = operation.subject.upgrade(operation.directory, 1, pg16_baseline_bridge=True)
    record = json.loads((destination / "release.json").read_text())
    assert record["previous_image_id"] == deploy.PG16_BASELINE_IMAGE
    assert record["backup_image_id"] == NEW_IMAGE
    assert record["backup_mode"] == "pg16_baseline_bridge"
    assert record["backup_toolchain"]["pg_dump"]["major"] == 16
    assert record["status"] == "runtime_ready"
    assert len([call for call in operation.calls if "--tools" in call]) == 1
    mutations = [call for call in operation.calls if call[0] != "probe" and "--tools" not in call]
    assert mutations[0] == ("stop", "app")
    assert "scripts/backup_database.py" in mutations[1]
    assert mutations[2][-1] == "--require-postgres-compatible"
    assert mutations[3][-1] == "migrate"


def test_baseline_bridge_rejects_another_immutable_old_image(operation):
    with pytest.raises(deploy.DeploymentError, match="exact_baseline_image"):
        operation.subject.upgrade(operation.directory, 1, pg16_baseline_bridge=True)
    assert not any(call[0] == "stop" for call in operation.calls)
    assert not list(operation.directory.iterdir())


def test_baseline_bridge_rejects_another_database_revision(operation):
    operation.state.update(current_image=deploy.PG16_BASELINE_IMAGE, revision="older-revision")
    with pytest.raises(deploy.DeploymentError, match="baseline_release_and_schema"):
        operation.subject.upgrade(operation.directory, 1, pg16_baseline_bridge=True)
    assert not any(call[0] == "stop" for call in operation.calls)


@pytest.mark.parametrize("changed_path", deploy.PG16_BRIDGE_UNCHANGED_PATHS)
def test_baseline_bridge_rejects_future_application_or_schema_changes(operation, changed_path):
    operation.state.update(current_image=deploy.PG16_BASELINE_IMAGE, source_changes=changed_path)
    with pytest.raises(deploy.DeploymentError, match="unchanged_database_application"):
        operation.subject.upgrade(operation.directory, 1, pg16_baseline_bridge=True)
    assert not any(call[0] == "stop" for call in operation.calls)
    assert not list(operation.directory.iterdir())


@pytest.mark.parametrize(("query", "reply", "error"), [
    ("inspect", "b" * 40, "baseline_release_and_schema"),
    ("merge-base", "b" * 40, "baseline_ancestor"),
])
def test_baseline_bridge_checks_image_label_and_commit_ancestry(operation, monkeypatch,
                                                              query, reply, error):
    original = operation.subject.command
    monkeypatch.setattr(operation.subject, "command", lambda args, **kw:
                        reply if query in args else original(args, **kw))
    operation.state["current_image"] = deploy.PG16_BASELINE_IMAGE
    with pytest.raises(deploy.DeploymentError, match=error):
        operation.subject.upgrade(operation.directory, 1, pg16_baseline_bridge=True)
    assert not any(call[0] == "stop" for call in operation.calls)


def test_pg17_archive_is_not_a_verified_upgrade_backup_despite_crypto_success(operation,
                                                                           monkeypatch):
    original = operation.subject.dc

    def incompatible_archive(*args, **kwargs):
        result = original(*args, **kwargs)
        if "scripts/verify_backup.py" in args:
            assert "--require-postgres-compatible" in args
            raise deploy.DeploymentError("postgresql_archive_client_major_mismatch")
        return result

    monkeypatch.setattr(operation.subject, "dc", incompatible_archive)
    with pytest.raises(deploy.DeploymentError, match="archive_client_major_mismatch"):
        operation.subject.upgrade(operation.directory, 1)
    assert not any("migrate" in call or call[0] == "up" for call in operation.calls)
    record = json.loads(next(operation.directory.glob("*/release.json")).read_text())
    assert record["status"] == "failed_operator_recovery_required"
    assert record["stage"] == "verify"
    assert "encrypted_sha256" not in record


def test_archive_changed_during_qualification_never_prepares(operation, monkeypatch):
    original = operation.subject.dc

    def changed_archive(*args, **kwargs):
        result = original(*args, **kwargs)
        if "scripts/verify_backup.py" in args:
            next(operation.directory.glob("*/*.acbackup")).write_bytes(b"changed-test-backup")
        return result

    monkeypatch.setattr(operation.subject, "dc", changed_archive)
    with pytest.raises(deploy.DeploymentError, match="backup_changed_during_verification"):
        operation.subject.upgrade(operation.directory, 1)
    assert not any("migrate" in call or call[0] == "up" for call in operation.calls)


def test_changed_schema_after_stopping_writers_never_uses_baseline_bridge(operation, monkeypatch):
    original = operation.subject.probe
    operation.state.update(current_image=deploy.PG16_BASELINE_IMAGE, backup_image=NEW_IMAGE)

    def changed_schema(*args, **kwargs):
        if operation.subject.stage == "stopped_state_validation":
            operation.state["revision"] = "unexpected-schema"
        return original(*args, **kwargs)

    monkeypatch.setattr(operation.subject, "probe", changed_schema)
    with pytest.raises(deploy.DeploymentError, match="database_changed_before_backup"):
        operation.subject.upgrade(operation.directory, 1, pg16_baseline_bridge=True)
    assert ("stop", "app") in operation.calls
    assert not any("scripts/backup_database.py" in call or "migrate" in call or call[0] == "up"
                   for call in operation.calls)
    record = json.loads(next(operation.directory.glob("*/release.json")).read_text())
    assert record["status"] == "failed_operator_recovery_required"
    assert record["stage"] == "stopped_state_validation"


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
    assert operation.calls == [
        ("ps", "--all", "--quiet", "db"),
        ("start", "db"),
        ("inspect", "db_health"),
        ("probe", "existing"),
        ("up", "-d", "--no-deps", "--no-build", "--pull", "never",
         "--wait", "--wait-timeout", "180", "app"),
        ("probe", "smoke"),
    ]  # Exhaustive: no migrate/prepare/seed/build/pull operation is permitted.


def test_start_recovers_existing_stopped_containers_in_health_order(operation, monkeypatch):
    subject = operation.subject
    state = {"db": "stopped", "app": "stopped"}
    calls = []

    def dc(*args, **kwargs):
        calls.append(args)
        if args == ("ps", "--quiet", "--all", "app"):
            assert state["app"] == "stopped"
            return "a" * 64
        if args == ("ps", "--all", "--quiet", "db"):
            return DB_CONTAINER
        if args == ("start", "db"):
            assert state == {"db": "stopped", "app": "stopped"}
            state["db"] = "starting"
            return ""
        if args == ("up", "-d", "--no-deps", "--no-build", "--pull", "never",
                    "--wait", "--wait-timeout", "180", "app"):
            assert state["db"] == "healthy"
            state["app"] = "healthy"
            return ""
        pytest.fail(f"Unexpected normal-start command: {args}")

    def command(args, **kwargs):
        if args == ["docker", "inspect", "--format", DB_HEALTH_FORMAT, DB_CONTAINER]:
            calls.append(("inspect", "db_health"))
            assert state["app"] == "stopped"
            return "running " + state["db"]
        assert args == ["docker", "inspect", "--format", "{{.Image}}", "a" * 64]
        return NEW_IMAGE

    def wait(seconds):
        assert seconds == 1 and state == {"db": "starting", "app": "stopped"}
        state["db"] = "healthy"

    def probe(mode, **kwargs):
        calls.append(("probe", mode))
        assert state["db"] == "healthy"
        if mode == "smoke":
            assert state["app"] == "healthy" and kwargs["running"] is True
        else:
            assert mode == "existing" and state["app"] == "stopped"

    monkeypatch.setattr(subject, "current_image", deploy.Deployment.current_image.__get__(subject))
    monkeypatch.setattr(subject, "command", command)
    monkeypatch.setattr(subject, "dc", dc)
    monkeypatch.setattr(subject, "probe", probe)
    monkeypatch.setattr(subject, "prepare", lambda: pytest.fail("Normal start invoked prepare"))
    monkeypatch.setattr(deploy.time, "sleep", wait)
    subject.restart()
    assert state == {"db": "healthy", "app": "healthy"}
    assert [call[0] for call in calls] == ["ps", "ps", "start", "inspect", "inspect", "probe", "up", "probe"]


def test_failed_database_health_prevents_app_probe_and_start(operation, monkeypatch):
    monkeypatch.setattr(operation.subject, "current_image", lambda **_: NEW_IMAGE)
    operation.failure["at"] = "start"
    with pytest.raises(deploy.DeploymentError, match="simulated_failure"):
        operation.subject.restart()
    assert operation.calls == [("ps", "--all", "--quiet", "db"), ("start", "db")]
    assert operation.subject.stage == "database_start_and_readiness"


@pytest.mark.parametrize("state", ["running unhealthy", "exited", "running", "restarting starting"])
def test_nonhealthy_or_missing_database_healthcheck_prevents_app_start(operation, monkeypatch, state):
    monkeypatch.setattr(operation.subject, "current_image", lambda **_: NEW_IMAGE)
    monkeypatch.setattr(operation.subject, "command", lambda *a, **kw: state)
    with pytest.raises(deploy.DeploymentError, match="database_not_healthy"):
        operation.subject.restart()
    assert operation.calls == [("ps", "--all", "--quiet", "db"), ("start", "db")]


def test_database_health_wait_is_bounded_and_never_prepares(operation, monkeypatch):
    monkeypatch.setattr(operation.subject, "current_image", lambda **_: NEW_IMAGE)
    monkeypatch.setattr(operation.subject, "command", lambda *a, **kw: "running starting")
    clock = iter([0, 119, 120])
    sleeps = []
    monkeypatch.setattr(deploy.time, "monotonic", lambda: next(clock))
    monkeypatch.setattr(deploy.time, "sleep", sleeps.append)
    with pytest.raises(deploy.DeploymentError, match="database_health_timed_out"):
        operation.subject.restart()
    assert sleeps == [1]
    assert operation.calls == [("ps", "--all", "--quiet", "db"), ("start", "db")]


@pytest.mark.parametrize("containers", ["", "not-a-container", DB_CONTAINER + "\n" + "c" * 64])
def test_normal_start_requires_one_existing_database_and_never_creates_it(operation, monkeypatch, containers):
    monkeypatch.setattr(operation.subject, "current_image", lambda **_: NEW_IMAGE)
    calls = []
    def dc(*args, **kwargs):
        calls.append(args)
        return containers
    monkeypatch.setattr(operation.subject, "dc", dc)
    with pytest.raises(deploy.DeploymentError, match="one_existing_database_container_required"):
        operation.subject.restart()
    assert calls == [("ps", "--all", "--quiet", "db")]


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


@pytest.mark.parametrize(("diagnostic", "code"), [
    ("Permission denied", "command_permission_denied"),
    ("No space left on device", "command_storage_exhausted"),
    ("server version mismatch", "command_postgres_client_version_mismatch"),
    ("pg_dump failed", "command_postgres_dump_failed"),
])
def test_command_failure_classification_never_exposes_raw_output(monkeypatch, diagnostic, code):
    monkeypatch.setattr(subprocess, "run", lambda *a, **kw: SimpleNamespace(
        returncode=1, stdout="sensitive-test-sentinel", stderr=diagnostic + " /private/internal/path"))
    with pytest.raises(deploy.DeploymentError) as caught:
        deploy.run(["docker", "test"], cwd=ROOT)
    assert str(caught.value) == code


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
