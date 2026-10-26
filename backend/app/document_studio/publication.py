"""Snapshot-bound rendering validation and stateless preview receipts."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time

from sqlalchemy import select, text

from ..models import CompanyBrandImage, CompanyProfile, StudioActivation
from ..settings import settings
from .renderer import (
    build_source,
    canonical,
    check_layout,
    digest,
    inspect_pdf,
    pdf_required,
    render,
    synthetic_values,
)
from .schemas import (
    CompanyIdentity,
    Layout,
    supports_request_variants,
    validate_publication_fields,
    walk_blocks,
)


def lock_company(db):
    # Serialize first-profile creation and publication even while no profile row
    # exists yet. SQLite's writer lock serializes the corresponding writes.
    if db.bind.dialect.name == "postgresql":
        db.execute(text("SELECT pg_advisory_xact_lock(178865005, 1)"))


def active_selection(db, document_type, language):
    return db.scalar(select(StudioActivation).where(StudioActivation.document_type == document_type,
        StudioActivation.language == language).order_by(StudioActivation.revision.desc()).limit(1))


def snapshot(db, draft, document_type):
    layout = Layout.model_validate(draft.layout)
    profile = db.get(CompanyProfile, 1)
    identity = CompanyIdentity.model_validate(profile.identity if profile else {}).model_dump()
    allowed = set(identity["identity_image_ids"])
    allowed.update(v for v in (identity["primary_logo_id"], identity["secondary_logo_id"]) if v)
    ids = {b.image_id for b in walk_blocks(layout.blocks) if b.type in {"image", "logo", "native_image"} and b.image_id is not None}
    if not ids <= allowed:
        raise ValueError("studio_image_not_allowed")
    # Reject unauthorized cell images before inspecting their layout geometry.
    # Both authorization and bounds remain mandatory for every snapshot.
    check_layout(layout, document_type)
    images = {}
    total = 0
    for image_id in sorted(ids):
        image = db.get(CompanyBrandImage, image_id)
        if image is None or digest(image.content) != image.sha256:
            raise ValueError("studio_image_missing")
        total += len(image.content)
        if total > 5_000_000:
            raise ValueError("studio_source_size")
        images[str(image.id)] = {"sha256": image.sha256, "content": base64.b64encode(image.content).decode()}
    return {"renderer": 1, "layout": layout.model_dump(), "document_type": document_type,
            "language": draft.language, "company": {"revision": profile.revision if profile else 0,
            "identity": identity}, "images": images}


def validate_render(manifest, count=5, *, raster=False, request_variant="MACHINE"):
    if manifest["document_type"] == "PART_REQUEST" and request_variant == "FREE_FORM" and not supports_request_variants(manifest["layout"]):
        raise ValueError("studio_request_variant_mismatch")
    validate_publication_fields(Layout.model_validate(manifest["layout"]), manifest["document_type"])
    values, tables = synthetic_values(manifest["language"], count)
    if manifest["document_type"] == "PART_REQUEST" and supports_request_variants(manifest["layout"]):
        from .diagnostics import request_sample
        _, values, tables = request_sample(manifest["language"], count, request_variant)
    values["REQUEST_VARIANT"] = request_variant
    docx = render(manifest, values, tables)
    pdf = pdf_required(docx)
    report = inspect_pdf(pdf, raster=raster)
    report.update(docx_sha256=digest(docx), rows=count)
    return docx, pdf, report


def receipt(draft, manifest, user_id):
    payload = base64.urlsafe_b64encode(canonical({"draft": draft.id, "revision": draft.revision,
        "manifest": digest(canonical(manifest)), "user": user_id, "expires": int(time.time()) + 900})).decode()
    signature = hmac.new(settings.secret_key.encode(), payload.encode(), hashlib.sha256).hexdigest()
    return payload + "." + signature


def verify_receipt(token, draft, manifest, user_id):
    try:
        payload, signature = token.split(".")
        expected = hmac.new(settings.secret_key.encode(), payload.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(signature, expected):
            raise ValueError
        data = json.loads(base64.urlsafe_b64decode(payload))
        if (data["draft"] != draft.id or data["revision"] != draft.revision or data["user"] != user_id
                or data["manifest"] != digest(canonical(manifest)) or data["expires"] < time.time()):
            raise ValueError
    except (ValueError, KeyError, TypeError):
        raise ValueError("studio_preview_required") from None


def publication_source(manifest):
    source = build_source(manifest)
    variants = ("MACHINE", "FREE_FORM") if manifest["document_type"] == "PART_REQUEST" and supports_request_variants(manifest["layout"]) else ("MACHINE",)
    reports = [{**validate_render(manifest, count, request_variant=variant)[2], "request_variant": variant}
               for variant in variants for count in (1, 5, 30)]
    return source, {"valid": True, "renderer": 1, "cases": reports,
                    "source_sha256": digest(source), "manifest_sha256": digest(canonical(manifest)),
                    "company_revision": manifest["company"]["revision"],
                    "image_sha256": {key: value["sha256"] for key, value in manifest["images"].items()}}
