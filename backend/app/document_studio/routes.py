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
    StudioActivation,
    User,
    utcnow,
)
from ..permissions import Permission, require_permission
from ..template_engine import DOCX_MEDIA_TYPE
from .files import normalize_image, validate_docx
from .schemas import (
    FIELD_CATALOG,
    SUPPORTED_TYPES,
    TABLE_CATALOG,
    ActivationInput,
    CompanyIdentity,
    DraftCreate,
    DraftUpdate,
    IdentityUpdate,
    ImageUpload,
    Layout,
    PreviewInput,
    PublishInput,
    StrictModel,
    TemplateCreate,
    initial_layout,
    publication_fields,
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
    from .publication import lock_company
    lock_company(db)
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
    return {"schema_version": 2, "schema": Layout.model_json_schema(),
            "fields": [{"code": code, "group": group} for code, group in FIELD_CATALOG.items()],
            "supported_document_types": SUPPORTED_TYPES, "renderer_enabled": True}


@router.get("/templates")
def templates(_: User = Depends(reader), db: Session = Depends(get_db)):
    selected = {}
    for item in db.scalars(select(StudioActivation).order_by(StudioActivation.revision.desc())):
        selected.setdefault((item.document_type, item.language), item)
    rows = db.scalars(select(DocumentTemplate).options(selectinload(DocumentTemplate.versions).defer(DocumentTemplateVersion.source_content))
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
            "studio": bool(v.layout_contract.get("studio")),
            "active": bool((selection := selected.get((t.document_type, v.language))) and selection.version_id == v.id),
            "active_version_id": selection.version_id if selection else None,
            "validation_report": v.validation_report if v.layout_contract.get("studio") else None,
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
        "created_at", "updated_at")} | {"status": "DRAFT", "renderer_enabled": True}


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
    layout = initial_layout(template.document_type).model_dump()
    # New workspaces start with the required business data in editable flow.
    # Existing v1 workspaces remain readable and are validated at publication.
    slots = [b for b in layout["blocks"] if b["type"] == "signature"]
    layout["blocks"] = [b for b in layout["blocks"] if b["type"] != "signature"]
    layout["blocks"] += [{"id": code.lower(), "type": "field", "field": code}
                         for code in publication_fields(template.document_type)]
    for source, workflow in TABLE_CATALOG.items():
        if workflow == template.document_type:
            keys = [("date", 25), ("event_type", 25), ("description", 50)] if source == "REPAIR_EVENTS" else [("description", 70), ("quantity", 30)]
            labels = {"description": {"bg": "Описание", "en": "Description", "ru": "Описание"},
                "quantity": {"bg": "Количество", "en": "Quantity", "ru": "Количество"},
                "date": {"bg": "Дата", "en": "Date", "ru": "Дата"},
                "event_type": {"bg": "Събитие", "en": "Event", "ru": "Событие"}}
            layout["blocks"].append({"id": source.lower(), "type": "dynamic_table", "source": source,
                "style": {"border_pt": .5},
                "columns": [{"key": key, "label": labels[key][payload.language], "width_percent": width} for key, width in keys]})
    layout["blocks"] += slots
    layout["schema_version"] = 2
    layout = Layout.model_validate(layout).model_dump()
    if payload.base_version_id:
        base = db.get(DocumentTemplateVersion, payload.base_version_id)
        if base is None or base.template_id != template_id or base.language != payload.language:
            fail("studio_base_mismatch")
        if base.layout_contract.get("studio"):
            from ..template_engine import source_bytes
            from .renderer import manifest_from_source
            layout = manifest_from_source(source_bytes(base))["layout"]
    item = DocumentEditorDraft(template_id=template_id, **payload.model_dump(),
        layout=layout, schema_version=layout["schema_version"], created_by_id=user.id, updated_by_id=user.id)
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
    from types import SimpleNamespace

    from .publication import snapshot
    try:
        snapshot(db, SimpleNamespace(layout=payload.layout.model_dump(), language=item.language), template.document_type)
    except ValueError as exc:
        fail(str(exc))
    result = db.execute(update(DocumentEditorDraft).where(DocumentEditorDraft.id == draft_id,
        DocumentEditorDraft.revision == payload.expected_revision).values(title=payload.title,
        layout=payload.layout.model_dump(), schema_version=payload.layout.schema_version,
        revision=DocumentEditorDraft.revision + 1,
        updated_by_id=user.id, updated_at=utcnow()))
    if result.rowcount != 1:
        db.rollback()
        fail("studio_conflict", 409)
    add_audit_log(db, user, "document_editor_draft", draft_id, "studio_draft_saved",
                  {"revision": payload.expected_revision + 1})
    commit(db)
    db.refresh(item)
    return draft_output(item)


def current_draft(db, draft_id, revision):
    draft = db.get(DocumentEditorDraft, draft_id)
    if draft is None:
        fail("studio_not_found", 404)
    if draft.revision != revision:
        fail("studio_conflict", 409)
    return draft


@router.post("/drafts/{draft_id}/preview")
def preview_draft(draft_id: int, payload: PreviewInput, user: User = Depends(reader), db: Session = Depends(get_db)):
    from .publication import receipt, snapshot, validate_render
    draft = current_draft(db, draft_id, payload.expected_revision)
    template = db.get(DocumentTemplate, draft.template_id)
    try:
        manifest = snapshot(db, draft, template.document_type)
        docx, pdf, report = validate_render(manifest, payload.rows, raster=True)
    except ValueError as exc:
        fail(str(exc) if str(exc).startswith("studio_") else "studio_invalid")
    # No ORM mutation, official number, reservation, signer or persistent file.
    return {"report": report, "receipt": receipt(draft, manifest, user.id),
            "docx": base64.b64encode(docx).decode(), "pdf": base64.b64encode(pdf).decode()}


@router.post("/drafts/{draft_id}/publish", status_code=201)
def publish_draft(draft_id: int, payload: PublishInput, user: User = Depends(manager), db: Session = Depends(get_db)):
    from .publication import lock_company, publication_source, snapshot, verify_receipt
    from .renderer import digest
    draft = current_draft(db, draft_id, payload.expected_revision)
    template = db.get(DocumentTemplate, draft.template_id)
    try:
        manifest = snapshot(db, draft, template.document_type)
        verify_receipt(payload.receipt, draft, manifest, user.id)
        source, report = publication_source(manifest)
    except ValueError as exc:
        fail(str(exc) if str(exc).startswith("studio_") else "studio_invalid")
    # Serialize against saves/publications after conversion, without publishing
    # anything if either the workspace or company snapshot changed meanwhile.
    result = db.execute(update(DocumentEditorDraft).where(DocumentEditorDraft.id == draft.id,
        DocumentEditorDraft.revision == payload.expected_revision).values(revision=DocumentEditorDraft.revision + 1))
    if result.rowcount != 1:
        db.rollback()
        fail("studio_conflict", 409)
    company_revision = manifest["company"]["revision"]
    lock_company(db)
    current_company_revision = db.scalar(select(CompanyProfile.revision).where(CompanyProfile.id == 1)) or 0
    if current_company_revision != company_revision:
        db.rollback()
        fail("studio_conflict", 409)
    if company_revision:
        result = db.execute(update(CompanyProfile).where(CompanyProfile.id == 1,
            CompanyProfile.revision == company_revision).values(revision=CompanyProfile.revision))
        if result.rowcount != 1:
            db.rollback()
            fail("studio_conflict", 409)
    number = (db.scalar(select(func.max(DocumentTemplateVersion.version)).where(
        DocumentTemplateVersion.template_id == template.id, DocumentTemplateVersion.language == draft.language)) or 0) + 1
    now = utcnow()
    version = DocumentTemplateVersion(template_id=template.id, version=number, language=draft.language,
        source_content=source, source_filename="studio-template.docx", source_media_type=DOCX_MEDIA_TYPE,
        source_sha256=digest(source), layout_contract={"studio": 1, "schema_version": manifest["layout"]["schema_version"],
        "manifest_sha256": report["manifest_sha256"], "draft_id": draft.id, "draft_revision": payload.expected_revision},
        required_fields=["DOCUMENT_NUMBER", "PREPARER_NAME", "SIGNATURE_STATUS", *publication_fields(template.document_type)],
        change_note=payload.change_note, created_by_id=user.id, validation_status="PASSED",
        validation_report=report, validated_at=now, validated_by_id=user.id,
        is_published=True, published_by_id=user.id, published_at=now)
    db.add(version)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        fail("studio_conflict", 409)
    add_audit_log(db, user, "document_template_version", version.id, "studio_version_published",
        {"draft_id": draft.id, "draft_revision": payload.expected_revision, "source_sha256": version.source_sha256,
         "company_revision": company_revision, "change_note": payload.change_note})
    commit(db)
    return {"id": version.id, "version": number, "source_sha256": version.source_sha256,
            "draft_revision": payload.expected_revision + 1, "active": False, "validation_report": report}


@router.post("/versions/{version_id}/activate", status_code=201)
def activate_version(version_id: int, payload: ActivationInput, user: User = Depends(manager), db: Session = Depends(get_db)):
    from ..template_engine import source_bytes
    from .publication import active_selection
    from .renderer import digest, manifest_from_source
    version = db.get(DocumentTemplateVersion, version_id)
    if version is None:
        fail("studio_not_found", 404)
    if not version.layout_contract.get("studio") or not version.is_published or version.validation_status != "PASSED" or not version.template.is_active:
        fail("studio_activation_invalid")
    try:
        source = source_bytes(version)
        manifest = manifest_from_source(source)
        if (digest(source) != version.source_sha256 or manifest["document_type"] != version.template.document_type
                or manifest["language"] != version.language or not version.validation_report.get("valid")):
            raise ValueError
    except (ValueError, KeyError, TypeError):
        fail("studio_activation_invalid")
    selected = active_selection(db, version.template.document_type, version.language)
    if (selected.version_id if selected else None) != payload.expected_version_id:
        fail("studio_conflict", 409)
    activation = StudioActivation(document_type=version.template.document_type, language=version.language,
        revision=selected.revision + 1 if selected else 1, version_id=version.id,
        created_by_id=user.id, reason=payload.reason)
    db.add(activation)
    add_audit_log(db, user, "document_template_version", version.id, "studio_version_activated",
        {"previous_version_id": payload.expected_version_id, "reason": payload.reason})
    commit(db)
    return {"version_id": version.id, "active": True}
