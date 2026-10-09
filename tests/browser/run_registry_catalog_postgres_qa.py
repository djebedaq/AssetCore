"""Dedicated disposable PostgreSQL; credentials never leave child process memory."""

import os
import secrets
import socket
import subprocess
import sys
import time
from pathlib import Path
from uuid import uuid4


def main():
    root = Path(__file__).resolve().parents[2]
    output = root / ".tmp" / "registry02-postgres"
    output.mkdir(exist_ok=True)
    name = "assetcore-registry02-qa-" + uuid4().hex[:12]
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    env["POSTGRES_PASSWORD"] = secrets.token_urlsafe(32)
    env["POSTGRES_USER"] = "assetcore_qa"
    env["POSTGRES_DB"] = "assetcore_test_concurrency"
    env["ASSETCORE_POSTGRES_CONCURRENCY_URL"] = f"postgresql+psycopg://assetcore_qa:{env['POSTGRES_PASSWORD']}@127.0.0.1:{port}/assetcore_test_concurrency"
    env["ASSETCORE_REQUIRE_POSTGRES_TESTS"] = "true"
    try:
        subprocess.run(["docker", "run", "--detach", "--name", name,
            "--publish", f"127.0.0.1:{port}:5432", "--env", "POSTGRES_PASSWORD", "--env", "POSTGRES_USER",
            "--env", "POSTGRES_DB", "postgres:16-alpine"], env=env, check=True, capture_output=True)
        for _ in range(60):
            # The image's temporary init server accepts Unix-socket connections
            # before it restarts. TCP becomes ready only on the final server.
            if subprocess.run(["docker", "exec", name, "pg_isready", "-h", "127.0.0.1",
                    "-U", "assetcore_qa", "-d", "assetcore_test_concurrency"], capture_output=True).returncode == 0:
                break
            time.sleep(1)
        else:
            raise RuntimeError("QA PostgreSQL readiness failed")
        with (output / "pytest.log").open("w", encoding="utf-8") as log:
            result = subprocess.run([sys.executable, "-m", "pytest", "-q", *(sys.argv[1:] or ["tests/postgres"]), "--tb=short",
                "--durations=10", "--junitxml=.tmp/registry02-postgres/results.xml"], cwd=root, env=env, stdout=log, stderr=subprocess.STDOUT)
        print("Dedicated PostgreSQL suite exit code:", result.returncode)
        return result.returncode
    finally:
        # Only the random container created above; no existing Docker resources.
        subprocess.run(["docker", "rm", "--force", "--volumes", name], capture_output=True, check=False)


if __name__ == "__main__":
    raise SystemExit(main())
