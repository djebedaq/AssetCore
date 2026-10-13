"""Linux-only bounded D13 parser contention/crash QA; output contains private OEM rows.

Run in an isolated non-root, network-none container, 2 CPUs / 1 GiB / 64 PIDs.
No expected controls are read. Compare the saved report afterwards.
"""

import argparse
import hashlib
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from tempfile import TemporaryDirectory

from catalog_adaptive_pdf_qa import Monitor, fingerprints, runtime


def wait_for(predicate, children, seconds=15):
    deadline = time.monotonic() + seconds
    while not predicate():
        if time.monotonic() >= deadline or any(child.poll() is not None for child in children):
            raise RuntimeError("QA_LIVE_WORKER_NOT_AVAILABLE")
        time.sleep(.02)


def child(args):
    from app.catalog_admin.parts_extraction import process
    from app.settings import settings
    settings.catalog_extraction_max_processes = 1 if args.mode in {"crash", "recover"} else 2
    original = process._extract
    if args.mode == "hold":
        def gated(*values):
            args.marker.write_text("ready")
            wait_for(lambda: args.release.exists(), [])
            return original(*values)
        process._extract = gated
    if args.mode == "crash":
        launch = subprocess.Popen
        def recorded(*values, **options):
            worker = launch(*values, **options)
            args.marker.write_text(str(worker.pid))
            return worker
        process.subprocess.Popen = recorded
    content = args.pdf.read_bytes()
    digest = hashlib.sha256(content).hexdigest()
    config = {**process.configuration(settings), "source_sha256": digest}
    started = time.monotonic()
    try:
        result = process.extract(content, "page", 15 if args.mode == "recover" else 13, config)
    except Exception as error:
        code = getattr(error, "detail", {}).get("code") if isinstance(getattr(error, "detail", None), dict) else None
        allowed = {"catalog_extraction_busy", "catalog_extraction_resource_limit", "catalog_extraction_timeout"}
        result = {"error": code if code in allowed else "QA_UNEXPECTED_FAILURE"}
    args.output.write_text(json.dumps({"result": result, "call_wall_seconds": time.monotonic() - started}), encoding="utf-8")


def main(args):
    if sys.platform != "linux":
        raise RuntimeError("QA_REQUIRES_ISOLATED_LINUX_RUNTIME")
    children, outputs = [], []
    with TemporaryDirectory(prefix="assetcore-live-capacity-") as directory:
        folder = Path(directory)
        release = folder / "release"
        def start(mode, index):
            output, marker = folder / f"{index}.json", folder / f"{index}.ready"
            command = [sys.executable, str(Path(__file__).resolve()), str(args.pdf), "--mode", mode,
                "--output", str(output), "--marker", str(marker), "--release", str(release)]
            worker = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            children.append(worker)
            return worker, output, marker
        try:
            first, second = start("hold", 0), start("hold", 1)
            wait_for(lambda: first[2].exists() and second[2].exists(), [first[0], second[0]])
            third = start("busy", 2)
            assert third[0].wait(timeout=15) == 0
            busy = json.loads(third[1].read_text())
            assert busy["result"] == {"error": "catalog_extraction_busy"}
            release.touch()
            for worker, output, _ in (first, second):
                assert worker.wait(timeout=50) == 0
                data = json.loads(output.read_text())
                assert len(data["result"].get("rows", [])) == 20
                outputs.append({"physical_page": 13, "result": data["result"], "resources": {
                    "wall_seconds_including_test_barrier": data["call_wall_seconds"], "descendants_remaining_after_worker": 0}})
            crashed = start("crash", 3)
            wait_for(crashed[2].exists, [crashed[0]])
            worker_pid = int(crashed[2].read_text())
            ocr_children = []
            def has_ocr():
                ocr_children.clear()
                for pid in Monitor.children(worker_pid):
                    try:
                        if Path(f"/proc/{pid}/comm").read_text().strip() == "tesseract":
                            ocr_children.append(pid)
                    except FileNotFoundError:
                        pass  # A bounded OCR batch may finish during sampling.
                return bool(ocr_children)
            wait_for(has_ocr, [crashed[0]])
            # Only kill the exact worker owned by this disposable QA controller.
            parent = Path(f"/proc/{worker_pid}/stat").read_text().rsplit(")", 1)[1].split()[1]
            assert int(parent) == crashed[0].pid
            os.kill(worker_pid, signal.SIGKILL)
            assert crashed[0].wait(timeout=15) == 0
            failure = json.loads(crashed[1].read_text())
            assert failure["result"] == {"error": "catalog_extraction_resource_limit"}
            wait_for(lambda: all(not Path(f"/proc/{pid}").exists() for pid in [worker_pid, *ocr_children]), [])
            recovery = start("recover", 4)
            assert recovery[0].wait(timeout=50) == 0
            data = json.loads(recovery[1].read_text())
            assert len(data["result"].get("rows", [])) == 10
            outputs.append({"physical_page": 15, "result": data["result"], "resources": {
                "wall_seconds": data["call_wall_seconds"], "descendants_remaining_after_worker": 0}})
            report = {"source_sha256": hashlib.sha256(args.pdf.read_bytes()).hexdigest(), "runtime": runtime(),
                "implementation_sha256": fingerprints(), "runs": [{"run": 1, "pages": outputs}],
                "live_capacity": {"independent_controllers": 3, "admitted": 2, "busy": 1,
                    "busy_call_seconds": busy["call_wall_seconds"], "killed_real_worker_with_active_tesseract": True,
                    "controlled_crash_failure": True, "ocr_orphans_after_crash": 0, "same_slot_native_recovery": True},
                "review_state": "NOT_REVIEWED"}
            args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
            print(json.dumps(report["live_capacity"]))
        finally:
            for worker in children:
                if worker.poll() is None:
                    worker.kill()
                worker.wait(timeout=5)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pdf", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--mode", choices=("hold", "busy", "crash", "recover"))
    parser.add_argument("--marker", type=Path)
    parser.add_argument("--release", type=Path)
    arguments = parser.parse_args()
    if arguments.mode:
        child(arguments)
    else:
        main(arguments)
