"""Bounded original-byte ingestion; filenames are metadata, never paths."""

import hashlib
from threading import Lock
from typing import BinaryIO

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..models import CatalogSourceBlob
from ..settings import settings
from .service import fail

_validation_cache: dict[tuple, int] = {}
_validation_lock = Lock()


def limit_error(code: str, limit: int, setting: str) -> HTTPException:
    return HTTPException(413, detail={"code": code, "limit": limit, "configurable_setting": setting})


def read_upload(stream: BinaryIO) -> tuple[bytes, str]:
    content = bytearray()
    digest = hashlib.sha256()
    while chunk := stream.read(1024 * 1024):
        if len(content) + len(chunk) > settings.catalog_pdf_max_bytes:
            raise limit_error("catalog_source_too_large", settings.catalog_pdf_max_bytes, "CATALOG_PDF_MAX_BYTES")
        digest.update(chunk)
        content.extend(chunk)
    return bytes(content), digest.hexdigest()


def validate_pdf(content: bytes) -> int:
    if len(content) > settings.catalog_pdf_max_bytes:
        raise limit_error("catalog_source_too_large", settings.catalog_pdf_max_bytes, "CATALOG_PDF_MAX_BYTES")
    if not content.startswith(b"%PDF-"):
        raise fail("catalog_source_invalid_pdf", 422)
    from .parts_extraction.process import configuration, extract
    config = configuration(settings)
    key = (hashlib.sha256(content).hexdigest(), tuple(sorted(config.items())))
    with _validation_lock:
        cached = _validation_cache.get(key)
    if cached is not None:
        return cached
    result = extract(content, "validate", 0, config)
    if result.get("error") == "catalog_source_page_limit":
        raise limit_error("catalog_source_page_limit", settings.catalog_pdf_max_pages, "CATALOG_PDF_MAX_PAGES")
    if result.get("error"):
        raise fail(result["error"], 422)
    # Cache only successful metadata, bounded to 32 exact SHA/config identities.
    # Never retain source bytes or skip hashing the current content.
    with _validation_lock:
        if len(_validation_cache) >= 32:
            _validation_cache.pop(next(iter(_validation_cache)))
        _validation_cache[key] = result["page_count"]
    return result["page_count"]


def shared_blob(db: Session, content: bytes, digest: str | None = None) -> CatalogSourceBlob:
    digest = digest or hashlib.sha256(content).hexdigest()
    existing = db.scalar(select(CatalogSourceBlob).where(CatalogSourceBlob.sha256 == digest))
    if existing is not None:
        if existing.byte_length != len(content) or existing.content != content:
            raise fail("catalog_source_integrity", 422)
        return existing
    try:
        with db.begin_nested():
            blob = CatalogSourceBlob(sha256=digest, content=content, byte_length=len(content))
            db.add(blob)
            db.flush()
        return blob
    except IntegrityError:
        blob = db.scalar(select(CatalogSourceBlob).where(CatalogSourceBlob.sha256 == digest))
        if blob is None or blob.content != content:
            raise fail("catalog_source_integrity", 422) from None
        return blob
