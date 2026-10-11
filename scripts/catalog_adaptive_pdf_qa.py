"""DB-free bounded extraction benchmarks; expected controls are compare-only.

Run extract without making any expected file available to the worker/container.
Run compare afterwards, in a separate process. Reports never contain host paths.
"""

import argparse
import hashlib
import json
import os
import platform
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))


class Monitor:
    def __init__(self):
        self.stop = threading.Event()
        self.peak = self.count = 0
        self.cpu = {}
        self.pids = set()

    def sample(self):
        # Optional psutil on Windows is QA-only; production code has no new dep.
        try:
            import psutil
            tree = [psutil.Process(), *psutil.Process().children(recursive=True)]
            rss = 0
            for process in tree:
                try:
                    rss += process.memory_info().rss
                    times = process.cpu_times()
                    self.cpu[process.pid] = max(self.cpu.get(process.pid, 0), times.user + times.system)
                    self.pids.add(process.pid)
                except psutil.Error:
                    pass
            self.peak, self.count = max(self.peak, rss), max(self.count, len(tree))
            return
        except ImportError:
            pass
        if sys.platform != "linux":
            return
        tree, rss = [os.getpid()], 0
        for pid in tree:
            try:
                base = Path(f"/proc/{pid}")
                tree.extend(child for child in self.children(pid) if child not in tree)
                status = (base / "status").read_text().splitlines()
                rss += next(int(line.split()[1]) * 1024 for line in status if line.startswith("VmRSS:"))
                stat = (base / "stat").read_text().rsplit(")", 1)[1].split()
                cpu = (int(stat[11]) + int(stat[12])) / os.sysconf("SC_CLK_TCK")
                self.cpu[pid] = max(self.cpu.get(pid, 0), cpu)
                self.pids.add(pid)
            except (OSError, StopIteration, ValueError):
                pass
        self.peak, self.count = max(self.peak, rss), max(self.count, len(tree))

    @staticmethod
    def children(pid):
        children = set()
        # Linux attaches children to the spawning thread, not just the main
        # thread. Include ThreadPoolExecutor workers in concurrent QA samples.
        for task in Path(f"/proc/{pid}/task").glob("*"):
            try:
                children.update(int(p) for p in (task / "children").read_text().split())
            except OSError:
                pass
        return children

    def run(self):
        while not self.stop.wait(.02):
            self.sample()

    def remaining(self):
        try:
            import psutil
            return len(psutil.Process().children(recursive=True))
        except ImportError:
            return len(self.children(os.getpid())) if sys.platform == "linux" else None


def runtime():
    import fitz
    from app.catalog_admin.parts_extraction.ocr import language_folder
    from PIL import __version__ as pillow
    result = {"os": platform.system(), "python": platform.python_version(), "pymupdf": fitz.VersionBind, "pillow": pillow}
    try:
        version = subprocess.run(["tesseract", "--version"], capture_output=True, text=True, timeout=5, check=True)
        folder = language_folder()
        result.update({"tesseract": version.stdout.splitlines()[0], "models": {
            path.stem: hashlib.sha256(path.read_bytes()).hexdigest() for path in sorted(folder.glob("*.traineddata"))}})
    except (OSError, subprocess.SubprocessError, RuntimeError):
        result["tesseract"] = "UNAVAILABLE"
    return result


def fingerprints():
    return {path.name: hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()
        for path in sorted((ROOT / "backend/app/catalog_admin/parts_extraction").glob("*.py"))}


def concurrency_report(args):
    from app.catalog_admin.parts_extraction import process
    from app.settings import settings
    if args.pdf.stat().st_size > settings.catalog_pdf_max_bytes:
        raise ValueError("PDF_BYTE_LIMIT")
    content = args.pdf.read_bytes()
    sha = hashlib.sha256(content).hexdigest()
    config = {**process.configuration(settings), "source_sha256": sha}
    monitor = Monitor()
    monitor.sample()
    initial_cpu = sum(monitor.cpu.values())
    thread = threading.Thread(target=monitor.run, daemon=True)
    started = time.monotonic()
    thread.start()
    try:
        def run_worker(_):
            try:
                return process.extract(content, "page", args.page, config)
            except Exception as exc:
                detail = getattr(exc, "detail", {})
                code = detail.get("code") if isinstance(detail, dict) else None
                allowed = {"catalog_extraction_timeout", "catalog_extraction_resource_limit", "catalog_extraction_busy"}
                return {"error": code if code in allowed else "QA_WORKER_FAILED"}
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(run_worker, range(2)))
    finally:
        monitor.sample()
        monitor.stop.set()
        thread.join(2)
    resources = {"wall_seconds": round(time.monotonic() - started, 4),
        "sampled_cpu_seconds": round(sum(monitor.cpu.values()) - initial_cpu, 4),
        "sampled_peak_tree_rss_mib": round(monitor.peak / 1024**2, 2),
        "peak_process_count_including_controller": monitor.count, "sample_interval_ms": 20,
        "descendants_remaining_after_worker": monitor.remaining(), "queue_wait_seconds": 0,
        "measurement_scope": "AGGREGATE_TWO_CONCURRENT_WORKERS"}
    return {"source_sha256": sha, "runtime": runtime(), "implementation_sha256": fingerprints(),
        "implementation_algorithm": "sha256-normalized-lf", "limits": config,
        "runs": [{"run": 1, "pages": [{"physical_page": args.page, "result": result, "resources": resources} for result in results]}],
        "review_state": "NOT_REVIEWED", "scope": "CONCURRENT_EXTRACTION_ONLY"}


def extract_report(args):
    from app.catalog_admin.parts_extraction import context, process
    from app.settings import settings
    if args.pdf.stat().st_size > settings.catalog_pdf_max_bytes:
        raise ValueError("PDF_BYTE_LIMIT")
    content = args.pdf.read_bytes()
    sha = hashlib.sha256(content).hexdigest()
    pages = [int(n) for n in args.pages.split(",")]
    if not 1 <= len(pages) <= 100 or len(set(pages)) != len(pages) or not 1 <= args.runs <= 5:
        raise ValueError("QA_SELECTION_LIMIT")
    config = {**process.configuration(settings), "source_sha256": sha}
    runs = []
    for number in range(args.runs):
        outputs = []
        for page in pages:
            monitor = Monitor()
            thread = threading.Thread(target=monitor.run, daemon=True)
            monitor.sample()
            initial_cpu = sum(monitor.cpu.values())
            started = time.monotonic()
            thread.start()
            try:
                result = process.extract(content, "page", page, config)
            finally:
                monitor.sample()
                monitor.stop.set()
                thread.join(2)
            outputs.append({"physical_page": page, "result": result, "resources": {
                "wall_seconds": round(time.monotonic() - started, 4),
                "sampled_cpu_seconds": round(sum(monitor.cpu.values()) - initial_cpu, 4),
                "sampled_peak_tree_rss_mib": round(monitor.peak / 1024**2, 2),
                "peak_process_count_including_controller": monitor.count, "sample_interval_ms": 20,
                "descendants_remaining_after_worker": monitor.remaining(), "queue_wait_seconds": 0}})
        profiles = [p for output in outputs for p in context.profiles(output["result"], sha)]
        for output in outputs:
            if output["result"].get("quality", {}).get("needs_context") and profiles:
                output["first_pass"] = output["result"]
                output["result"] = process.extract(content, "page", output["physical_page"], {**config, "context_profiles": profiles[:8]})
        runs.append({"run": number + 1, "pages": outputs})
    return {"source_sha256": sha, "runtime": runtime(), "implementation_sha256": fingerprints(),
        "implementation_algorithm": "sha256-normalized-lf", "limits": config, "runs": runs,
        "review_state": "NOT_REVIEWED", "scope": "EXTRACTION_ONLY_NO_HOTSPOT_OR_PUBLICATION_CLAIM"}


def compare_report(args):
    # This function runs AFTER extraction; no import or call into an extractor.
    report = json.loads(args.report.read_text(encoding="utf-8-sig"))
    expected = json.loads(args.expected.read_text(encoding="utf-8-sig"))
    fields = ("position", "part_number", "description", "quantity")
    runs = []
    success = report["source_sha256"] == expected["pdf_sha256"]
    for run in report["runs"]:
        pages = []
        for output in run["pages"]:
            number, result = output["physical_page"], output["result"]
            wanted = [row for row in expected["parts"] if row["pdf_page"] == number]
            if not wanted:
                raise ValueError("QA_CONTROL_PAGE_MISSING")
            rows = result.get("rows", [])
            exact, counts, mismatches = 0, dict.fromkeys(fields, 0), []
            for index, original in enumerate(wanted):
                actual = rows[index]["payload"] if index < len(rows) else {}
                matches = {field: str(actual.get(field)) == str(original[field]) for field in fields}
                for field, matches_ in matches.items():
                    counts[field] += matches_
                exact += all(matches.values())
                if not all(matches.values()):
                    mismatches.append({"row_index": index, "fields": [key for key, value in matches.items() if not value]})
            provenance = all(row.get("provenance", {}).get("sha256") == expected["pdf_sha256"]
                and row["provenance"].get("physical_page") == number for row in rows)
            passed = (exact == len(wanted) == len(rows) and provenance
                and output["resources"].get("descendants_remaining_after_worker", 0) == 0)
            success = success and passed
            pages.append({"physical_page": number, "expected": len(wanted), "extracted": len(rows), "exact_rows": exact,
                "exact_fields": counts, "provenance": provenance, "passed": passed, "mismatches": mismatches,
                "resources": output["resources"], "quality": result.get("quality")})
        runs.append({"run": run["run"], "pages": pages})
    return {"passed": success, "source_sha256": report["source_sha256"],
        "control_sha256": hashlib.sha256(args.expected.read_bytes()).hexdigest(),
        "control_usage": "SEPARATE_POST_EXTRACTION_COMPARISON_ONLY", "runtime": report["runtime"],
        "implementation_sha256": report.get("implementation_sha256"),
        "implementation_algorithm": report.get("implementation_algorithm"), "runs": runs}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_subparsers(dest="mode", required=True)
    extract = modes.add_parser("extract")
    extract.add_argument("pdf", type=Path)
    extract.add_argument("--pages", required=True)
    extract.add_argument("--runs", type=int, default=3)
    concurrent = modes.add_parser("concurrency")
    concurrent.add_argument("pdf", type=Path)
    concurrent.add_argument("--page", type=int, required=True)
    compare = modes.add_parser("compare")
    compare.add_argument("report", type=Path)
    compare.add_argument("expected", type=Path)
    for command in (extract, compare, concurrent):
        command.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = {"extract": extract_report, "compare": compare_report, "concurrency": concurrency_report}[args.mode](args)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"mode": args.mode, "passed": result.get("passed"), "runs": len(result["runs"])}))
    return 0 if result.get("passed", True) else 1


if __name__ == "__main__":
    raise SystemExit(main())
