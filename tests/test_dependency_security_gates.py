from __future__ import annotations

import os
import subprocess
import sys
from datetime import date
from pathlib import Path

import pytest
import yaml

from scripts.audit_dependencies import (
    AuditFailure,
    apply_policy,
    frontend_findings,
    python_findings,
)
from scripts.dependency_inventory import canonical_json, collect_inventory


def _finding(severity="HIGH", version="1.0"):
    return {
        "ecosystem": "python",
        "package": "test-package",
        "version": version,
        "advisory": "GHSA-0000-0000-0000",
        "severity": severity,
        "fix_versions": [],
    }


@pytest.mark.parametrize("severity", ["HIGH", "CRITICAL", "UNKNOWN", "UNRECOGNIZED"])
def test_audit_fails_for_high_critical_or_unknown_even_without_a_patch(severity):
    result = apply_policy([_finding(severity)], {"format": 1, "exceptions": []})
    assert result["valid"] is False
    assert len(result["blocking"]) == 1


def test_lower_severity_is_reported_not_silently_removed():
    findings = [_finding("LOW"), _finding("MODERATE")]
    result = apply_policy(findings, {"format": 1, "exceptions": []})
    assert result["valid"] is True
    assert result["informational"] == findings


def test_exceptions_are_exact_version_scoped_and_expire():
    exception = {
        **_finding(),
        "reason": "Test-only reviewed mitigation",
        "tracking_url": "https://github.com/example/project/issues/1",
        "expires": "2030-02-01",
    }
    policy = {"format": 1, "exceptions": [exception]}
    report = apply_policy([_finding()], policy, today=date(2030, 1, 1))
    assert report["valid"] is True
    assert len(report["accepted_exceptions"]) == 1
    assert apply_policy([_finding(version="1.1")], policy, today=date(2030, 1, 1))["valid"] is False
    with pytest.raises(AuditFailure, match="invalid_or_expired"):
        apply_policy([_finding()], policy, today=date(2030, 2, 1))


def test_python_audit_deduplicates_aliases_and_looks_up_severity():
    vulnerability = {
        "id": "PYSEC-2000-1",
        "aliases": ["GHSA-0000-0000-0000"],
        "fix_versions": ["2.0"],
    }
    report = {
        "dependencies": [
            {"name": "test-package", "version": "1.0", "vulns": [vulnerability, vulnerability]}
        ]
    }
    looked_up = []

    def lookup(identifier):
        looked_up.append(identifier)
        return "HIGH"

    findings, count = python_findings(report, lookup)
    assert count == 1
    assert len(findings) == 1
    assert findings[0]["severity"] == "HIGH"
    assert looked_up == ["GHSA-0000-0000-0000"]


@pytest.mark.parametrize(
    "report", [{}, {"dependencies": []}, {"dependencies": [{"skip_reason": "unavailable"}]}]
)
def test_incomplete_python_audit_is_not_a_pass(report):
    with pytest.raises(AuditFailure):
        python_findings(report)


def test_registry_error_and_missing_frontend_metadata_cannot_pass():
    for report in ({"error": "registry unavailable"}, {"advisories": {}}):
        with pytest.raises(AuditFailure):
            frontend_findings(report)
    findings, count = frontend_findings(
        {"advisories": {}, "metadata": {"vulnerabilities": {}, "totalDependencies": 10}}
    )
    assert findings == []
    assert count == 10


def test_frontend_advisory_without_affected_versions_cannot_be_silently_lost():
    with pytest.raises(AuditFailure, match="advisories_missing"):
        frontend_findings({"advisories": {}, "metadata": {"vulnerabilities": {"high": 1}}})
    with pytest.raises(AuditFailure, match="versions_missing"):
        frontend_findings(
            {"advisories": {"1": {"findings": []}}, "metadata": {"vulnerabilities": {"high": 1}}}
        )


def test_dependency_inventory_and_cyclonedx_are_reproducible_and_path_free():
    inventory, sbom = collect_inventory()
    second_inventory, second_sbom = collect_inventory()
    assert canonical_json(inventory) == canonical_json(second_inventory)
    assert canonical_json(sbom) == canonical_json(second_sbom)
    assert sbom["bomFormat"] == "CycloneDX"
    assert sbom["specVersion"] == "1.6"
    assert len(sbom["components"]) == len(inventory["python"]) + len(inventory["frontend"])
    assert all(item["purl"] == item["bom-ref"] for item in sbom["components"])
    assert b"site-packages" not in canonical_json(sbom)
    assert b"C:/Users" not in canonical_json(inventory)
    assert b"password" not in canonical_json(sbom).lower()


def test_ci_actions_are_immutable_and_all_existing_security_gates_remain_explicit():
    import re

    root = Path(__file__).resolve().parents[1]
    workflow = yaml.safe_load((root / ".github/workflows/check.yml").read_text(encoding="utf-8"))
    assert workflow["permissions"] == {"contents": "read"}
    assert set(workflow["jobs"]) == {"frontend", "backend", "postgres", "docker"}
    for job in workflow["jobs"].values():
        assert 0 < job["timeout-minutes"] <= 30
        for step in job["steps"]:
            if "uses" in step:
                assert re.fullmatch(r"actions/[a-z-]+@[0-9a-f]{40}", step["uses"])
    backend = "\n".join(step.get("run", "") for step in workflow["jobs"]["backend"]["steps"])
    for gate in (
        "ruff check",
        "validate_migration_history.py",
        "validate_authorization_inventory.py",
        "catalog_v2_validation.py",
        "build_catalog_translations.py --check",
        "test_runtime_deployment_hardening.py",
        "verify_release.py",
        "audit_dependencies.py python",
    ):
        assert gate in backend
    assert "--select E9" not in backend
    postgres = workflow["jobs"]["postgres"]
    assert postgres["env"]["ASSETCORE_REQUIRE_POSTGRES_TESTS"] == "true"
    assert any("pytest -q tests/postgres" in step.get("run", "") for step in postgres["steps"])


def test_ci_translation_command_runs_without_an_inherited_pythonpath():
    root = Path(__file__).resolve().parents[1]
    workflow = yaml.safe_load((root / ".github/workflows/check.yml").read_text(encoding="utf-8"))
    step = next(
        item
        for item in workflow["jobs"]["backend"]["steps"]
        if item.get("name") == "Catalog EN/BG translation gate"
    )
    environment = {key: value for key, value in os.environ.items() if key != "PYTHONPATH"}
    environment.update(step.get("env", {}))
    result = subprocess.run(
        [sys.executable, "backend/scripts/build_catalog_translations.py", "--check"],
        cwd=root,
        env=environment,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, "Translation gate must run in a clean CI environment."
