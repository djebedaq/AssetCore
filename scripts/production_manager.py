"""Interactive host orchestration around the authoritative production executor.

Mutating commands re-execute a frozen snapshot before changing this checkout.
The snapshot holds both operator and executor locks; a fresh interpreter loads
the qualified target executor. Neither the running manager nor its imports are
read from files being replaced. No production environment file is copied.
"""

from __future__ import annotations

import argparse
import base64
import binascii
import getpass
import ipaddress
import json
import os
import re
import stat
import subprocess
import sys
import tempfile
import urllib.request
import warnings
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import urlsplit

if __package__:
    from . import production_deploy as deploy
    from .production_manager_ci import CIError, qualify_ci
else:
    import production_deploy as deploy
    from production_manager_ci import CIError, qualify_ci

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ".assetcore-operator.json"
ORIGIN = "https://github.com/djebedaq/AssetCore.git"
ORIGINS = {ORIGIN, ORIGIN[:-4], "git@github.com:djebedaq/AssetCore.git"}
CHECKS = {
    "runtime": "runtime_ready", "database": "database_connected",
    "schema": "database_schema_current", "configuration": "configuration_valid",
    "catalog": "catalog_integrity_verified", "cryptography": "cryptography_operational",
    "license": "license_evaluated",
}
STAGES = {
    "release_validation", "image_build", "current_state", "backup_toolchain_preflight",
    "recovery_directory_creation", "recovery_directory_qualification", "stop_writers",
    "stopped_state_validation", "backup", "verify", "prepare", "start_and_readiness",
    "post_deploy_smoke", "database_start_and_readiness",
}


class ManagerError(RuntimeError):
    pass


class SafeParser(argparse.ArgumentParser):
    def error(self, message):
        # argparse normally echoes invalid values, including accidentally pasted secrets.
        raise ManagerError("invalid_arguments")


def clean_environment() -> dict[str, str]:
    env = os.environ.copy()
    env.pop("BACKUP_ENCRYPTION_KEY", None)
    # Host overrides must not redirect Git, Compose or target Python imports.
    for name in list(env):
        if name.startswith(("GIT_", "COMPOSE_", "PYTHON")) or name == "ASSETCORE_IMAGE":
            env.pop(name)
    env["GIT_TERMINAL_PROMPT"] = "0"
    env["GIT_NO_REPLACE_OBJECTS"] = "1"
    return env


def command(root: Path, args: list[str], *, env: dict | None = None,
            timeout: int = 120) -> str:
    return deploy.run(args, cwd=root, env=clean_environment() if env is None else env,
                      timeout=timeout)


def git(root: Path, *args: str) -> str:
    return command(root, ["git", "-c", f"safe.directory={root}",
                          "-c", "core.hooksPath=/dev/null", *args])


def exact_sha(value: str) -> str:
    if not isinstance(value, str) or not deploy.SHA.fullmatch(value):
        raise ManagerError("exact_40_character_target_sha_required")
    return value


def public_origin(value: str | None) -> str | None:
    if value is None:
        return None
    try:
        parsed = urlsplit(value)
        host = parsed.hostname
        if (not isinstance(value, str) or not value.isascii() or
                any(ord(char) <= 32 for char in value) or parsed.scheme != "https" or
                not host or parsed.username or parsed.password or parsed.query or
                parsed.fragment or parsed.path not in ("", "/") or parsed.port not in (None, 443)):
            raise ValueError
        # Public readiness is a configured DNS origin, never an arbitrary IP/internal URL.
        try:
            ipaddress.ip_address(host)
        except ValueError:
            pass
        else:
            raise ValueError
        if ("." not in host or host.endswith((".local", ".localhost", ".internal")) or
                not re.fullmatch(r"[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?", host) or
                any(not label or len(label) > 63 or label.startswith("-") or
                    label.endswith("-") for label in host.split("."))):
            raise ValueError
        return f"https://{host}"
    except (ValueError, TypeError, AttributeError):
        raise ManagerError("public_https_origin_required") from None


def validate_config(value: dict, root: Path) -> dict:
    required = {"version", "backup_dir", "actor_user_id", "project", "public_origin"}
    if not isinstance(value, dict) or set(value) != required:
        raise ManagerError("operator_config_fields_invalid")
    if type(value["version"]) is not int or value["version"] != 1:
        raise ManagerError("operator_config_version_invalid")
    if type(value["actor_user_id"]) is not int or not 1 <= value["actor_user_id"] <= 2147483647:
        raise ManagerError("positive_audit_actor_required")
    if not isinstance(value["project"], str) or not re.fullmatch(
            r"[a-z0-9][a-z0-9_-]{0,62}", value["project"]):
        raise ManagerError("invalid_compose_project")
    raw = value["backup_dir"]
    if not isinstance(raw, str) or not raw or any(c in raw for c in "\r\n\0,"):
        raise ManagerError("approved_backup_parent_required")
    path = Path(raw)
    if (not path.is_absolute() or path.is_symlink() or not path.is_dir() or
            path.resolve().is_relative_to(root.resolve())):
        raise ManagerError("approved_backup_parent_required")
    if os.name != "nt" and path.stat().st_mode & stat.S_IWOTH:
        raise ManagerError("backup_parent_world_writable")
    return {**value, "backup_dir": str(path.resolve()),
            "public_origin": public_origin(value["public_origin"])}


def load_config(root: Path) -> dict:
    path = root / CONFIG
    if path.is_symlink() or path.stat().st_size > 8192:
        raise ManagerError("operator_config_invalid")
    return validate_config(json.loads(path.read_text("utf-8")), root)


def configure(root: Path, args) -> None:
    value = validate_config({"version": 1, "backup_dir": args.backup_dir,
                             "actor_user_id": args.actor_user_id, "project": args.project,
                             "public_origin": args.public_origin}, root)
    path = root / CONFIG
    if path.exists() and load_config(root)["project"] != value["project"]:
        raise ManagerError("compose_project_change_requires_separate_procedure")
    if git(root, "ls-files", "--", CONFIG) or not git(root, "check-ignore", "--", CONFIG):
        raise ManagerError("operator_config_must_be_gitignored")
    # Atomic write, private on POSIX; Windows inherits the checkout ACL.
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=root / ".tmp",
                                     prefix="operator-config-", delete=False) as handle:
        temporary = Path(handle.name)
        json.dump(value, handle, ensure_ascii=True, indent=2)
    try:
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def source_state(root: Path) -> dict:
    return {"source_sha": exact_sha(git(root, "rev-parse", "HEAD")),
            "git_clean": not bool(git(root, "status", "--porcelain", "--untracked-files=all"))}


def qualify_source(root: Path, target: str, running: str) -> str:
    exact_sha(target)
    exact_sha(running)
    state = source_state(root)
    if not state["git_clean"]:
        raise ManagerError("clean_release_checkout_required")
    if state["source_sha"] != running:
        raise ManagerError("source_running_release_mismatch_recovery_required")
    if git(root, "remote", "get-url", "--all", "origin") not in ORIGINS:
        raise ManagerError("assetcore_repository_required")
    if git(root, "for-each-ref", "--format=%(refname)", "refs/replace/"):
        raise ManagerError("git_replacement_objects_not_allowed")
    grafts = Path(git(root, "rev-parse", "--git-path", "info/grafts"))
    if not grafts.is_absolute():
        grafts = root / grafts
    if grafts.exists():
        raise ManagerError("git_grafts_not_allowed")
    if any(line[:1].islower() or line.startswith("S ")
           for line in git(root, "ls-files", "-v").splitlines()):
        raise ManagerError("hidden_worktree_changes_not_allowed")
    # Pin the network destination, refspec and protocol; do not trust local fetch config.
    names = git(root, "config", "--list", "--name-only").splitlines()
    if any(re.fullmatch(r"url\..*\.insteadof", name, flags=re.IGNORECASE) for name in names):
        raise ManagerError("git_url_rewrite_not_allowed")
    if any(name.lower().startswith("http.") and name.lower().endswith(
            (".sslverify", ".followredirects", ".proxy")) for name in names):
        raise ManagerError("git_http_override_not_allowed")
    git(root, "-c", "http.followRedirects=false", "-c", "protocol.allow=never",
        "-c", "http.sslVerify=true", "-c", "http.proxy=",
        "-c", "protocol.https.allow=always", "fetch", "--no-tags", "--no-recurse-submodules",
        ORIGIN, "+refs/heads/main:refs/remotes/origin/main")
    if git(root, "rev-parse", "--verify", f"{target}^{{commit}}") != target:
        raise ManagerError("target_commit_unavailable")
    if git(root, "merge-base", target, "refs/remotes/origin/main") != target:
        raise ManagerError("target_not_in_approved_main_history")
    if target == running or git(root, "merge-base", running, target) != running:
        raise ManagerError("forward_only_update_required")
    return state["source_sha"]


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *_args, **_kwargs):
        return None


def read_endpoint(url: str) -> dict:
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    try:
        with opener.open(url, timeout=10) as response:
            if response.status != 200 or response.geturl() != url:
                raise ValueError
            data = response.read(65537)
            if len(data) > 65536:
                raise ValueError
            value = json.loads(data)
            if not isinstance(value, dict):
                raise ValueError
            return value
    except Exception:
        raise ManagerError("readiness_transport_or_response_failed") from None


def readiness(value: dict) -> dict:
    checks = value.get("checks", {})
    passed = {name: isinstance(checks, dict) and isinstance(checks.get(name), dict) and
              checks[name].get("status") == "pass" and checks[name].get("code") == code
              for name, code in CHECKS.items()}
    return {"ready": value.get("status") == "ready" and value.get("service") == "AssetCore"
            and all(passed.values()), "checks": passed}


def container_status(root: Path, project: str, service: str) -> dict:
    identifiers = command(root, ["docker", "ps", "--all", "--quiet", "--no-trunc",
                          "--filter", f"label=com.docker.compose.project={project}",
                          "--filter", f"label=com.docker.compose.service={service}",
                          "--filter", "label=com.docker.compose.oneoff=False"]).splitlines()
    if len(identifiers) != 1 or not re.fullmatch(r"[0-9a-f]{64}", identifiers[0]):
        raise ManagerError("one_existing_service_container_required")
    state = command(root, ["docker", "inspect", "--format",
                          "{{.State.Status}} {{if .State.Health}}{{.State.Health.Status}}{{end}}",
                          identifiers[0]])
    image = command(root, ["docker", "inspect", "--format", "{{.Image}}", identifiers[0]])
    if not deploy.IMAGE_ID.fullmatch(image):
        raise ManagerError("invalid_running_image_identity")
    result = {"running": state.startswith("running "), "healthy": state == "running healthy",
              "image_id": image}
    if service == "app":
        result["release_sha"] = exact_sha(command(root, [
            "docker", "image", "inspect", image, "--format",
            '{{index .Config.Labels "org.opencontainers.image.revision"}}']))
        port_source = ".NetworkSettings.Ports" if result["running"] else ".HostConfig.PortBindings"
        bindings = json.loads(command(root, ["docker", "inspect", "--format",
            '{{json (index ' + port_source + ' "10000/tcp")}}', identifiers[0]]))
        if (not isinstance(bindings, list) or len(bindings) != 1 or
                bindings[0].get("HostIp") != "127.0.0.1" or
                not re.fullmatch(r"[0-9]{1,5}", bindings[0].get("HostPort", "")) or
                not 1 <= int(bindings[0]["HostPort"]) <= 65535):
            raise ManagerError("single_loopback_app_binding_required")
        result["port"] = int(bindings[0]["HostPort"])
    return result


def status(root: Path, config: dict) -> dict:
    result = {"docker_available": False, "git_clean": None, "source_sha": None,
              "app": None, "db": None, "local": {"ready": False}, "health": False,
              "public": None if not config["public_origin"] else {"ready": False}}
    try:
        result.update(source_state(root))
    except Exception:
        pass
    try:
        command(root, ["docker", "info", "--format", "{{.ServerVersion}}"])
        result["docker_available"] = True
    except Exception:
        return result
    for service in ("app", "db"):
        try:
            result[service] = container_status(root, config["project"], service)
        except Exception:
            pass
    if result["app"] and result["app"]["running"]:
        origin = f'http://127.0.0.1:{result["app"]["port"]}'
        try:
            result["local"] = readiness(read_endpoint(origin + "/api/ready"))
            result["health"] = read_endpoint(origin + "/api/health").get("status") == "ok"
        except Exception:
            pass
    if config["public_origin"]:
        try:
            result["public"] = readiness(read_endpoint(config["public_origin"] + "/api/ready"))
        except Exception:
            pass
    return result


def require_local(report: dict, sha: str | None = None, image: str | None = None) -> None:
    if not (report["docker_available"] and report["git_clean"] and report["app"] and
            report["db"] and report["app"]["healthy"] and report["db"]["healthy"] and
            report["local"]["ready"] and report["health"]):
        raise ManagerError("local_production_qualification_failed")
    if ((sha and report["app"]["release_sha"] != sha) or
            (image and report["app"]["image_id"] != image)):
        raise ManagerError("running_release_identity_mismatch")


def backup_key() -> str:
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", getpass.GetPassWarning)
            value = getpass.getpass("BACKUP_ENCRYPTION_KEY (скрит вход): ")
        if len(value) != 44 or len(base64.b64decode(value, validate=True)) != 32:
            raise ValueError
        return value
    except (ValueError, binascii.Error, EOFError, getpass.GetPassWarning):
        raise ManagerError("secure_32_byte_base64_backup_key_required") from None


# This small adapter is frozen with the manager. Only the fresh child imports the
# target deployment module. The parent already owns its authoritative OS lock.
EXECUTOR = r'''
import json, os, sys
from pathlib import Path
sys.path.insert(0, str(Path(sys.argv[1]) / "scripts"))
import production_deploy as d
root, operation, sha, project, expected, backup, actor = sys.argv[1:]
# release_source uses module-level run(env=None), outside Deployment.command.
# Remove the operational key from those Git calls too; explicit backup/verify
# child environments remain controlled by the existing backup_secret contract.
original_run = d.run
def scoped_run(command, *, cwd, env=None, **kwargs):
    if env is None:
        env = os.environ.copy()
        env.pop("BACKUP_ENCRYPTION_KEY", None)
    return original_run(command, cwd=cwd, env=env, **kwargs)
d.run = scoped_run
class PinnedDeployment(d.Deployment):
    def image_identity(self):
        identity = super().image_identity()
        if expected and identity != expected:
            raise d.DeploymentError("immutable_target_changed")
        return identity
job = PinnedDeployment(Path(root), sha, Path(root) / ".env", project)
try:
    if operation == "build":
        result = {"image_id": job.build()}
    else:
        job.validate()
        if job.image != expected:
            raise d.DeploymentError("immutable_target_changed")
        if operation == "upgrade":
            destination = job.upgrade(Path(backup), int(actor))
            result = {"recovery_directory": destination.name}
        elif operation == "start":
            job.restart()
            result = {}
        elif operation == "stop_failed_target":
            if job.current_image(running=False) != expected:
                raise d.DeploymentError("running_target_changed")
            job.dc("stop", "app")
            result = {}
        else:
            raise d.DeploymentError("invalid_operation")
    print(json.dumps({"ok": True, **result}))
except (Exception, KeyboardInterrupt):
    print(json.dumps({"ok": False, "stage": job.stage}))
finally:
    os.environ.pop("BACKUP_ENCRYPTION_KEY", None)
'''


def executor(root: Path, config: dict, operation: str, sha: str, *,
             image: str = "", key: str | None = None) -> dict:
    environment = clean_environment()
    if key is not None:
        if operation != "upgrade":
            raise ManagerError("backup_secret_scope_invalid")
        environment["BACKUP_ENCRYPTION_KEY"] = key
    try:
        raw = command(root, [sys.executable, "-I", "-B", "-c", EXECUTOR, str(root),
                      operation, sha, config["project"], image, config["backup_dir"],
                      str(config["actor_user_id"])], env=environment, timeout=7200)
    finally:
        environment.pop("BACKUP_ENCRYPTION_KEY", None)
    result = json.loads(raw)
    if result.get("ok") is not True:
        stage = result.get("stage")
        stage = stage if stage in STAGES else "unknown"
        raise ManagerError("guarded_operation_failed_" + stage + "_operator_attention_required")
    if operation == "build":
        if not deploy.IMAGE_ID.fullmatch(result.get("image_id", "")):
            raise ManagerError("invalid_built_image_identity")
        return {"image_id": result["image_id"]}
    if operation == "upgrade":
        name = result.get("recovery_directory", "")
        if not re.fullmatch(r"upgrade-[a-zA-Z0-9_-]{6,64}", name):
            raise ManagerError("invalid_recovery_receipt")
        return {"recovery_directory": name}
    return {}


def emit(code: str, **fields) -> None:
    messages = {
        "current_status": "Текущо състояние преди обновяване.",
        "status": "Състояние на инсталацията; проверката не променя услугите.",
        "confirmation_required": "Проверете точните версии и потвърдете одобрения SHA.",
        "building_exact_target": "Подготвя се image от точната одобрена версия.",
        "guarded_upgrade_starting": "Започва защитеното обновяване с проверен backup.",
        "post_update_status": "Независима проверка след обновяването.",
        "post_restart_status": "Проверка след стартиране на същата версия.",
        "update_complete": "Обновяването и задължителните проверки са успешни.",
        "restart_complete": "Същата версия е стартирана успешно.",
        "operator_configured": "Локалната несекретна конфигурация е записана.",
        "operator_cancelled": "Операцията е отказана преди промяна на версията.",
        "public_qualification_failed_local_application_preserved":
            "Публичната проверка е неуспешна. Локалното приложение остава стартирано.",
        "license_qualification_failed_application_preserved":
            "Лицензната проверка изисква намеса. Приложението остава достъпно за разрешените read/export/backup операции.",
    }
    fallback = ("GitHub CI не е положително потвърден; няма спиране на приложението."
                if code.startswith("ci_") else
                "Операцията е прекратена. Проверете кода и recovery процедурата; няма автоматичен retry или rollback.")
    print(json.dumps({"result": code, "message": messages.get(code, fallback), **fields},
                     ensure_ascii=False), flush=True)


def update(root: Path, config: dict, target: str) -> None:
    exact_sha(target)
    current = status(root, config)
    emit("current_status", **current)
    require_local(current)
    source = qualify_source(root, target, current["app"]["release_sha"])
    ci = qualify_ci(target)
    emit("confirmation_required", current_sha=source, target_sha=target, ci=ci,
         backup_required=True,
         phases=["build", "preflight", "stop_writers", "backup", "verify", "prepare", "readiness"])
    if input(f"За прилагане въведете APPLY {target}: ") != f"APPLY {target}":
        raise ManagerError("operator_cancelled")
    key = backup_key()
    try:
        # Revalidate after the unbounded human interaction before any checkout/build.
        if source_state(root) != {"source_sha": source, "git_clean": True}:
            raise ManagerError("source_changed_during_confirmation")
        before = status(root, config)
        require_local(before, source, current["app"]["image_id"])
        git(root, "checkout", "--detach", "--no-overwrite-ignore", target)
        deploy.release_source(root, target)
        emit("building_exact_target", target_sha=target)
        built = executor(root, config, "build", target)
        # Check the current app again; build and source preparation never stop it.
        require_local(status(root, config), source, current["app"]["image_id"])
        ci = qualify_ci(target)  # A rerun started during build must block writer shutdown.
        emit("guarded_upgrade_starting", target_sha=target, **built)
        receipt = executor(root, config, "upgrade", target, image=built["image_id"], key=key)
    finally:
        key = None  # Never installed in the manager's process environment or persisted.
    final = status(root, config)
    emit("post_update_status", target_sha=target, **built, **receipt, **final)
    try:
        require_local(final, target, built["image_id"])
    except ManagerError:
        # Expiry must not take away the application's verified read/export/backup
        # paths. A licence-only qualification failure is nonzero, never success,
        # but must not add a shutdown absent from the authoritative executor.
        if final["local"].get("checks") == {**dict.fromkeys(CHECKS, True), "license": False}:
            try:
                require_local({**final, "local": {"ready": True}}, target, built["image_id"])
            except ManagerError:
                pass
            else:
                raise ManagerError("license_qualification_failed_application_preserved") from None
        # Match the existing executor's local smoke failure semantics: stop only
        # the confirmed target app, never restart an old image or roll back data.
        executor(root, config, "stop_failed_target", target, image=built["image_id"])
        raise
    if final["public"] is not None and not final["public"]["ready"]:
        raise ManagerError("public_qualification_failed_local_application_preserved")
    emit("update_complete", target_sha=target, ci=ci, **built, **receipt)


def restart(root: Path, config: dict) -> None:
    state = source_state(root)
    if not state["git_clean"]:
        raise ManagerError("clean_release_checkout_required")
    app = container_status(root, config["project"], "app")
    if app["release_sha"] != state["source_sha"]:
        raise ManagerError("release_change_requires_upgrade")
    executor(root, config, "start", state["source_sha"], image=app["image_id"])
    final = status(root, config)
    emit("post_restart_status", **final)
    require_local(final, state["source_sha"], app["image_id"])
    if final["public"] is not None and not final["public"]["ready"]:
        raise ManagerError("public_qualification_failed_local_application_preserved")
    emit("restart_complete")


@contextmanager
def windows_host_lock(name: str = "Global\\AssetCoreProductionOperator"):
    # Global named mutex covers different Windows accounts and checkouts without
    # requiring an Administrator-owned directory. Access denial also fails closed.
    import ctypes
    from ctypes import wintypes

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
    kernel.CreateMutexW.restype = wintypes.HANDLE
    kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel.WaitForSingleObject.restype = wintypes.DWORD
    kernel.ReleaseMutex.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = kernel.CreateMutexW(None, False, name)
    if not handle:
        raise ManagerError("operator_host_lock_unavailable")
    acquired = False
    try:
        acquired = kernel.WaitForSingleObject(handle, 0) in (0, 0x80)
        if not acquired:
            raise ManagerError("another_production_operation_is_running")
        yield
    finally:
        if acquired:
            kernel.ReleaseMutex(handle)
        kernel.CloseHandle(handle)


@contextmanager
def host_lock():
    if os.name == "nt":
        with windows_host_lock():
            yield
        return
    directory = Path(tempfile.gettempdir()) / "assetcore-production-operator"
    directory.mkdir(mode=0o700, exist_ok=True)
    if directory.is_symlink() or (os.name != "nt" and
            (directory.stat().st_uid != os.getuid() or directory.stat().st_mode & 0o077)):
        raise ManagerError("operator_lock_directory_not_private")
    with deploy.operation_lock(directory, "host"):
        yield


def frozen_run(root: Path, argv: list[str]) -> int:
    # No secrets exist at this point. Snapshot only these three tooling modules.
    directory = root / ".tmp"
    directory.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="operator-bootstrap-", dir=directory) as temporary:
        snapshot = Path(temporary)
        for name in ("production_manager.py", "production_manager_ci.py", "production_deploy.py"):
            (snapshot / name).write_bytes((root / "scripts" / name).read_bytes())
        bootstrap = (
            "import sys\nfrom pathlib import Path\n"
            "try:\n"
            "    sys.path.insert(0, sys.argv[1])\n"
            "    import production_manager as m\n"
            "    code = m.main(sys.argv[3:], root=Path(sys.argv[2]), frozen=True)\n"
            "except (Exception, KeyboardInterrupt):\n"
            "    print('{\"result\":\"operator_bootstrap_failed\"}')\n"
            "    code = 1\n"
            "raise SystemExit(code)\n"
        )
        # Inherit terminal for secure interactive input; worker emits only normalized output.
        result = subprocess.run([sys.executable, "-I", "-B", "-c", bootstrap,
                                 str(snapshot), str(root), *argv], cwd=root,
                                env=clean_environment(), check=False)
        return result.returncode


def main(argv: list[str] | None = None, *, root: Path = ROOT, frozen: bool = False) -> int:
    try:
        for stream in (sys.stdout, sys.stderr):
            if hasattr(stream, "reconfigure"):
                stream.reconfigure(encoding="utf-8", errors="replace")
        argv = list(sys.argv[1:] if argv is None else argv)
        parser = SafeParser(description="AssetCore: защитени операторски операции")
        commands = parser.add_subparsers(dest="operation", required=True, parser_class=SafeParser)
        config_parser = commands.add_parser("configure", help="Локална несекретна конфигурация")
        config_parser.add_argument("--backup-dir", required=True)
        config_parser.add_argument("--actor-user-id", required=True, type=int)
        config_parser.add_argument("--project", required=True)
        config_parser.add_argument("--public-origin")
        commands.add_parser("status", help="Само проверка на състоянието")
        commands.add_parser("restart", help="Защитен старт на същата версия")
        update_parser = commands.add_parser("update", help="Одобрена точна версия")
        update_parser.add_argument("--sha", required=True)
        args = parser.parse_args(argv)
        if args.operation == "update":
            exact_sha(args.sha)
        if args.operation == "status":
            result = status(root, load_config(root))
            emit("status", **result)
            require_local(result)
            if result["public"] is not None and not result["public"]["ready"]:
                raise ManagerError("public_qualification_failed")
            return 0
        if not frozen:
            return frozen_run(root, argv)
        with host_lock():
            if args.operation == "configure":
                (root / ".tmp").mkdir(exist_ok=True)
                configure(root, args)
                emit("operator_configured")
                return 0
            config = load_config(root)
            with deploy.operation_lock(root, config["project"]):
                if args.operation == "restart":
                    restart(root, config)
                else:
                    update(root, config, args.sha)
        return 0
    except (Exception, KeyboardInterrupt) as exc:
        # Only our own fixed codes cross the boundary, never exception/subprocess text.
        code = (str(exc) if type(exc) is ManagerError else
                exc.code.lower() if type(exc) is CIError else "operator_operation_failed")
        if not re.fullmatch(r"[a-z0-9_]{1,150}", code):
            code = "operator_operation_failed"
        emit(code)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
