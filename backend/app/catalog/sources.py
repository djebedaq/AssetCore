from __future__ import annotations

import hashlib
import json
from functools import lru_cache
from pathlib import Path
from typing import Any

CATALOG_VERSION = "PARTS_CATALOG_V2"
RESOURCE_ROOT = Path(__file__).resolve().parents[2] / "resources"
CATALOG_ROOT = RESOURCE_ROOT / "catalog" / "v2"
SOURCE_ROOT = RESOURCE_ROOT / "technical_docs" / "PARTS_CATALOG"
MANIFEST_PATH = CATALOG_ROOT / "manifest.json"


class CatalogSourceError(RuntimeError):
    pass


@lru_cache(maxsize=1)
def load_manifest() -> dict[str, Any]:
    payload = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    if payload.get("dataset_version") != CATALOG_VERSION:
        raise CatalogSourceError("Невалидна версия на активния каталог.")
    return payload


def dataset_sources() -> list[dict[str, Any]]:
    return list(load_manifest().get("sources") or [])


def source_by_id(source_id: str) -> dict[str, Any]:
    source = next(
        (item for item in dataset_sources() if item.get("source_id") == source_id), None
    )
    if source is None:
        raise CatalogSourceError(f"Непознат каталожен източник: {source_id}")
    return source


def source_path(source: dict[str, Any]) -> Path:
    return SOURCE_ROOT / str(source["filename"])


def source_relative_path(source: dict[str, Any]) -> str:
    return f"PARTS_CATALOG/{source['filename']}"


def source_digest(source: dict[str, Any]) -> str:
    path = source_path(source)
    if not path.is_file():
        raise CatalogSourceError(f"Липсва контролиран източник: {source['filename']}")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def ensure_source_integrity(source_id: str) -> dict[str, Any]:
    source = source_by_id(source_id)
    actual = source_digest(source)
    if actual != source.get("sha256"):
        raise CatalogSourceError(
            f"Променен източник без повторна верификация: {source['filename']}"
        )
    return source


def load_source_dataset(source: dict[str, Any]) -> dict[str, Any]:
    relative = source.get("records_file")
    if not relative:
        return {"records": [], "hotspots": []}
    payload = json.loads((CATALOG_ROOT / str(relative)).read_text(encoding="utf-8"))
    if payload.get("source_id") != source.get("source_id"):
        raise CatalogSourceError(f"Несъответстващ dataset source_id: {relative}")
    return payload


def load_all_records() -> list[dict[str, Any]]:
    return [
        record
        for source in dataset_sources()
        for record in load_source_dataset(source).get("records") or []
    ]


def load_all_hotspots() -> list[dict[str, Any]]:
    return [
        hotspot
        for source in dataset_sources()
        for hotspot in load_source_dataset(source).get("hotspots") or []
    ]
