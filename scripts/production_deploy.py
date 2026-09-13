"""Explicit, fail-closed Compose operations. No business logic or secret output."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import tarfile
import tempfile
import time
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SHA = re.compile(r"[0-9a-f]{40}\Z")
IMAGE_ID = re.compile(r"sha256:[0-9a-f]{64}\Z")
# One documented repair transition, never a fallback for arbitrary old releases.
PG16_BASELINE_SHA = "1de39f50dcd2d05fd298a6ea6a52ecca1e9ef160"
PG16_BASELINE_IMAGE = "sha256:1cd58e1157504009af17e06d1830a05dddcf213d4371e30ed6142eac5249263a"
PG16_BASELINE_REVISION = "20260826_0021"
PG16_BRIDGE_UNCHANGED_PATHS = (
    "backend/app", "backend/alembic", "backend/alembic.ini", "backend/requirements.txt",
)


class DeploymentError(RuntimeError):
    """Only controlled error codes may cross the command-line boundary."""


def run(command: list[str], *, cwd: Path, env: dict | None = None,
        input_text: str | None = None, timeout: int = 1800) -> str:
    try:
        result = subprocess.run(command, cwd=cwd, env=env, input=input_text,
                                text=True, capture_output=True, timeout=timeout, check=False)
    except (OSError, subprocess.SubprocessError):
        raise DeploymentError("command_unavailable_or_timed_out") from None
    if result.returncode:
        # Even Docker config errors/build logs may contain secrets. Never echo them.
        output = (result.stdout + result.stderr).casefold()
        for marker, code in (
            ("permission denied", "command_permission_denied"),
            ("no space left on device", "command_storage_exhausted"),
            ("server version mismatch", "command_postgres_client_version_mismatch"),
            ("pg_dump failed", "command_postgres_dump_failed"),
        ):
            if marker in output:
                raise DeploymentError(code)
        raise DeploymentError("command_failed")
    return result.stdout.strip()


def release_source(root: Path, sha: str) -> None:
    if not SHA.fullmatch(sha):
        raise DeploymentError("exact_40_character_release_sha_required")
    git = ["git", "-c", f"safe.directory={root}"]
    if run([*git, "rev-parse", "HEAD"], cwd=root) != sha:
        raise DeploymentError("release_sha_does_not_match_checkout")
    if run([*git, "status", "--porcelain", "--untracked-files=all"], cwd=root):
        raise DeploymentError("clean_release_checkout_required")


@contextmanager
def operation_lock(root: Path, project: str):
    # One operator per checkout/project. OS releases the lock after interruption.
    directory = root / ".tmp"
    directory.mkdir(exist_ok=True)
    with (directory / f"production-{project}.lock").open("a+b") as handle:
        handle.seek(0, 2)
        if handle.tell() == 0:
            handle.write(b"0")
            handle.flush()
        handle.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            raise DeploymentError("another_production_operation_is_running") from None
        try:
            yield
        finally:
            handle.seek(0)
            if os.name == "nt":
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def file_sha256(path: Path) -> str:
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


class Deployment:
    def __init__(self, root: Path, sha: str, env_file: Path, project: str = "assetcore"):
        if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,62}", project):
            raise DeploymentError("invalid_compose_project")
        self.root, self.sha, self.project = root.resolve(), sha, project
        self.env = os.environ.copy()
        self.env.pop("BACKUP_ENCRYPTION_KEY", None)
        self.compose = ["docker", "compose", "--project-directory", str(self.root),
                        "--project-name", project, "--env-file", str(env_file.resolve()),
                        "-f", str(self.root / "docker-compose.yml")]
        self.image = ""
        self.stage = "release_validation"

    def command(self, args: list[str], *, backup_secret: bool = False,
                input_text: str | None = None) -> str:
        environment = self.env.copy()
        if backup_secret:
            key = os.environ.get("BACKUP_ENCRYPTION_KEY")
            if not key:
                raise DeploymentError("operational_backup_key_required")
            environment["BACKUP_ENCRYPTION_KEY"] = key
        return run(args, cwd=self.root, env=environment, input_text=input_text)

    def dc(self, *args: str, **kwargs) -> str:
        return self.command([*self.compose, *args], **kwargs)

    def image_identity(self) -> str:
        value = json.loads(self.command([
            "docker", "image", "inspect", f"assetcore:{self.sha}", "--format",
            '{{json .Id}}',
        ]))
        if not isinstance(value, str) or not IMAGE_ID.fullmatch(value):
            raise DeploymentError("invalid_image_identity")
        revision = self.command([
            "docker", "image", "inspect", value, "--format",
            '{{index .Config.Labels "org.opencontainers.image.revision"}}',
        ])
        if not IMAGE_ID.fullmatch(value) or revision != self.sha:
            raise DeploymentError("image_revision_mismatch")
        return value

    def build(self) -> str:
        release_source(self.root, self.sha)
        # Export ONLY committed files, not ignored local .env/databases/build inputs.
        with tempfile.TemporaryDirectory(prefix="assetcore-release-") as temporary:
            directory = Path(temporary)
            archive, context = directory / "source.tar", directory / "context"
            self.command(["git", "-c", f"safe.directory={self.root}", "archive",
                          "--format=tar", f"--output={archive}", self.sha])
            context.mkdir()
            with tarfile.open(archive) as source:
                source.extractall(context, filter="data")
            self.stage = "image_build"
            self.command(["docker", "build", "--tag", f"assetcore:{self.sha}",
                          "--build-arg", f"ASSETCORE_RELEASE_SHA={self.sha}", str(context)])
        release_source(self.root, self.sha)
        return self.image_identity()

    def validate(self) -> None:
        release_source(self.root, self.sha)
        self.image = self.image_identity()
        self.env["ASSETCORE_IMAGE"] = self.image  # Immutable content ID, not mutable tag.
        self.dc("config", "--quiet")

    def probe(self, mode: str, actor: int | None = None, *, running: bool = False) -> dict:
        arguments = [mode] + ([str(actor)] if actor is not None else [])
        if running:
            # Works on a pre-PROD-01 image too; executes the same read-only probe.
            content = (self.root / "scripts" / "production_container.py").read_text("utf-8")
            result = self.dc("exec", "-T", "app", "python", "-", *arguments,
                             input_text=content)
        else:
            result = self.dc("run", "--rm", "--no-deps", "--pull", "never", "-T",
                             "app", "python", "scripts/production_container.py", *arguments)
        return json.loads(result)

    def current_image(self, *, running: bool) -> str:
        arguments = ["ps", "--quiet"] + ([] if running else ["--all"]) + ["app"]
        containers = self.dc(*arguments).splitlines()
        if len(containers) != 1 or not re.fullmatch(r"[0-9a-f]{12,64}", containers[0]):
            raise DeploymentError("one_existing_app_container_required")
        identity = self.command(["docker", "inspect", "--format", "{{.Image}}", containers[0]])
        if not IMAGE_ID.fullmatch(identity):
            raise DeploymentError("invalid_current_image_identity")
        return identity

    def prepare(self) -> None:
        self.stage = "prepare"
        self.dc("run", "--rm", "--no-deps", "--pull", "never", "-T", "migrate")

    def start(self) -> None:
        self.stage = "start_and_readiness"
        try:
            self.dc("up", "-d", "--no-deps", "--no-build", "--pull", "never",
                    "--wait", "--wait-timeout", "180", "app")
            self.stage = "post_deploy_smoke"
            self.probe("smoke", running=True)
        except (Exception, KeyboardInterrupt):
            self.dc("stop", "app")
            raise

    def initialize(self) -> None:
        self.validate()
        if self.dc("ps", "--all", "--quiet", "app"):
            raise DeploymentError("initialization_refuses_existing_app")
        self.stage = "empty_database_validation"
        self.dc("up", "-d", "--wait", "--wait-timeout", "120", "db")
        self.probe("empty")  # Refuses any existing user relation, not just machine rows.
        self.prepare()
        self.start()

    def restart(self) -> None:
        self.validate()
        if self.current_image(running=False) != self.image:
            raise DeploymentError("release_change_requires_upgrade")
        self.stage = "database_start_and_readiness"
        # Start only the existing database container; never create/build/pull it.
        containers = self.dc("ps", "--all", "--quiet", "db").splitlines()
        if len(containers) != 1 or not re.fullmatch(r"[0-9a-f]{12,64}", containers[0]):
            raise DeploymentError("one_existing_database_container_required")
        self.dc("start", "db")
        # Support Compose versions without start --wait; inspect only state, not logs/config.
        deadline = time.monotonic() + 120
        while True:
            state = self.command([
                "docker", "inspect", "--format",
                "{{.State.Status}} {{if .State.Health}}{{.State.Health.Status}}{{end}}",
                containers[0],
            ])
            if state == "running healthy":
                break
            if state != "running starting":
                raise DeploymentError("database_not_healthy")
            if time.monotonic() >= deadline:
                raise DeploymentError("database_health_timed_out")
            time.sleep(1)
        self.probe("existing")  # Validate production configuration without preparing it.
        self.start()  # No migration/seed/prepare, including on failure.

    def backup_image(self, previous_image: str, previous_revision: str, *,
                     pg16_baseline_bridge: bool) -> str:
        if not pg16_baseline_bridge:
            return previous_image
        if previous_image != PG16_BASELINE_IMAGE:
            raise DeploymentError("pg16_bridge_requires_exact_baseline_image")
        revision = self.command([
            "docker", "image", "inspect", previous_image, "--format",
            '{{index .Config.Labels "org.opencontainers.image.revision"}}',
        ])
        if revision != PG16_BASELINE_SHA or previous_revision != PG16_BASELINE_REVISION:
            raise DeploymentError("pg16_bridge_requires_baseline_release_and_schema")
        git = ["git", "-c", f"safe.directory={self.root}"]
        if self.command([*git, "merge-base", PG16_BASELINE_SHA, self.sha]) != PG16_BASELINE_SHA:
            raise DeploymentError("pg16_bridge_requires_baseline_ancestor")
        # The corrected image can audit the old DB only for this same-schema repair.
        # Future releases changing application/schema code must first deploy this repair.
        if self.command([*git, "diff", "--name-only", PG16_BASELINE_SHA, self.sha,
                         "--", *PG16_BRIDGE_UNCHANGED_PATHS]):
            raise DeploymentError("pg16_bridge_requires_unchanged_database_application")
        return self.image

    def toolchain_preflight(self, image: str) -> dict:
        self.env["ASSETCORE_IMAGE"] = image
        try:
            # Send the current standalone read-only guard even to a pre-PROD-03A image.
            # This prevents old backup code without guards from bypassing the contract.
            content = (self.root / "scripts" / "postgres_toolchain.py").read_text("utf-8")
            result = self.dc("run", "--rm", "--no-deps", "--pull", "never", "-T",
                             "app", "python", "-", "--tools", "pg_dump", "pg_restore", "psql",
                             input_text=content)
            return json.loads(result)
        finally:
            self.env["ASSETCORE_IMAGE"] = self.image

    def upgrade(self, backup_directory: Path, actor: int, *,
                pg16_baseline_bridge: bool = False) -> Path:
        self.validate()
        if actor < 1 or not os.environ.get("BACKUP_ENCRYPTION_KEY"):
            raise DeploymentError("active_actor_and_operational_key_required")
        directory = backup_directory.resolve()
        if not directory.is_dir() or not directory.is_absolute() or "," in str(directory):
            raise DeploymentError("existing_operator_backup_directory_required")
        self.stage = "current_state"
        previous_image = self.current_image(running=True)
        self.probe("smoke", running=True)
        previous = self.probe("existing", actor, running=True)
        if self.probe("existing", actor) != previous:
            raise DeploymentError("current_and_target_database_must_match")
        self.stage = "backup_toolchain_preflight"
        backup_image = self.backup_image(
            previous_image, previous["revision"], pg16_baseline_bridge=pg16_baseline_bridge,
        )
        backup_toolchain = self.toolchain_preflight(backup_image)
        if backup_image != self.image:
            self.toolchain_preflight(self.image)
        # Unique directory: the existing backup tool's second-resolution filenames
        # cannot overwrite an earlier backup or be mistaken for this operation.
        destination = Path(tempfile.mkdtemp(prefix="upgrade-", dir=directory))
        destination.chmod(0o770)  # Linux: operator must share the UID/GID 10001 directory.
        record = {"release_sha": self.sha, "image_id": self.image,
                  "previous_image_id": previous_image, "previous_revision": previous["revision"],
                  "backup_image_id": backup_image, "backup_toolchain": backup_toolchain,
                  "backup_mode": "pg16_baseline_bridge" if pg16_baseline_bridge else "previous_image",
                  "created_at": datetime.now(UTC).isoformat(), "project": self.project,
                  "fully_commissioned": False}

        def save(status: str) -> None:
            record["status"] = status
            record["stage"] = self.stage
            (destination / "release.json").write_text(json.dumps(record, indent=2), "utf-8")

        save("started")
        try:
            self.stage = "stop_writers"
            self.dc("stop", "app")
            self.env["ASSETCORE_IMAGE"] = backup_image
            self.stage = "stopped_state_validation"
            if self.probe("existing", actor) != previous:
                raise DeploymentError("database_changed_before_backup")
            self.stage = "backup"
            self.dc("run", "--rm", "--no-deps", "--pull", "never", "-T",
                    "-e", "BACKUP_ENCRYPTION_KEY", "-v", f"{destination}:/backups:rw",
                    "app", "python", "scripts/backup_database.py", "--output-dir", "/backups",
                    "--actor-user-id", str(actor), backup_secret=True)
            backups = list(destination.glob("*.acbackup"))
            if len(backups) != 1 or backups[0].is_symlink() or not backups[0].is_file():
                raise DeploymentError("exactly_one_new_backup_required")
            backup = backups[0]
            digest = file_sha256(backup)
            self.stage = "verify"
            # Always use the corrected target verifier: crypto/checksum success alone
            # does not qualify a PG17-produced archive for recovery to PostgreSQL 16.
            self.env["ASSETCORE_IMAGE"] = self.image
            self.dc("run", "--rm", "--no-deps", "--pull", "never", "-T",
                    "-e", "BACKUP_ENCRYPTION_KEY", "-v", f"{destination}:/backups:ro",
                    "app", "python", "scripts/verify_backup.py", f"/backups/{backup.name}",
                    "--require-postgres-compatible",
                    backup_secret=True)
            if file_sha256(backup) != digest:
                raise DeploymentError("backup_changed_during_verification")
            record.update(backup_file=backup.name, encrypted_sha256=digest)
            save("backup_verified")
            self.env["ASSETCORE_IMAGE"] = self.image
            release_source(self.root, self.sha)
            self.prepare()
            self.start()
            save("runtime_ready")
            return destination
        except (Exception, KeyboardInterrupt):
            # Never auto-start the old image against a possibly partially migrated DB.
            save("failed_operator_recovery_required")
            raise
        finally:
            self.env["ASSETCORE_IMAGE"] = self.image


def main() -> int:
    parser = argparse.ArgumentParser(description="Explicit AssetCore production operations")
    parser.add_argument("operation", choices=["build", "init", "start", "upgrade"])
    parser.add_argument("--sha", required=True)
    parser.add_argument("--env-file", type=Path, default=ROOT / ".env")
    parser.add_argument("--project", default="assetcore")
    parser.add_argument("--backup-dir", type=Path)
    parser.add_argument("--actor-user-id", type=int)
    parser.add_argument("--confirm-empty", action="store_true")
    parser.add_argument("--pg16-baseline-bridge", action="store_true",
                        help="Use the corrected image for the exact PROD-03A baseline repair only")
    args = parser.parse_args()
    deployment = None
    try:
        deployment = Deployment(ROOT, args.sha, args.env_file, args.project)
        with operation_lock(ROOT, args.project):
            if args.operation == "build":
                image = deployment.build()
                print(json.dumps({"release_sha": args.sha, "image_id": image}))
            elif args.operation == "init":
                if not args.confirm_empty:
                    raise DeploymentError("explicit_empty_database_confirmation_required")
                deployment.initialize()
            elif args.operation == "start":
                deployment.restart()
            elif args.operation == "upgrade":
                if not args.backup_dir or not args.actor_user_id:
                    raise DeploymentError("backup_directory_and_actor_required")
                deployment.upgrade(args.backup_dir, args.actor_user_id,
                                   pg16_baseline_bridge=args.pg16_baseline_bridge)
        print("production_operation_complete; licence_commissioning_requires_operator_verification")
        return 0
    except (Exception, KeyboardInterrupt):
        # No raw subprocess, configuration, paths or credentials in console.
        print(f"production_operation_failed; stage={deployment.stage if deployment else 'arguments'}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
