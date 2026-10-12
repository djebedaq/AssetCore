"""The configured capacity is shared by independent web processes, not threads only."""

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest
from app.catalog_admin.parts_extraction import capacity
from fastapi import HTTPException

PROGRAM = """
import json, sys, tempfile, time
from pathlib import Path
tempfile.tempdir = sys.argv[1]
from app.catalog_admin.parts_extraction import process
from app.settings import settings
settings.catalog_extraction_max_processes = 2
marker = Path(sys.argv[2])
def work(*args):
    marker.write_text('entered')
    if sys.argv[3] == 'hold':
        while not marker.with_suffix('.release').exists():
            time.sleep(.02)
    return {'result': 'accepted'}
process._extract = work
try:
    print(json.dumps(process.extract(b'QA synthetic', 'page', 1, {'timeout': 2})), flush=True)
except Exception as error:
    print(json.dumps({'error': getattr(error, 'detail', {}).get('code')}), flush=True)
"""


def test_capacity_across_web_processes_and_abandoned_slot(tmp_path):
    environment = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[1] / "backend"))
    holders = []
    try:
        for index in range(2):
            marker = tmp_path / f"holder-{index}"
            holder = subprocess.Popen([sys.executable, "-c", PROGRAM, str(tmp_path), str(marker), "hold"],
                env=environment, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            holders.append(holder)
            deadline = time.monotonic() + 15
            while not marker.exists() and holder.poll() is None and time.monotonic() < deadline:
                time.sleep(.02)
            assert marker.exists(), "QA holder must enter its extraction slot"
        result = subprocess.run([sys.executable, "-c", PROGRAM, str(tmp_path), str(tmp_path / "third"), "check"],
            env=environment, capture_output=True, text=True, timeout=15, check=True)
        assert json.loads(result.stdout) == {"error": "catalog_extraction_busy"}
        assert not (tmp_path / "third").exists(), "Capacity rejection must happen before PDF parsing"
        # An abruptly terminated web process cannot strand the global capacity.
        holders[0].kill()
        holders[0].wait(timeout=5)
        recovered = subprocess.run([sys.executable, "-c", PROGRAM, str(tmp_path), str(tmp_path / "recovered"), "check"],
            env=environment, capture_output=True, text=True, timeout=15, check=True)
        assert json.loads(recovered.stdout) == {"result": "accepted"}
    finally:
        for index, holder in enumerate(holders):
            (tmp_path / f"holder-{index}.release").touch()
            try:
                holder.communicate(timeout=5)
            except subprocess.TimeoutExpired:
                holder.kill()
                holder.communicate(timeout=5)


def test_capacity_released_after_exception_and_busy_rejection(tmp_path, monkeypatch):
    monkeypatch.setattr(capacity, "gettempdir", lambda: str(tmp_path))
    with capacity.slot(1):
        with pytest.raises(HTTPException) as rejected:
            with capacity.slot(1):
                pytest.fail("A busy slot cannot enter extraction")
        assert rejected.value.detail["code"] == "catalog_extraction_busy"
    with pytest.raises(ValueError, match="QA interruption"):
        with capacity.slot(1):
            raise ValueError("QA interruption")
    with capacity.slot(1):
        assert list((tmp_path / "assetcore-parser-slots").iterdir())


@pytest.mark.skipif(os.name == "nt", reason="POSIX no-follow and private permissions")
@pytest.mark.parametrize("unsafe", ["directory_permissions", "file_permissions", "symlink", "not_regular"])
def test_unsafe_capacity_storage_fails_closed(tmp_path, monkeypatch, unsafe):
    monkeypatch.setattr(capacity, "gettempdir", lambda: str(tmp_path))
    folder = tmp_path / "assetcore-parser-slots"
    folder.mkdir(mode=0o700)
    target = folder / "slot-0"
    if unsafe == "directory_permissions":
        folder.chmod(0o777)
    elif unsafe == "file_permissions":
        target.touch(mode=0o666)
        target.chmod(0o666)
    elif unsafe == "symlink":
        original = tmp_path / "untouched"
        original.write_bytes(b"QA untouched")
        target.symlink_to(original)
    else:
        target.mkdir()
    with pytest.raises(HTTPException) as rejected:
        with capacity.slot(1):
            pytest.fail("Unsafe storage must never grant a slot")
    assert rejected.value.detail["code"] == "catalog_extraction_resource_limit"
    if unsafe == "symlink":
        assert original.read_bytes() == b"QA untouched"


@pytest.mark.skipif(os.name == "nt", reason="Unix inherited file-descriptor lease; Windows kills the Job Object")
def test_worker_retains_slot_after_web_parent_dies(tmp_path, monkeypatch):
    marker = tmp_path / "worker-pid"
    program = """
import subprocess, sys, tempfile
tempfile.tempdir = sys.argv[1]
from app.catalog_admin.parts_extraction import process
from app.settings import settings
settings.catalog_extraction_max_processes = 1
launch = subprocess.Popen
def worker(args, **kwargs):
    code = "import os,time; from pathlib import Path; Path(%r).write_text(str(os.getpid())); time.sleep(120)" % sys.argv[2]
    return launch([sys.executable, '-c', code], **kwargs)
process.subprocess.Popen = worker
process.extract(b'QA synthetic', 'page', 1, {'timeout': 45})
"""
    environment = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[1] / "backend"))
    parent = subprocess.Popen([sys.executable, "-c", program, str(tmp_path), str(marker)],
        env=environment, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    worker_pid = None
    monkeypatch.setattr(capacity, "gettempdir", lambda: str(tmp_path))
    try:
        deadline = time.monotonic() + 15
        while not marker.exists() and parent.poll() is None and time.monotonic() < deadline:
            time.sleep(.02)
        assert marker.exists()
        worker_pid = int(marker.read_text())
        parent.kill()
        parent.wait(timeout=5)
        with pytest.raises(HTTPException) as rejected:
            with capacity.slot(1):
                pytest.fail("The orphan worker still owns its parsing slot")
        assert rejected.value.detail["code"] == "catalog_extraction_busy"
        os.kill(worker_pid, signal.SIGKILL)
        deadline = time.monotonic() + 3
        while True:
            try:
                with capacity.slot(1):
                    break
            except HTTPException:
                assert time.monotonic() < deadline, "Dead workers must release capacity"
                time.sleep(.02)
    finally:
        if parent.poll() is None:
            parent.kill()
        parent.wait(timeout=5)
        if worker_pid:
            try:
                os.kill(worker_pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
