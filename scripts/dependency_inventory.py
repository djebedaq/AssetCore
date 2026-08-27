"""Reproducible release inventory and CycloneDX 1.6, without machine paths/secrets.

Scope: the installed Python environment and every resolved pnpm package (also
optional/platform packages). OS packages/container layers require image scanning
and are not claimed to be covered by this inventory.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import importlib.metadata
import json
import re
from pathlib import Path
from urllib.parse import quote

import yaml
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

ROOT = Path(__file__).resolve().parents[1]
MANIFESTS = (
    "backend/requirements.txt",
    "backend/requirements-dev.txt",
    "backend/requirements-ci.txt",
    "frontend/package.json",
    "frontend/pnpm-lock.yaml",
)


def canonical_json(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode()


def python_pins(root: Path) -> dict[str, str]:
    pins = {}
    for filename in MANIFESTS[:3]:
        for line in (root / filename).read_text(encoding="utf-8").splitlines():
            if not line.strip() or line.startswith(("#", "-r ")):
                continue
            requirement = Requirement(line)
            specifiers = list(requirement.specifier)
            if requirement.url or len(specifiers) != 1 or specifiers[0].operator != "==":
                raise ValueError("Python direct dependencies must use exact version pins.")
            name = canonicalize_name(requirement.name)
            version = specifiers[0].version
            if name in pins and pins[name] != version:
                raise ValueError("Inconsistent Python direct dependency pins.")
            pins[name] = version
    return pins


def collect_inventory(root: Path = ROOT) -> tuple[dict, dict]:
    package = json.loads((root / "frontend/package.json").read_text(encoding="utf-8"))
    lock = yaml.safe_load((root / "frontend/pnpm-lock.yaml").read_text(encoding="utf-8"))
    if str(lock.get("lockfileVersion")) != "9.0":
        raise ValueError("Unexpected pnpm lockfile format; review the inventory parser.")
    importer = lock["importers"]["."]
    for section in ("dependencies", "devDependencies"):
        if set(importer[section]) != set(package[section]):
            raise ValueError("Frontend dependency manifest and lockfile differ.")
        for name, specifier in package[section].items():
            if importer[section][name]["specifier"] != specifier:
                raise ValueError("Frontend lockfile has an outdated direct specifier.")

    installed = sorted(
        {
            (canonicalize_name(item.metadata["Name"]), item.version)
            for item in importlib.metadata.distributions()
        }
    )
    installed_by_name = dict(installed)
    for name, expected in python_pins(root).items():
        if installed_by_name.get(name) != expected:
            raise ValueError("The installed Python set does not match the direct CI pins.")

    components = []
    for name, version in installed:
        purl = f"pkg:pypi/{quote(name, safe='')}@{quote(version, safe='')}"
        components.append(
            {"type": "library", "bom-ref": purl, "name": name, "version": version, "purl": purl}
        )
    frontend = []
    for identifier, details in sorted(lock["packages"].items()):
        name, version = identifier.rsplit("@", 1)
        integrity = details.get("resolution", {}).get("integrity", "")
        if not re.fullmatch(r"sha512-[A-Za-z0-9+/]+={0,2}", integrity):
            raise ValueError("Every resolved pnpm package must have a SHA-512 integrity value.")
        digest = base64.b64decode(integrity.removeprefix("sha512-"), validate=True)
        if len(digest) != 64:
            raise ValueError("Invalid pnpm SHA-512 integrity value.")
        purl = f"pkg:npm/{quote(name, safe='/')}@{quote(version, safe='')}"
        components.append(
            {
                "type": "library",
                "bom-ref": purl,
                "name": name,
                "version": version,
                "purl": purl,
                "hashes": [{"alg": "SHA-512", "content": digest.hex()}],
            }
        )
        frontend.append({"name": name, "version": version, "integrity": integrity})
    manifests = {
        path: hashlib.sha256((root / path).read_bytes().replace(b"\r\n", b"\n")).hexdigest()
        for path in MANIFESTS
    }
    inventory = {
        "format": 1,
        "scope": "installed-python-and-pnpm-lock; excludes OS/image packages",
        "manifest_sha256_normalized_lf": manifests,
        "python": [{"name": name, "version": version} for name, version in installed],
        "frontend": frontend,
        "package_manager": package["packageManager"],
    }
    inventory["inventory_sha256"] = hashlib.sha256(canonical_json(inventory)).hexdigest()
    sbom = {
        "bomFormat": "CycloneDX",
        "specVersion": "1.6",
        "version": 1,
        "metadata": {
            "component": {
                "type": "application",
                "name": "AssetCore",
                "version": package["version"],
            },
            "properties": [
                {"name": "assetcore:inventory-sha256", "value": inventory["inventory_sha256"]}
            ],
        },
        "components": sorted(components, key=lambda item: item["bom-ref"]),
    }
    return inventory, sbom


def write_inventory(output: Path) -> dict:
    inventory, sbom = collect_inventory()
    output.mkdir(parents=True, exist_ok=True)
    (output / "dependency-inventory.json").write_bytes(canonical_json(inventory))
    (output / "sbom.cdx.json").write_bytes(canonical_json(sbom))
    return {
        "valid": True,
        "python_packages": len(inventory["python"]),
        "frontend_packages": len(inventory["frontend"]),
        "inventory_sha256": inventory["inventory_sha256"],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    try:
        result = write_inventory(args.output)
    except Exception:
        result = {"valid": False, "error": "dependency_inventory_invalid"}
    print(json.dumps(result, sort_keys=True))
    return 0 if result["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
