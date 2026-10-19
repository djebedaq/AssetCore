from __future__ import annotations

import base64
import hashlib

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import Field
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from ..audit import add_audit_log
from ..database import get_db
from ..models import (
    CompanyBrandImage,
    CompanyProfile,
    DocumentEditorDraft,
    DocumentTemplate,
    DocumentTemplateVersion,
    User,
    utcnow,
)
from ..permissions import Permission, require_permission
from ..template_engine import DOCX_MEDIA_TYPE
from .files import normalize_image, validate_docx
from .schemas import (
    FIELD_CATALOG,
    SUPPORTED_TYPES,
    CompanyIdentity,
    DraftCreate,
    DraftUpdate,
    IdentityUpdate,
    ImageUpload,
    Layout,
    StrictModel,
    TemplateCreate,
    initial_layout,
    validate_workflow,
)

router = APIRouter(prefix="/api/studio", tags=["document-studio"])
reader = require_permission(Permission.STUDIO_VIEW)
manager = require_permission(Permission.TEMPLATES_MANAGE)
company_manager = require_permission(Permission.COMPANY_MANAGE)


def fail(code: str, status=422):
    raise HTTPException(status, detail={"code": code})


def commit(db: Session):
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        fail("studio_conflict", 409)


def profile_output(item: CompanyProfile | None):
    return {"revision": item.revision if item else 0,
            "identity": item.identity if item else CompanyIdentity().model_dump(),
            "updated_by_id": item.updated_by_id if item else None,
            "updated_at": item.updated_at if item else None}


def image_output(item: CompanyBrandImage):
    return {"id": item.id, "purpose": item.purpose, "filename": item.filename,
            "sha256": item.sha256, "width": item.width, "height": item.height,
            "created_at": item.created_at, "download_endpoint": f"/studio/images/{item.id}/content"}


def check_images(db: Session, ids: set[int]):
    if ids and set(db.scalars(select(CompanyBrandImage.id).where(CompanyBrandImage.id.in_(ids)))) != ids:
        fail("studio_image_missing")


@router.get("/company")
def company_profile(_: User = Depends(reader), db: Session = Depends(get_db)):
    return profile_output(db.get(CompanyProfile, 1))


@router.put("/company")
def update_company(payload: IdentityUpdate, user: User = Depends(company_manager), db: Session = Depends(get_db)):
    identity = payload.identity.model_dump()
    ids = set(payload.identity.identity_image_ids)
    ids.update(i for i in (payload.identity.primary_logo_id, payload.identity.secondary_logo_id) if i)
    check_images(db, ids)
    now = utcnow()
    if payload.expected_revision == 0:
        db.add(CompanyProfile(id=1, revision=1, identity=identity, updated_by_id=user.id, updated_at=now))
    else:
        result = db.execute(update(CompanyProfile).where(CompanyProfile.id == 1,
            CompanyProfile.revision == payload.expected_revision).values(identity=identity,
            revision=CompanyProfile.revision + 1, updated_by_id=user.id, updated_at=now))
        if result.rowcount != 1:
            db.rollback()
            fail("studio_conflict", 409)
    add_audit_log(db, user, "company_profile", 1, "company_identity_updated",
                  {"revision": payload.expected_revision + 1, "image_ids": sorted(ids)})
    commit(db)
    return profile_output(db.get(CompanyProfile, 1))


@router.get("/images")
def images(_: User = Depends(reader), db: Session = Depends(get_db)):
    return [image_output(i) for i in db.scalars(select(CompanyBrandImage).order_by(CompanyBrandImage.id.desc()))]


@router.post("/images", status_code=201)
def upload_image(payload: ImageUpload, user: User = Depends(company_manager), db: Session = Depends(get_db)):
    try:
        content, width, height = normalize_image(payload)
    except ValueError as exc:
        fail(str(exc) if str(exc).startswith("studio_") else "studio_image_invalid")
    item = CompanyBrandImage(purpose=payload.purpose, filename="brand-image.png", content=content,
        width=width, height=height, sha256=hashlib.sha256(content).hexdigest(), created_by_id=user.id)
    db.add(item)
    db.flush()
    add_audit_log(db, user, "company_brand_image", item.id, "company_image_uploaded",
                  {"sha256": item.sha256, "purpose": item.purpose})
    commit(db)
    return image_output(item)


@router.get("/images/{image_id}/content")
def image_content(image_id: int, _: User = Depends(reader), db: Session = Depends(get_db)):
    item = db.get(CompanyBrandImage, image_id)
    if item is None:
        fail("studio_not_found", 404)
    return Response(item.content, media_type="image/png", headers={
        "Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff",
        "Content-Security-Policy": "default-src 'none'; sandbox",
        "Content-Disposition": 'inline; filename="brand-image.png"'})


@router.get("/schema")
def layout_schema(_: User = Depends(reader)):
    return {"schema_version": 1, "schema": Layout.model_json_schema(),
            "fields": [{"code": code, "group": group} for code, group in FIELD_CATALOG.items()],
            "supported_document_types": SUPPORTED_TYPES, "renderer_enabled": False}


@router.get("/templates")
def templates(_: User = Depends(reader), db: Session = Depends(get_db)):
    rows = db.scalars(select(DocumentTemplate).options(selectinload(DocumentTemplate.versions))
                      .order_by(DocumentTemplate.document_type, DocumentTemplate.code))
    return [{"id": t.id, "code": t.code, "document_type": t.document_type,
        "name_bg": t.name_bg, "name_en": t.name_en, "name_ru": t.name_ru,
        "is_active": t.is_active, "authoring_supported": t.document_type in SUPPORTED_TYPES,
        "versions": [{"id": v.id, "version": v.version, "language": v.language,
            "status": "PUBLISHED" if v.is_published else "REFERENCE" if v.layout_contract.get("reference_only") else "DRAFT",
            "validation_status": v.validation_status, "source_sha256": v.source_sha256,
            "change_note": v.change_note, "created_at": v.created_at,
            "created_by_id": v.created_by_id, "published_at": v.published_at,
            "source_filename": v.source_filename, "numbering_rule": v.numbering_rule,
            "effective_from": v.effective_from, "effective_to": v.effective_to,
            "download_endpoint": f"/studio/versions/{v.id}/source"}
            for v in sorted(t.versions, key=lambda v: (v.language, v.version), reverse=True)]} for t in rows]


@router.post("/templates", status_code=201)
def create_template(payload: TemplateCreate, user: User = Depends(manager), db: Session = Depends(get_db)):
    item = DocumentTemplate(**payload.model_dump())
    db.add(item)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        fail("studio_conflict", 409)
    add_audit_log(db, user, "document_template", item.id, "studio_template_created", {"code": item.code})
    commit(db)
    return {"id": item.id}


@router.get("/versions/{version_id}/source")
def version_source(version_id: int, _: User = Depends(reader), db: Session = Depends(get_db)):
    from ..template_engine import TemplateValidationError, source_bytes
    item = db.get(DocumentTemplateVersion, version_id)
    if item is None:
        fail("studio_not_found", 404)
    try:
        content = source_bytes(item)
    except TemplateValidationError:
        fail("studio_not_found", 404)
    return Response(content, media_type=item.source_media_type or DOCX_MEDIA_TYPE, headers={
        "Content-Disposition": 'attachment; filename="template-source.docx"',
        "Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"})


class DocxImport(StrictModel):
    language: str = Field(pattern="^(bg|en|ru)$")
    filename: str = Field(min_length=1, max_length=120, pattern=r"^[^/\\\x00-\x1f]+\.(?i:docx)$")
    content_base64: str = Field(min_length=1, max_length=16_000_000)
    change_note: str = Field(min_length=1, max_length=2000)


@router.post("/templates/{template_id}/import", status_code=201)
def import_docx(template_id: int, payload: DocxImport, user: User = Depends(manager), db: Session = Depends(get_db)):
    if db.get(DocumentTemplate, template_id) is None:
        fail("studio_not_found", 404)
    try:
        content = base64.b64decode(payload.content_base64, validate=True)
        digest = validate_docx(content)
    except ValueError:
        fail("studio_docx_unsafe")
    number = (db.scalar(select(func.max(DocumentTemplateVersion.version)).where(
        DocumentTemplateVersion.template_id == template_id,
        DocumentTemplateVersion.language == payload.language)) or 0) + 1
    item = DocumentTemplateVersion(template_id=template_id, version=number, language=payload.language,
        source_filename=payload.filename, source_media_type=DOCX_MEDIA_TYPE,
        source_content=content, source_sha256=digest, layout_contract={"reference_only": True,
        "studio_import": 1}, change_note=payload.change_note, created_by_id=user.id)
    db.add(item)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        fail("studio_conflict", 409)
    add_audit_log(db, user, "document_template_version", item.id, "studio_docx_reference_imported",
                  {"source_sha256": digest, "version": number})
    commit(db)
    return {"id": item.id, "status": "REFERENCE", "source_sha256": digest,
            "structural_conversion": False}


def draft_output(d: DocumentEditorDraft):
    return {key: getattr(d, key) for key in ("id", "template_id", "base_version_id", "title",
        "language", "schema_version", "layout", "revision", "created_by_id", "updated_by_id",
        "created_at", "updated_at")} | {"status": "DRAFT", "renderer_enabled": False}


@router.get("/templates/{template_id}/drafts")
def list_drafts(template_id: int, _: User = Depends(reader), db: Session = Depends(get_db)):
    return [draft_output(d) for d in db.scalars(select(DocumentEditorDraft).where(
        DocumentEditorDraft.template_id == template_id).order_by(DocumentEditorDraft.updated_at.desc()))]


@router.post("/templates/{template_id}/drafts", status_code=201)
def create_draft(template_id: int, payload: DraftCreate, user: User = Depends(manager), db: Session = Depends(get_db)):
    template = db.get(DocumentTemplate, template_id)
    if template is None:
        fail("studio_not_found", 404)
    if template.document_type not in SUPPORTED_TYPES:
        fail("studio_workflow_unsupported")
    if payload.base_version_id:
        base = db.get(DocumentTemplateVersion, payload.base_version_id)
        if base is None or base.template_id != template_id or base.language != payload.language:
            fail("studio_base_mismatch")
    item = DocumentEditorDraft(template_id=template_id, **payload.model_dump(),
        layout=initial_layout(template.document_type).model_dump(), created_by_id=user.id, updated_by_id=user.id)
    db.add(item)
    db.flush()
    add_audit_log(db, user, "document_editor_draft", item.id, "studio_draft_created",
                  {"template_id": template_id, "base_version_id": payload.base_version_id})
    commit(db)
    return draft_output(item)


@router.get("/drafts/{draft_id}")
def get_draft(draft_id: int, _: User = Depends(reader), db: Session = Depends(get_db)):
    item = db.get(DocumentEditorDraft, draft_id)
    if item is None:
        fail("studio_not_found", 404)
    return draft_output(item)


@router.put("/drafts/{draft_id}")
def update_draft(draft_id: int, payload: DraftUpdate, user: User = Depends(manager), db: Session = Depends(get_db)):
    item = db.get(DocumentEditorDraft, draft_id)
    if item is None:
        fail("studio_not_found", 404)
    template = db.get(DocumentTemplate, item.template_id)
    try:
        validate_workflow(payload.layout, template.document_type)
    except ValueError as exc:
        fail(str(exc))
    check_images(db, {b.image_id for b in payload.layout.blocks if b.type in {"image", "logo"}})
    result = db.execute(update(DocumentEditorDraft).where(DocumentEditorDraft.id == draft_id,
        DocumentEditorDraft.revision == payload.expected_revision).values(title=payload.title,
        layout=payload.layout.model_dump(), revision=DocumentEditorDraft.revision + 1,
        updated_by_id=user.id, updated_at=utcnow()))
    if result.rowcount != 1:
        db.rollback()
        fail("studio_conflict", 409)
    add_audit_log(db, user, "document_editor_draft", draft_id, "studio_draft_saved",
                  {"revision": payload.expected_revision + 1})
    commit(db)
    db.refresh(item)
    return draft_output(item)
