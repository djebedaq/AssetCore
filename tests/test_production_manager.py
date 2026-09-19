from __future__ import annotations

import base64
import json
import os
import subprocess
import sys
import uuid
import warnings
from pathlib import Path
from types import SimpleNamespace
from urllib.error import HTTPError, URLError

import pytest

from scripts import production_manager as manager

ROOT = Path(__file__).resolve().parents[1]
OLD_SHA = "a" * 40
NEW_SHA = "b" * 40
OLD_IMAGE = "sha256:" + "1" * 64
NEW_IMAGE = "sha256:" + "2" * 64
BACKUP_KEY = base64.b64encode(b"manager-test-key" * 2).decode("ascii")


def git(root: Path, *arguments: str) -> str:
    result = subprocess.run(
        ["git", "-c", "core.autocrlf=false", *arguments],
        cwd=root, capture_output=True, text=True, check=True,
    )
    return result.stdout.strip()


@pytest.fixture()
def release_repository(tmp_path):
    """Local committed content only; no remote/network or application data."""
    root = tmp_path / "installation with spaces"
    root.mkdir()
    git(root, "init", "--initial-branch=main")
    git(root, "config", "user.name", "Isolated tooling test")
    git(root, "config", "user.email", "tooling-test@example.invalid")
    (root / ".gitignore").write_text(".tmp/\n.assetcore-operator.json\n", "utf-8")
    (root / "release-marker.txt").write_text("first committed version\n", "utf-8")
    git(root, "add", ".")
    git(root, "commit", "-m", "First isolated release")
    current = git(root, "rev-parse", "HEAD")
    (root / "release-marker.txt").write_text("second committed version\n", "utf-8")
    git(root, "commit", "-am", "Second isolated release")
    target = git(root, "rev-parse", "HEAD")
    git(root, "remote", "add", "origin", "https://github.com/djebedaq/AssetCore.git")
    git(root, "update-ref", "refs/remotes/origin/main", target)
    git(root, "checkout", "--detach", current)
    return root, current, target


@pytest.fixture()
def configuration(tmp_path):
    root = tmp_path / "source"
    root.mkdir()
    backup = tmp_path / "approved backups"
    backup.mkdir()
    return root, {
        "version": 1, "backup_dir": str(backup), "actor_user_id": 17,
        "project": "isolated-project", "public_origin": None,
    }


def ready_payload():
    return {"status": "ready", "service": "AssetCore", "checks": {
        name: {"status": "pass", "code": code} for name, code in manager.CHECKS.items()
    }}


def production_report(sha=OLD_SHA, image=OLD_IMAGE, *, public=None):
    return {
        "docker_available": True, "git_clean": True, "source_sha": sha,
        "app": {"running": True, "healthy": True, "release_sha": sha,
                "image_id": image, "port": 10000},
        "db": {"running": True, "healthy": True, "image_id": "sha256:" + "3" * 64},
        "local": manager.readiness(ready_payload()), "health": True, "public": public,
    }


@pytest.mark.parametrize("value", ["", "main", "latest", "a" * 39, "a" * 41,
                                  "A" * 40, "g" * 40, "a" * 40 + "; stop", None])
def test_target_must_be_an_explicit_exact_lowercase_commit(value):
    with pytest.raises(manager.ManagerError, match="exact_40_character_target_sha_required"):
        manager.exact_sha(value)


@pytest.mark.parametrize("argv", [[], ["update"], ["latest"], ["update", "--sha", "main"],
                                 ["update", "--sha", "latest"],
                                 ["update", "--sha", NEW_SHA, "--skip-ci"],
                                 ["update", "--sha", NEW_SHA, "--pg16-baseline-bridge"],
                                 ["update", "--sha", NEW_SHA, "--force"]])
def test_cli_has_no_implicit_target_or_safety_bypass(argv, tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(manager, "frozen_run", lambda *_: pytest.fail("started a mutation"))
    monkeypatch.setattr(manager, "command", lambda *_a, **_k: pytest.fail("ran a command"))
    assert manager.main(argv, root=tmp_path) == 1
    assert "Traceback" not in capsys.readouterr().out


def test_invalid_argument_does_not_echo_accidentally_pasted_secret(tmp_path, capsys):
    assert manager.main(["configure", "--actor-user-id", BACKUP_KEY], root=tmp_path) == 1
    assert BACKUP_KEY not in capsys.readouterr().out


@pytest.mark.parametrize("name", ["BACKUP_ENCRYPTION_KEY", "POSTGRES_PASSWORD", "DATABASE_URL",
                                 "SECRET_KEY", "SIGNATURE_ENCRYPTION_KEY", "private_key",
                                 "unknown_preference"])
def test_configuration_rejects_secret_and_unknown_fields(configuration, name):
    root, config = configuration
    with pytest.raises(manager.ManagerError, match="operator_config_fields_invalid"):
        manager.validate_config({**config, name: BACKUP_KEY}, root)


@pytest.mark.parametrize("actor", [0, -1, True, "17", 2147483648, 1.5, None])
def test_configuration_requires_explicit_positive_actor(configuration, actor):
    root, config = configuration
    with pytest.raises(manager.ManagerError, match="positive_audit_actor_required"):
        manager.validate_config({**config, "actor_user_id": actor}, root)


@pytest.mark.parametrize("project", ["", "A", "bad project", "--project", "x;stop", "x" * 64])
def test_configuration_rejects_unsafe_compose_identity(configuration, project):
    root, config = configuration
    with pytest.raises(manager.ManagerError, match="invalid_compose_project"):
        manager.validate_config({**config, "project": project}, root)


def test_configuration_accepts_absolute_path_with_spaces(configuration):
    root, config = configuration
    result = manager.validate_config(config, root)
    assert result == config
    assert Path(result["backup_dir"]).is_absolute()


@pytest.mark.parametrize("path_kind", ["relative", "inside_source", "missing", "comma"])
def test_configuration_refuses_unapproved_backup_parent(configuration, path_kind):
    root, config = configuration
    paths = {"relative": "relative backups", "inside_source": str(root),
             "missing": str(root.parent / "missing"), "comma": str(root.parent / "bad,path")}
    with pytest.raises(manager.ManagerError, match="approved_backup_parent_required"):
        manager.validate_config({**config, "backup_dir": paths[path_kind]}, root)


@pytest.mark.skipif(os.name == "nt", reason="POSIX permission bits do not represent Windows ACLs")
def test_posix_world_writable_backup_parent_refused(configuration):
    root, config = configuration
    backup = Path(config["backup_dir"])
    backup.chmod(0o777)
    try:
        with pytest.raises(manager.ManagerError, match="backup_parent_world_writable"):
            manager.validate_config(config, root)
    finally:
        backup.chmod(0o700)


@pytest.mark.parametrize("origin", ["http://example.com", "https://user:password@example.com",
                                   "https://127.0.0.1", "https://[::1]", "https://localhost",
                                   "https://host.internal", "https://example.com:8443",
                                   "https://example.com/api/ready", "https://example.com?x=1",
                                   "https://example.com#x", "https://bad..example.com",
                                   "https://example.com\n", "https://-bad.example.com"])
def test_public_readiness_requires_a_safe_configured_https_origin(origin):
    with pytest.raises(manager.ManagerError, match="public_https_origin_required"):
        manager.public_origin(origin)


def test_public_origin_is_normalized_and_optional():
    assert manager.public_origin("https://Status.Example.COM:443/") == "https://status.example.com"
    assert manager.public_origin(None) is None


def test_configure_writes_only_validated_nonsecret_config(release_repository, tmp_path):
    root, _, _ = release_repository
    (root / ".tmp").mkdir()
    backup = tmp_path / "backup parent"
    backup.mkdir()
    args = SimpleNamespace(backup_dir=str(backup), actor_user_id=17, project="isolated-project",
                           public_origin="https://status.example.com")
    manager.configure(root, args)
    saved = json.loads((root / manager.CONFIG).read_text("utf-8"))
    assert set(saved) == {"version", "backup_dir", "actor_user_id", "project", "public_origin"}
    assert saved == manager.load_config(root)
    assert git(root, "status", "--porcelain", "--untracked-files=all") == ""
    args.project = "different-project"
    with pytest.raises(manager.ManagerError, match="compose_project_change_requires"):
        manager.configure(root, args)
    assert json.loads((root / manager.CONFIG).read_text("utf-8")) == saved


def test_secret_prompt_has_no_echo_storage_or_environment(configuration, monkeypatch, capsys):
    root, _ = configuration
    before = set(root.iterdir())
    monkeypatch.delenv("BACKUP_ENCRYPTION_KEY", raising=False)
    monkeypatch.setattr(manager.getpass, "getpass", lambda _prompt: BACKUP_KEY)
    assert manager.backup_key() == BACKUP_KEY
    assert "BACKUP_ENCRYPTION_KEY" not in os.environ
    assert set(root.iterdir()) == before
    captured = capsys.readouterr()
    assert BACKUP_KEY not in captured.out + captured.err


@pytest.mark.parametrize("key", ["", "not-base64", "!" * 44,
                               base64.b64encode(b"x" * 31).decode(),
                               base64.b64encode(b"x" * 33).decode(),
                               BACKUP_KEY + "\n"])
def test_malformed_backup_key_refused(key, monkeypatch):
    monkeypatch.setattr(manager.getpass, "getpass", lambda _prompt: key)
    with pytest.raises(manager.ManagerError, match="secure_32_byte_base64_backup_key_required"):
        manager.backup_key()


def test_getpass_echo_fallback_is_refused(monkeypatch):
    def unavailable(_prompt):
        warnings.warn("echo would be enabled", manager.getpass.GetPassWarning, stacklevel=2)
        pytest.fail("echo fallback continued")
    monkeypatch.setattr(manager.getpass, "getpass", unavailable)
    with pytest.raises(manager.ManagerError, match="secure_32_byte_base64_backup_key_required"):
        manager.backup_key()


def test_regular_commands_do_not_inherit_backup_key_or_process_overrides(monkeypatch):
    for name in ("BACKUP_ENCRYPTION_KEY", "GIT_DIR", "COMPOSE_FILE", "PYTHONPATH", "ASSETCORE_IMAGE"):
        monkeypatch.setenv(name, BACKUP_KEY)
    env = manager.clean_environment()
    assert env["GIT_TERMINAL_PROMPT"] == "0"
    assert not any(name in env for name in (
        "BACKUP_ENCRYPTION_KEY", "GIT_DIR", "COMPOSE_FILE", "PYTHONPATH", "ASSETCORE_IMAGE"))
    assert os.environ["BACKUP_ENCRYPTION_KEY"] == BACKUP_KEY


@pytest.mark.parametrize("name", list(manager.CHECKS))
def test_readiness_requires_every_exact_check(name):
    value = ready_payload()
    assert manager.readiness(value)["ready"]
    del value["checks"][name]
    assert not manager.readiness(value)["ready"]
    value = ready_payload()
    value["checks"][name]["status"] = "fail"
    assert not manager.readiness(value)["ready"]


@pytest.mark.parametrize("code", ["license_not_applicable", "license_evaluated_read_only",
                                 "license_unverified", "license_evaluation_failed"])
def test_ready_status_cannot_bypass_successful_licence_evaluation(code):
    value = ready_payload()
    value["checks"]["license"]["code"] = code
    assert manager.readiness(value) == {
        "ready": False, "checks": {name: name != "license" for name in manager.CHECKS},
    }


@pytest.mark.parametrize("value", [{}, {"status": "ready"},
                                  {"status": "ready", "service": "Different service"},
                                  {"status": "ready", "checks": []}])
def test_malformed_readiness_fails_closed(value):
    assert not manager.readiness(value)["ready"]


class HTTPResponse:
    def __init__(self, url, body, *, status=200):
        self.url, self.body, self.status = url, body, status

    def geturl(self):
        return self.url

    def read(self, size):
        return self.body[:size]

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False


def test_https_readiness_keeps_tls_and_disables_redirects_and_proxy(monkeypatch):
    url = "https://status.example.com/api/ready"
    observed = []

    def build(*handlers):
        observed.extend(handlers)
        return SimpleNamespace(open=lambda value, timeout: HTTPResponse(
            value, json.dumps(ready_payload()).encode()))

    monkeypatch.setattr(manager.urllib.request, "build_opener", build)
    assert manager.readiness(manager.read_endpoint(url))["ready"]
    assert any(isinstance(item, manager.NoRedirect) for item in observed)
    assert any(isinstance(item, manager.urllib.request.ProxyHandler) and item.proxies == {}
               for item in observed)
    assert manager.NoRedirect().redirect_request(None) is None


@pytest.mark.parametrize("failure", [URLError("secret TLS diagnostic"),
                                     HTTPError("https://private.invalid", 302, "secret", {}, None)])
def test_tls_redirect_errors_are_safe(failure, monkeypatch):
    def fail(*_args, **_kwargs):
        raise failure
    monkeypatch.setattr(manager.urllib.request, "build_opener",
                        lambda *_: SimpleNamespace(open=fail))
    with pytest.raises(manager.ManagerError) as caught:
        manager.read_endpoint("https://status.example.com/api/ready")
    assert str(caught.value) == "readiness_transport_or_response_failed"


@pytest.mark.parametrize(("body", "status", "response_url"), [
    (b"secret invalid json", 200, "https://status.example.com/api/ready"),
    (b"[]", 200, "https://status.example.com/api/ready"),
    (b"x" * 65537, 200, "https://status.example.com/api/ready"),
    (b"{}", 503, "https://status.example.com/api/ready"),
    (b"{}", 200, "https://different.example.com/api/ready"),
], ids=["invalid-json", "wrong-shape", "oversized", "unavailable", "redirect"])
def test_http_metadata_and_unbounded_responses_refused(body, status, response_url, monkeypatch):
    monkeypatch.setattr(manager.urllib.request, "build_opener", lambda *_: SimpleNamespace(
        open=lambda *_a, **_k: HTTPResponse(response_url, body, status=status)))
    with pytest.raises(manager.ManagerError, match="readiness_transport_or_response_failed"):
        manager.read_endpoint("https://status.example.com/api/ready")


def intercept_fetch(monkeypatch):
    original = manager.git
    calls = []

    def local(root, *arguments):
        calls.append(arguments)
        if "fetch" in arguments:
            return ""
        return original(root, *arguments)

    monkeypatch.setattr(manager, "git", local)
    return calls


def test_exact_committed_forward_target_is_qualified_without_checkout(release_repository,
                                                                   monkeypatch):
    root, current, target = release_repository
    calls = intercept_fetch(monkeypatch)
    assert manager.qualify_source(root, target, current) == current
    assert git(root, "rev-parse", "HEAD") == current
    fetch = next(call for call in calls if "fetch" in call)
    assert manager.ORIGIN in fetch
    assert "+refs/heads/main:refs/remotes/origin/main" in fetch
    assert "--no-tags" in fetch and "--no-recurse-submodules" in fetch
    assert not any("checkout" in call for call in calls)


@pytest.mark.parametrize("untracked", [False, True])
def test_dirty_release_is_refused_before_fetch(release_repository, monkeypatch, untracked):
    root, current, target = release_repository
    path = root / ("untracked.txt" if untracked else "release-marker.txt")
    path.write_text("uncommitted application content", "utf-8")
    calls = intercept_fetch(monkeypatch)
    with pytest.raises(manager.ManagerError, match="clean_release_checkout_required"):
        manager.qualify_source(root, target, current)
    assert not any("fetch" in call for call in calls)
    assert git(root, "rev-parse", "HEAD") == current


def test_unavailable_target_cannot_qualify(release_repository, monkeypatch):
    root, current, _ = release_repository
    intercept_fetch(monkeypatch)
    with pytest.raises((manager.ManagerError, manager.deploy.DeploymentError)):
        manager.qualify_source(root, "f" * 40, current)
    assert git(root, "rev-parse", "HEAD") == current


def test_fetch_failure_is_closed_and_preserves_checkout(release_repository, monkeypatch):
    root, current, target = release_repository
    original = manager.git

    def fail_fetch(root, *arguments):
        if "fetch" in arguments:
            raise manager.deploy.DeploymentError("command_failed")
        return original(root, *arguments)

    monkeypatch.setattr(manager, "git", fail_fetch)
    with pytest.raises(manager.deploy.DeploymentError, match="command_failed"):
        manager.qualify_source(root, target, current)
    assert git(root, "rev-parse", "HEAD") == current


def test_target_outside_approved_main_is_refused(release_repository, monkeypatch):
    root, current, target = release_repository
    git(root, "update-ref", "refs/remotes/origin/main", current)
    intercept_fetch(monkeypatch)
    with pytest.raises(manager.ManagerError, match="target_not_in_approved_main_history"):
        manager.qualify_source(root, target, current)


@pytest.mark.parametrize("same", [False, True])
def test_downgrade_and_reinstall_are_refused(release_repository, monkeypatch, same):
    root, current, target = release_repository
    git(root, "checkout", "--detach", target)
    intercept_fetch(monkeypatch)
    with pytest.raises(manager.ManagerError, match="forward_only_update_required"):
        manager.qualify_source(root, target if same else current, target)


def test_running_source_mismatch_requires_recovery(release_repository, monkeypatch):
    root, current, target = release_repository
    intercept_fetch(monkeypatch)
    with pytest.raises(manager.ManagerError, match="source_running_release_mismatch"):
        manager.qualify_source(root, target, NEW_SHA)
    assert git(root, "rev-parse", "HEAD") == current


def test_arbitrary_remote_refused_before_network(release_repository, monkeypatch):
    root, current, target = release_repository
    git(root, "remote", "set-url", "origin", "https://untrusted.example.com/AssetCore.git")
    calls = intercept_fetch(monkeypatch)
    with pytest.raises(manager.ManagerError, match="assetcore_repository_required"):
        manager.qualify_source(root, target, current)
    assert not any("fetch" in call for call in calls)


def test_git_url_rewrite_refused_before_network(release_repository, monkeypatch):
    root, current, target = release_repository
    git(root, "config", "url.https://untrusted.example.com/.insteadOf", "https://github.com/")
    calls = intercept_fetch(monkeypatch)
    with pytest.raises(manager.ManagerError):
        manager.qualify_source(root, target, current)
    assert not any("fetch" in call for call in calls)


def test_container_status_queries_only_safe_metadata(configuration, monkeypatch):
    root, config = configuration
    calls = []

    def query(_root, arguments, **_kwargs):
        calls.append(arguments)
        if arguments[1] == "ps":
            return "c" * 64
        template = arguments[arguments.index("--format") + 1]
        if ".State.Status" in template:
            return "running healthy"
        if template == "{{.Image}}":
            return OLD_IMAGE
        if "org.opencontainers.image.revision" in template:
            return OLD_SHA
        if ".NetworkSettings.Ports" in template:
            return json.dumps([{"HostIp": "127.0.0.1", "HostPort": "12345"}])
        pytest.fail("unsafe or unknown Docker query")

    monkeypatch.setattr(manager, "command", query)
    result = manager.container_status(root, config["project"], "app")
    assert result == {"running": True, "healthy": True, "image_id": OLD_IMAGE,
                      "release_sha": OLD_SHA, "port": 12345}
    assert all("--format" in call or call[1] == "ps" for call in calls)
    assert all(".Config.Env" not in " ".join(call) for call in calls)
    assert any(f"label=com.docker.compose.project={config['project']}" in call for call in calls)


@pytest.mark.parametrize("binding", [[{"HostIp": "0.0.0.0", "HostPort": "10000"}],
                                     [{"HostIp": "127.0.0.1", "HostPort": "0"}],
                                     [{"HostIp": "127.0.0.1", "HostPort": "65536"}], [], None])
def test_app_requires_an_existing_single_loopback_binding(configuration, monkeypatch, binding):
    root, config = configuration
    replies = iter(["c" * 64, "running healthy", OLD_IMAGE, OLD_SHA, json.dumps(binding)])
    monkeypatch.setattr(manager, "command", lambda *_a, **_k: next(replies))
    with pytest.raises(manager.ManagerError, match="single_loopback_app_binding_required"):
        manager.container_status(root, config["project"], "app")


def test_status_is_read_only_and_does_not_create_files(configuration, monkeypatch):
    root, config = configuration
    config["public_origin"] = "https://status.example.com"
    before = list(root.iterdir())
    calls = []
    endpoints = []
    monkeypatch.setattr(manager, "source_state", lambda _root: {
        "source_sha": OLD_SHA, "git_clean": True})
    monkeypatch.setattr(manager, "command", lambda _root, args, **_kwargs: calls.append(args) or "")
    monkeypatch.setattr(manager, "container_status", lambda _root, _project, service:
                        production_report()[service])

    def endpoint(url):
        endpoints.append(url)
        return {"status": "ok"} if url.endswith("/api/health") else ready_payload()

    monkeypatch.setattr(manager, "read_endpoint", endpoint)
    result = manager.status(root, config)
    manager.require_local(result, OLD_SHA, OLD_IMAGE)
    assert result["public"]["ready"]
    assert calls == [["docker", "info", "--format", "{{.ServerVersion}}"]]
    assert endpoints == ["http://127.0.0.1:10000/api/ready", "http://127.0.0.1:10000/api/health",
                         "https://status.example.com/api/ready"]
    assert list(root.iterdir()) == before


def test_status_reports_unavailable_docker_without_echoing_error(configuration, monkeypatch,
                                                              capsys):
    root, config = configuration
    monkeypatch.setattr(manager, "source_state", lambda _root: {
        "source_sha": OLD_SHA, "git_clean": True})

    def fail(*_args, **_kwargs):
        raise RuntimeError(BACKUP_KEY)

    monkeypatch.setattr(manager, "command", fail)
    report = manager.status(root, config)
    assert not report["docker_available"] and report["app"] is None and report["db"] is None
    assert BACKUP_KEY not in capsys.readouterr().out


@pytest.fixture()
def update_flow(configuration, monkeypatch):
    root, config = configuration
    calls = []
    state = {"source": OLD_SHA, "running": OLD_SHA, "image": OLD_IMAGE, "failure": None,
             "public": None, "final_local": True, "confirm": f"APPLY {NEW_SHA}"}

    def status(_root, _config):
        calls.append("status")
        result = production_report(state["running"], state["image"], public=state["public"])
        result["source_sha"] = state["source"]
        if state["running"] == NEW_SHA and not state["final_local"]:
            result["local"]["ready"] = False
        return result

    def source(_root, target, running):
        calls.append("qualify_source")
        assert target == NEW_SHA and running == OLD_SHA
        return OLD_SHA

    def ci(target):
        calls.append("ci")
        assert target == NEW_SHA
        if state["failure"] == "ci":
            raise manager.ManagerError("ci_missing")
        return {"run_id": 101, "head_sha": target}

    def confirm(_prompt):
        calls.append("confirm")
        assert f"APPLY {NEW_SHA}" in _prompt
        return state["confirm"]

    def key():
        calls.append("key")
        if state["failure"] == "key":
            raise manager.ManagerError("secure_32_byte_base64_backup_key_required")
        return BACKUP_KEY

    def checkout(_root, *arguments):
        calls.append("checkout")
        assert arguments == ("checkout", "--detach", "--no-overwrite-ignore", NEW_SHA)
        state["source"] = NEW_SHA
        return ""

    def execute(_root, _config, operation, target, **kwargs):
        calls.append(operation)
        assert target == NEW_SHA
        assert "pg16_baseline_bridge" not in kwargs
        if operation == "build":
            assert "key" not in kwargs
            if state["failure"] == "build":
                raise manager.ManagerError("guarded_operation_failed_image_build_operator_attention_required")
            return {"image_id": NEW_IMAGE}
        if operation == "stop_failed_target":
            assert kwargs == {"image": NEW_IMAGE}
            state["running"] = None
            return {}
        assert operation == "upgrade" and kwargs == {"image": NEW_IMAGE, "key": BACKUP_KEY}
        if state["failure"] == "upgrade":
            raise manager.ManagerError("guarded_operation_failed_prepare_operator_attention_required")
        state.update(running=NEW_SHA, image=NEW_IMAGE)
        return {"recovery_directory": "upgrade-isolated123"}

    monkeypatch.setattr(manager, "status", status)
    monkeypatch.setattr(manager, "qualify_source", source)
    monkeypatch.setattr(manager, "qualify_ci", ci)
    monkeypatch.setattr("builtins.input", confirm)
    monkeypatch.setattr(manager, "backup_key", key)
    monkeypatch.setattr(manager, "source_state", lambda _root: {
        "source_sha": state["source"], "git_clean": True})
    monkeypatch.setattr(manager, "git", checkout)
    monkeypatch.setattr(manager.deploy, "release_source", lambda _root, target: calls.append("release_source"))
    monkeypatch.setattr(manager, "executor", execute)
    return SimpleNamespace(root=root, config=config, calls=calls, state=state)


def test_update_orders_qualification_confirmation_build_and_guarded_upgrade(update_flow, capsys):
    subject = update_flow
    manager.update(subject.root, subject.config, NEW_SHA)
    assert subject.calls == ["status", "qualify_source", "ci", "confirm", "key", "status",
                             "checkout", "release_source", "build", "status", "ci", "upgrade", "status"]
    assert subject.state["running"] == NEW_SHA and subject.state["image"] == NEW_IMAGE
    output = capsys.readouterr().out
    assert '"result": "update_complete"' in output and BACKUP_KEY not in output
    assert subject.config["backup_dir"] not in output


@pytest.mark.parametrize("confirmation", ["", "yes", "APPLY main", f"APPLY {OLD_SHA}",
                                         f"APPLY {NEW_SHA[:12]}"])
def test_cancelled_confirmation_causes_zero_checkout_build_or_stop(update_flow, confirmation):
    subject = update_flow
    subject.state["confirm"] = confirmation
    with pytest.raises(manager.ManagerError, match="operator_cancelled"):
        manager.update(subject.root, subject.config, NEW_SHA)
    assert subject.calls == ["status", "qualify_source", "ci", "confirm"]
    assert subject.state["source"] == subject.state["running"] == OLD_SHA


@pytest.mark.parametrize("failure", ["ci", "key", "build"])
def test_pre_stop_failure_preserves_running_application(update_flow, failure):
    subject = update_flow
    subject.state["failure"] = failure
    with pytest.raises(manager.ManagerError):
        manager.update(subject.root, subject.config, NEW_SHA)
    assert "upgrade" not in subject.calls
    assert subject.state["running"] == OLD_SHA and subject.state["image"] == OLD_IMAGE
    if failure != "build":
        assert "checkout" not in subject.calls and "build" not in subject.calls


def test_source_change_during_confirmation_prevents_checkout(update_flow, monkeypatch):
    subject = update_flow
    monkeypatch.setattr(manager, "source_state", lambda _root: {
        "source_sha": OLD_SHA, "git_clean": False})
    with pytest.raises(manager.ManagerError, match="source_changed_during_confirmation"):
        manager.update(subject.root, subject.config, NEW_SHA)
    assert "checkout" not in subject.calls and "build" not in subject.calls


def test_post_stop_failure_does_not_retry_or_restart_old_release(update_flow):
    subject = update_flow
    subject.state["failure"] = "upgrade"
    with pytest.raises(manager.ManagerError, match="prepare_operator_attention_required"):
        manager.update(subject.root, subject.config, NEW_SHA)
    assert subject.calls.count("upgrade") == 1
    assert subject.calls[-1] == "upgrade"
    assert not {"start", "restore", "rollback", "stop"}.intersection(subject.calls)
    assert subject.state["source"] == NEW_SHA


def test_post_update_local_readiness_is_required(update_flow):
    subject = update_flow
    subject.state["final_local"] = False
    with pytest.raises(manager.ManagerError, match="local_production_qualification_failed"):
        manager.update(subject.root, subject.config, NEW_SHA)
    assert subject.calls.count("upgrade") == 1 and subject.calls[-1] == "stop_failed_target"
    assert subject.state["running"] is None


def test_public_failure_preserves_successfully_deployed_local_app(update_flow):
    subject = update_flow
    subject.state["public"] = {"ready": False}
    with pytest.raises(manager.ManagerError,
                       match="public_qualification_failed_local_application_preserved"):
        manager.update(subject.root, subject.config, NEW_SHA)
    assert subject.state["running"] == NEW_SHA and subject.state["image"] == NEW_IMAGE
    assert subject.calls.count("upgrade") == 1
    assert not {"start", "rollback", "stop", "restore"}.intersection(subject.calls)


def test_restart_uses_existing_guarded_start_without_release_changes(configuration, monkeypatch):
    root, config = configuration
    calls = []
    monkeypatch.setattr(manager, "source_state", lambda _root: {
        "source_sha": OLD_SHA, "git_clean": True})
    monkeypatch.setattr(manager, "container_status", lambda *_: production_report()["app"])
    monkeypatch.setattr(manager, "executor", lambda *args, **kwargs: calls.append((args, kwargs)))
    monkeypatch.setattr(manager, "status", lambda *_: production_report())
    monkeypatch.setattr(manager, "git", lambda *_: pytest.fail("restart changed checkout"))
    manager.restart(root, config)
    assert calls == [((root, config, "start", OLD_SHA), {"image": OLD_IMAGE})]


def test_restart_refuses_a_release_mismatch(configuration, monkeypatch):
    root, config = configuration
    monkeypatch.setattr(manager, "source_state", lambda _root: {
        "source_sha": NEW_SHA, "git_clean": True})
    monkeypatch.setattr(manager, "container_status", lambda *_: production_report()["app"])
    monkeypatch.setattr(manager, "executor", lambda *_a, **_k: pytest.fail("restart changed release"))
    with pytest.raises(manager.ManagerError, match="release_change_requires_upgrade"):
        manager.restart(root, config)


@pytest.mark.parametrize("mode", ["replace", "grafts", "assume", "skip", "tls"])
def test_local_git_overrides_cannot_change_release_trust(release_repository, monkeypatch, mode):
    root, current, target = release_repository
    if mode == "replace":
        git(root, "replace", current, target)
    elif mode == "grafts":
        (root / ".git/info/grafts").write_text(current + "\n", "utf-8")
    elif mode in {"assume", "skip"}:
        flag = "--assume-unchanged" if mode == "assume" else "--skip-worktree"
        git(root, "update-index", flag, "release-marker.txt")
    else:
        git(root, "config", "http.https://github.com/.sslVerify", "false")
    calls = intercept_fetch(monkeypatch)
    with pytest.raises(manager.ManagerError):
        manager.qualify_source(root, target, current)
    assert not any("fetch" in call for call in calls)


def test_stopped_app_uses_configured_binding_for_guarded_restart(configuration, monkeypatch):
    root, config = configuration
    calls = []
    replies = iter(["c" * 64, "exited unhealthy", OLD_IMAGE, OLD_SHA,
                    json.dumps([{"HostIp": "127.0.0.1", "HostPort": "10000"}])])

    def query(_root, args, **_kwargs):
        calls.append(args)
        return next(replies)

    monkeypatch.setattr(manager, "command", query)
    assert not manager.container_status(root, config["project"], "app")["running"]
    assert ".HostConfig.PortBindings" in calls[-1][-2]


def test_ci_rerun_during_build_blocks_shutdown(update_flow, monkeypatch):
    subject = update_flow
    attempts = []

    def qualification(_sha):
        attempts.append(True)
        if len(attempts) == 2:
            raise manager.CIError("CI_RUN_PENDING")
        return {"qualified": True, "run_id": 1, "run_attempt": 1}

    monkeypatch.setattr(manager, "qualify_ci", qualification)
    with pytest.raises(manager.CIError, match="CI_RUN_PENDING"):
        manager.update(subject.root, subject.config, NEW_SHA)
    assert "build" in subject.calls and "upgrade" not in subject.calls
    assert subject.state["running"] == OLD_SHA


@pytest.fixture()
def target_executor(configuration):
    """Fresh child interpreter with test-only primitives; no Docker, DB or network."""
    root, config = configuration
    (root / "scripts").mkdir()
    source = '''
import json, os
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
IMAGE = "sha256:" + "2" * 64
class DeploymentError(RuntimeError):
    pass
def record(event):
    with (ROOT / "events.jsonl").open("a") as output:
        output.write(json.dumps(event) + "\\n")
def run(command, *, cwd, env=None, **kwargs):
    assert env is not None
    if command[0] == "git":
        assert "BACKUP_ENCRYPTION_KEY" not in env
    else:
        assert "BACKUP_ENCRYPTION_KEY" in env
    record(command[0])
class Deployment:
    def __init__(self, root, sha, env_file, project):
        self.stage = "release_validation"
        self.image = ""
        self.identities = 0
        assert env_file == root / ".env"
    def image_identity(self):
        self.identities += 1
        if (ROOT / "changed-tag").exists() and self.identities > 1:
            return "sha256:" + "3" * 64
        return IMAGE
    def validate(self):
        self.image = self.image_identity()
        run(["git"], cwd=ROOT)
    def build(self):
        assert "BACKUP_ENCRYPTION_KEY" not in os.environ
        record("build")
        return self.image_identity()
    def upgrade(self, backup, actor, *, pg16_baseline_bridge=False):
        self.validate()
        assert actor == 17 and not pg16_baseline_bridge
        run(["backup"], cwd=ROOT, env={"BACKUP_ENCRYPTION_KEY": os.environ["BACKUP_ENCRYPTION_KEY"]})
        record("upgrade")
        return backup / "upgrade-isolated123"
    def restart(self):
        assert "BACKUP_ENCRYPTION_KEY" not in os.environ
        self.validate()
        record("start")
'''
    (root / "scripts/production_deploy.py").write_text(source, "utf-8")
    return root, config


def test_fresh_executor_uses_target_primitives_and_limits_secret_environment(target_executor,
                                                                          monkeypatch, capsys):
    root, config = target_executor
    monkeypatch.setenv("BACKUP_ENCRYPTION_KEY", "inherited-key-must-not-reach-build")
    assert manager.executor(root, config, "build", NEW_SHA) == {"image_id": NEW_IMAGE}
    assert manager.executor(root, config, "upgrade", NEW_SHA, image=NEW_IMAGE, key=BACKUP_KEY) == {
        "recovery_directory": "upgrade-isolated123"}
    manager.executor(root, config, "start", NEW_SHA, image=NEW_IMAGE)
    events = (root / "events.jsonl").read_text()
    assert [json.loads(line) for line in events.splitlines()] == [
        "build", "git", "git", "backup", "upgrade", "git", "git", "start"]
    assert BACKUP_KEY not in events + capsys.readouterr().out
    assert not (root / ".env").exists()


def test_exact_image_is_pinned_again_on_upgrade_validation(target_executor):
    root, config = target_executor
    (root / "changed-tag").touch()
    with pytest.raises(manager.ManagerError, match="guarded_operation_failed_release_validation"):
        manager.executor(root, config, "upgrade", NEW_SHA, image=NEW_IMAGE, key=BACKUP_KEY)
    assert '"upgrade"' not in (root / "events.jsonl").read_text()


def test_secret_never_appears_in_argv_and_child_environment_is_cleared(configuration, monkeypatch):
    root, config = configuration
    environments = []

    def query(_root, argv, *, env, timeout):
        assert BACKUP_KEY not in " ".join(argv)
        assert env["BACKUP_ENCRYPTION_KEY"] == BACKUP_KEY
        environments.append(env)
        raise RuntimeError("untrusted child error " + BACKUP_KEY)

    monkeypatch.setattr(manager, "command", query)
    with pytest.raises(RuntimeError):
        manager.executor(root, config, "upgrade", NEW_SHA, image=NEW_IMAGE, key=BACKUP_KEY)
    assert "BACKUP_ENCRYPTION_KEY" not in environments[0]


def test_frozen_snapshot_survives_replacing_original_manager_and_imports_target(tmp_path, capfd,
                                                                             monkeypatch):
    root = tmp_path / "installation with spaces"
    scripts = root / "scripts"
    scripts.mkdir(parents=True)
    original = '''
import os, subprocess, sys
from pathlib import Path
def main(argv, *, root, frozen):
    assert frozen and argv == ["restart"]
    assert "BACKUP_ENCRYPTION_KEY" not in os.environ
    assert Path(__file__).parent != root / "scripts"
    assert {p.name for p in Path(__file__).parent.iterdir()} == {
        "production_manager.py", "production_manager_ci.py", "production_deploy.py"}
    target = root / "scripts/production_manager.py"
    target.write_text("print('fresh-target')", encoding="utf-8")
    assert old_code() == "frozen-manager"
    result = subprocess.run([sys.executable, "-I", "-B", str(target)],
                            capture_output=True, text=True, check=True)
    assert result.stdout.strip() == "fresh-target"
    print(old_code())
    return 0
def old_code():
    return "frozen-manager"
'''
    (scripts / "production_manager.py").write_text(original, "utf-8")
    for name in ("production_deploy.py", "production_manager_ci.py"):
        (scripts / name).write_text("# isolated bootstrap fixture\n", "utf-8")
    (root / ".env").write_text("not-a-real-secret", "utf-8")
    monkeypatch.setenv("BACKUP_ENCRYPTION_KEY", BACKUP_KEY)
    assert manager.frozen_run(root, ["restart"]) == 0
    assert "frozen-manager" in capfd.readouterr().out
    assert not list((root / ".tmp").glob("operator-bootstrap-*"))
    assert (root / ".env").read_text() == "not-a-real-secret"


def test_executor_os_lock_blocks_another_process_and_releases(tmp_path):
    code = '''
import sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from scripts.production_deploy import operation_lock, DeploymentError
try:
    with operation_lock(Path(sys.argv[2]), "isolated-project"):
        print("acquired")
except DeploymentError:
    print("blocked")
'''
    command = [sys.executable, "-I", "-B", "-c", code, str(ROOT), str(tmp_path)]
    with manager.deploy.operation_lock(tmp_path, "isolated-project"):
        child = subprocess.run(command, capture_output=True, text=True, timeout=20, check=True)
        assert child.stdout.strip() == "blocked"
    child = subprocess.run(command, capture_output=True, text=True, timeout=20, check=True)
    assert child.stdout.strip() == "acquired"


@pytest.mark.skipif(os.name != "nt", reason="Windows host named mutex")
def test_windows_host_mutex_blocks_other_processes_without_production_lock():
    name = "Global\\AssetCore-QA-" + uuid.uuid4().hex
    code = '''
import sys
sys.path.insert(0, sys.argv[1])
from scripts.production_manager import windows_host_lock, ManagerError
try:
    with windows_host_lock(sys.argv[2]):
        print("acquired")
except ManagerError:
    print("blocked")
'''
    command = [sys.executable, "-I", "-B", "-c", code, str(ROOT), name]
    with manager.windows_host_lock(name):
        child = subprocess.run(command, capture_output=True, text=True, timeout=20, check=True)
        assert child.stdout.strip() == "blocked"
    child = subprocess.run(command, capture_output=True, text=True, timeout=20, check=True)
    assert child.stdout.strip() == "acquired"


def test_main_does_not_echo_untrusted_exception_or_secret(configuration, monkeypatch, capsys):
    root, _ = configuration

    def fail(_root):
        raise RuntimeError("internal path and credential " + BACKUP_KEY)

    monkeypatch.setattr(manager, "load_config", fail)
    assert manager.main(["status"], root=root) == 1
    output = capsys.readouterr()
    assert BACKUP_KEY not in output.out + output.err
    assert '"result": "operator_operation_failed"' in output.out
