"""Read-only Windows/Linux host inventory. No installation, binding or configuration."""

from __future__ import annotations

import argparse
import ctypes
import json
import os
import platform
import shutil
import socket
import subprocess
from datetime import UTC, datetime
from pathlib import Path


def query(command: list[str]) -> str | None:
    try:
        result = subprocess.run(command, text=True, capture_output=True, timeout=15, check=False)
        return result.stdout.strip() if result.returncode == 0 else None
    except (OSError, subprocess.SubprocessError):
        return None


def ram_bytes() -> int | None:
    try:
        if os.name == "nt":
            class MemoryStatus(ctypes.Structure):
                _fields_ = [("length", ctypes.c_ulong), ("load", ctypes.c_ulong)] + [
                    (name, ctypes.c_ulonglong) for name in
                    ("total", "available", "page_total", "page_available",
                     "virtual_total", "virtual_available", "extended")
                ]
            status = MemoryStatus()
            status.length = ctypes.sizeof(status)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
                return status.total
            return None
        return os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES")
    except (AttributeError, OSError, ValueError):
        return None


def report(directory: Path, port: int = 10000) -> dict:
    directory = directory.resolve()
    now = datetime.now(UTC)
    docker = shutil.which("docker")
    compose = query([docker, "compose", "version", "--short"]) if docker else None
    engine = query([docker, "info", "--format",
                    '{{json .ServerVersion}}|{{json .Architecture}}|{{json .MemTotal}}']) if docker else None
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as connection:
        connection.settimeout(1)
        occupied = connection.connect_ex(("127.0.0.1", port)) == 0
    git = ["git", "-C", str(directory), "-c", f"safe.directory={directory}"]
    head = query([*git, "rev-parse", "HEAD"])
    changes = query([*git, "status", "--porcelain", "--untracked-files=all"])
    result = {
        "os": platform.system(), "os_release": platform.release(),
        "architecture": platform.machine(), "logical_cpu_count": os.cpu_count(),
        "ram_bytes": ram_bytes(), "free_disk_bytes": shutil.disk_usage(directory).free,
        "docker_cli_available": bool(docker), "compose_version": compose,
        "daemon_reachable": engine is not None, "engine_version_architecture_ram": engine,
        "loopback_port": port, "loopback_port_in_use": occupied,
        "utc_now": now.isoformat(), "date_plausible": 2026 <= now.year <= 2100,
        "clock_sync_verified": False, "git_sha": head,
        "git_clean": not changes if changes is not None else None,
    }
    if os.name == "nt":
        result["wsl_status_command_succeeded"] = query(["wsl", "--status"]) is not None
        result["virtualization_firmware_enabled"] = query([
            "powershell", "-NoProfile", "-NonInteractive", "-Command",
            "Get-CimInstance Win32_Processor | Select-Object -ExpandProperty VirtualizationFirmwareEnabled",
        ])
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--directory", type=Path, default=Path.cwd())
    parser.add_argument("--port", type=int, default=10000)
    args = parser.parse_args()
    if not 1 <= args.port <= 65535 or not args.directory.is_dir():
        parser.error("existing directory and valid port required")
    print(json.dumps(report(args.directory, args.port), indent=2))


if __name__ == "__main__":
    main()
