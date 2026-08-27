"""Fail-closed, high/critical dependency audit of the actual CI dependency set.

Auditors never run in fix mode. Only normalized package/advisory metadata is
printed or archived; subprocess diagnostics may contain index credentials and
are deliberately not echoed. Advisory feeds are live, not frozen security data.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
IDENTIFIER = re.compile(r"^[A-Za-z0-9_.@/+\-]+$")


class AuditFailure(RuntimeError):
    """Safe, fixed error code; never include subprocess or connection details."""


def _run_json(command: list[str], *, cwd: Path = ROOT) -> dict:
    try:
        result = subprocess.run(
            command,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=240,
        )
        if result.returncode not in {0, 1}:
            raise AuditFailure("auditor_execution_failed")
        report = json.loads(result.stdout)
        if not isinstance(report, dict) or report.get("error"):
            raise AuditFailure("auditor_report_invalid")
        return report
    except (OSError, subprocess.TimeoutExpired, ValueError):
        raise AuditFailure("auditor_execution_or_report_failed") from None


def _safe_identifier(value: object) -> str:
    if not isinstance(value, str) or not IDENTIFIER.fullmatch(value):
        raise AuditFailure("invalid_package_or_advisory_identifier")
    return value


def osv_severity(advisory_id: str) -> str:
    """GHSA/PYSEC severity from the public OSV record; unknown is blocking."""
    identifier = _safe_identifier(advisory_id)
    try:
        request = urllib.request.Request(
            f"https://api.osv.dev/v1/vulns/{identifier}",
            headers={"User-Agent": "AssetCore-dependency-audit/1"},
        )
        with urllib.request.urlopen(request, timeout=20) as response:
            report = json.load(response)
        severity = str(report.get("database_specific", {}).get("severity", "UNKNOWN")).upper()
        return "MODERATE" if severity == "MEDIUM" else severity
    except Exception:
        raise AuditFailure("advisory_severity_lookup_failed") from None


def python_findings(report: dict, severity_lookup=osv_severity) -> tuple[list[dict], int]:
    dependencies = report.get("dependencies")
    if not isinstance(dependencies, list) or not dependencies:
        raise AuditFailure("python_dependency_inventory_missing")
    findings: dict[tuple[str, str, str], dict] = {}
    for dependency in dependencies:
        if dependency.get("skip_reason") or not isinstance(dependency.get("vulns"), list):
            raise AuditFailure("python_dependency_not_audited")
        name = _safe_identifier(dependency["name"])
        version = _safe_identifier(dependency["version"])
        for vulnerability in dependency["vulns"]:
            aliases = sorted(set(vulnerability.get("aliases", [])))
            advisory_id = next(
                (value for value in [vulnerability["id"], *aliases] if value.startswith("GHSA-")),
                vulnerability["id"],
            )
            advisory_id = _safe_identifier(advisory_id)
            findings[(name, version, advisory_id)] = {
                "ecosystem": "python",
                "package": name,
                "version": version,
                "advisory": advisory_id,
                "fix_versions": sorted(
                    _safe_identifier(v) for v in vulnerability.get("fix_versions", [])
                ),
            }
    identifiers = sorted({item["advisory"] for item in findings.values()})
    with ThreadPoolExecutor(max_workers=8) as executor:
        severities = dict(zip(identifiers, executor.map(severity_lookup, identifiers), strict=True))
    for item in findings.values():
        item["severity"] = severities[item["advisory"]]
    return sorted(findings.values(), key=lambda item: (item["package"], item["advisory"])), len(
        dependencies
    )


def frontend_findings(report: dict) -> tuple[list[dict], int]:
    advisories = report.get("advisories")
    metadata = report.get("metadata", {})
    if not isinstance(advisories, dict) or not isinstance(metadata.get("vulnerabilities"), dict):
        raise AuditFailure("frontend_audit_report_invalid")
    reported_count = sum(metadata["vulnerabilities"].values())
    if reported_count and not advisories:
        raise AuditFailure("frontend_advisories_missing")
    findings = []
    for advisory in advisories.values():
        if not advisory.get("findings"):
            raise AuditFailure("frontend_advisory_versions_missing")
        for version in sorted({item["version"] for item in advisory["findings"]}):
            findings.append(
                {
                    "ecosystem": "frontend",
                    "package": _safe_identifier(advisory["module_name"]),
                    "version": _safe_identifier(version),
                    "advisory": _safe_identifier(advisory["github_advisory_id"]),
                    "severity": str(advisory["severity"]).upper(),
                    "patched_versions": advisory.get("patched_versions", ""),
                }
            )
    total = metadata.get("totalDependencies")
    if not isinstance(total, int) or total < 1:
        raise AuditFailure("frontend_dependency_inventory_missing")
    return sorted(findings, key=lambda item: (item["package"], item["advisory"])), total


def apply_policy(findings: list[dict], policy: dict, *, today: date | None = None) -> dict:
    today = today or date.today()
    if policy.get("format") != 1 or not isinstance(policy.get("exceptions"), list):
        raise AuditFailure("audit_exception_policy_invalid")
    exceptions = {}
    for exception in policy["exceptions"]:
        try:
            key = tuple(
                exception[field] for field in ("ecosystem", "package", "version", "advisory")
            )
            expires = date.fromisoformat(exception["expires"])
            if (
                expires <= today
                or not exception["reason"].strip()
                or not exception["tracking_url"].startswith("https://github.com/")
            ):
                raise ValueError
            if key in exceptions:
                raise ValueError
            exceptions[key] = exception
        except (KeyError, TypeError, ValueError):
            raise AuditFailure("audit_exception_invalid_or_expired") from None
    blocking = []
    accepted = []
    informational = []
    for item in findings:
        key = tuple(item[field] for field in ("ecosystem", "package", "version", "advisory"))
        if item["severity"] in {"LOW", "MODERATE"}:
            informational.append(item)
        elif key in exceptions:
            accepted.append({**item, "exception_expires": exceptions[key]["expires"]})
        else:
            blocking.append(item)
    return {
        "valid": not blocking,
        "policy": "block_high_critical_and_unknown; exact_expiring_exceptions_only",
        "blocking": blocking,
        "accepted_exceptions": accepted,
        "informational": informational,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("ecosystem", choices=("python", "frontend"))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.ecosystem == "python":
            raw = _run_json(
                [
                    sys.executable,
                    "-m",
                    "pip_audit",
                    "--local",
                    "--strict",
                    "--format",
                    "json",
                    "--progress-spinner",
                    "off",
                    "--desc",
                    "off",
                ]
            )
            findings, count = python_findings(raw)
        else:
            pnpm = shutil.which("pnpm")
            if pnpm is None:
                raise AuditFailure("pnpm_not_available")
            raw = _run_json(
                [pnpm, "audit", "--json", "--registry=https://registry.npmjs.org"],
                cwd=ROOT / "frontend",
            )
            findings, count = frontend_findings(raw)
        policy = json.loads(
            (ROOT / "security/dependency-audit-exceptions.json").read_text(encoding="utf-8")
        )
        result = {
            "ecosystem": args.ecosystem,
            "audited_dependency_count": count,
            **apply_policy(findings, policy),
        }
    except Exception as exc:
        code = str(exc) if isinstance(exc, AuditFailure) else "audit_failed_safely"
        result = {"valid": False, "error": code}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
