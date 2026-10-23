"""Single-installation management proposals; never a template editing API."""
from __future__ import annotations

import hashlib
from typing import Literal

from fastapi import APIRouter, Depends, Query, Response
from pydantic import Field
from sqlalchemy import func, or_, select, update
from sqlalchemy.orm import Session

from ..audit import add_audit_log
from ..database import get_db
from ..models import (
    DocumentTemplate,
    DocumentTemplateVersion,
    StudioProposal,
    StudioProposalAttachment,
    StudioProposalDraft,
    StudioProposalEvent,
    User,
    utcnow,
)
from ..permissions import Permission, has_permission, require_permission
from .files import normalize_image
from .schemas import DraftCreate, ImageUpload, StrictModel

router = APIRouter(prefix='/api/studio/proposals', tags=['studio-proposals'])
access = require_permission(Permission.STUDIO_PROPOSE)
manager = require_permission(Permission.TEMPLATES_MANAGE)


class AttachmentInput(StrictModel):
    filename: str = Field(min_length=1, max_length=120, pattern=r'^[^/\\\x00-\x1f]+$')
    media_type: Literal['image/png', 'image/jpeg']
    content_base64: str = Field(min_length=1, max_length=2_700_000)


class ProposalInput(StrictModel):
    template_id: int = Field(gt=0)
    target_version_id: int = Field(gt=0)
    language: Literal['bg', 'en', 'ru']
    title: str = Field(min_length=3, max_length=255)
    description: str = Field(min_length=10, max_length=10_000)
    attachments: list[AttachmentInput] = Field(default_factory=list, max_length=3)


class CommentInput(StrictModel):
    expected_revision: int = Field(ge=1)
    body: str = Field(min_length=3, max_length=5000)


class DecisionInput(StrictModel):
    expected_revision: int = Field(ge=1)
    status: Literal['ACCEPTED', 'REJECTED']
    reason: str = Field(min_length=3, max_length=5000)


class ProposalDraftInput(StrictModel):
    expected_revision: int = Field(ge=1)
    title: str = Field(min_length=1, max_length=255)
    base_version_id: int | None = Field(default=None, gt=0)


def scoped(user):
    return [] if has_permission(user, Permission.TEMPLATES_MANAGE) else [StudioProposal.author_id == user.id]


def visible(db, proposal_id, user):
    from .routes import fail
    item = db.scalar(select(StudioProposal).where(StudioProposal.id == proposal_id, *scoped(user)))
    if item is None:
        fail('studio_not_found', 404)
    return item


def event(db, item, user, kind, body, *, draft_id=None, version_id=None):
    db.add(StudioProposalEvent(proposal_id=item.id, revision=item.revision, kind=kind,
        body=body, author_id=user.id, draft_id=draft_id, version_id=version_id))
    add_audit_log(db, user, 'studio_proposal', item.id, 'studio_proposal_' + kind.lower(),
        {'revision': item.revision, 'target_version_id': item.target_version_id,
         'draft_id': draft_id, 'version_id': version_id})


def advance(db, item, expected, **values):
    from .routes import fail
    result = db.execute(update(StudioProposal).where(StudioProposal.id == item.id,
        StudioProposal.revision == expected).values(revision=StudioProposal.revision + 1, **values))
    if result.rowcount != 1:
        db.rollback()
        fail('studio_conflict', 409)
    db.refresh(item)


def output(db, p, *, detail=False, before_revision=None):
    template = db.get(DocumentTemplate, p.template_id)
    version = db.get(DocumentTemplateVersion, p.target_version_id)
    newest = db.scalar(select(func.max(DocumentTemplateVersion.version)).where(
        DocumentTemplateVersion.template_id == p.template_id, DocumentTemplateVersion.language == p.language,
        DocumentTemplateVersion.is_published.is_(True))) or 0
    result = {key: getattr(p, key) for key in ('id', 'template_id', 'target_version_id', 'author_id', 'language',
        'title', 'description', 'status', 'revision', 'created_at', 'decided_at', 'decided_by_id', 'decision_reason')}
    result.update(author_name=db.get(User, p.author_id).full_name, target_version=version.version,
        template_name={'bg': template.name_bg, 'en': template.name_en, 'ru': template.name_ru},
        newer_published=newest > version.version,
        decided_by_name=db.get(User, p.decided_by_id).full_name if p.decided_by_id else None)
    if detail:
        result['attachments'] = [{'id': a.id, 'sha256': a.sha256, 'width': a.width, 'height': a.height,
            'download_endpoint': f'/studio/proposals/{p.id}/attachments/{a.id}'} for a in db.scalars(
                select(StudioProposalAttachment).where(StudioProposalAttachment.proposal_id == p.id).order_by(StudioProposalAttachment.id))]
        history = select(StudioProposalEvent).where(StudioProposalEvent.proposal_id == p.id)
        if before_revision is not None:
            history = history.where(StudioProposalEvent.revision < before_revision)
        rows = list(db.scalars(history.order_by(StudioProposalEvent.revision.desc()).limit(101)))
        result['events_before'] = rows[99].revision if len(rows) > 100 else None
        result['events'] = [{key: getattr(e, key) for key in ('id', 'kind', 'body', 'revision', 'created_at', 'draft_id', 'version_id')}
            | {'author_name': db.get(User, e.author_id).full_name,
               'version_number': db.get(DocumentTemplateVersion, e.version_id).version if e.version_id else None}
            for e in reversed(rows[:100])]
        result['drafts'] = [{'draft_id': d.draft_id, 'base_version_id': d.base_version_id} for d in db.scalars(
            select(StudioProposalDraft).where(StudioProposalDraft.proposal_id == p.id).order_by(StudioProposalDraft.id))]
    return result


@router.get('')
def proposals(status: Literal['PENDING', 'ACCEPTED', 'REJECTED'] | None = None,
              language: Literal['bg', 'en', 'ru'] | None = None, template_id: int | None = None,
              q: str = Query(default='', max_length=200), limit: int = Query(default=30, ge=1, le=50),
              offset: int = Query(default=0, ge=0), user: User = Depends(access), db: Session = Depends(get_db)):
    filters = scoped(user)
    pending = db.scalar(select(func.count(StudioProposal.id)).where(*filters, StudioProposal.status == 'PENDING'))
    if status:
        filters.append(StudioProposal.status == status)
    if language:
        filters.append(StudioProposal.language == language)
    if template_id:
        filters.append(StudioProposal.template_id == template_id)
    if q.strip():
        search = q.strip()
        if db.bind.dialect.name == 'sqlite':
            # SQLite's built-in lower()/NOCASE only fold ASCII. Keep the same
            # BG/EN/RU search behaviour in local installations without changing
            # global SQL functions or persisting a second proposal registry.
            db.connection().connection.driver_connection.create_function(
                'studio_casefold', 1, lambda value: (value or '').casefold(), deterministic=True)

            def matches(column):
                return func.studio_casefold(column).contains(search.casefold(), autoescape=True)
        else:
            def matches(column):
                return column.icontains(search, autoescape=True)
        filters.append(or_(matches(StudioProposal.title), matches(StudioProposal.description),
            StudioProposal.author_id.in_(select(User.id).where(matches(User.full_name))),
            StudioProposal.template_id.in_(select(DocumentTemplate.id).where(or_(
                matches(DocumentTemplate.code), matches(DocumentTemplate.name_bg), matches(DocumentTemplate.name_en), matches(DocumentTemplate.name_ru))))))
    total = db.scalar(select(func.count(StudioProposal.id)).where(*filters))
    rows = db.scalars(select(StudioProposal).where(*filters).order_by(StudioProposal.created_at.desc(), StudioProposal.id.desc()).limit(limit).offset(offset))
    return {'items': [output(db, p) for p in rows], 'total': total, 'pending_count': pending}


@router.post('', status_code=201)
def create_proposal(payload: ProposalInput, user: User = Depends(access), db: Session = Depends(get_db)):
    from .routes import commit, fail
    version = db.get(DocumentTemplateVersion, payload.target_version_id)
    if version is None or version.template_id != payload.template_id or version.language != payload.language:
        fail('studio_base_mismatch')
    images = []
    try:
        for attachment in payload.attachments:
            images.append(normalize_image(ImageUpload(**attachment.model_dump(), purpose='IDENTITY')))
    except ValueError as exc:
        fail(str(exc) if str(exc).startswith('studio_') else 'studio_image_invalid')
    p = StudioProposal(**payload.model_dump(exclude={'attachments'}), author_id=user.id, status='PENDING', revision=1)
    db.add(p)
    db.flush()
    for content, width, height in images:
        db.add(StudioProposalAttachment(proposal_id=p.id, content=content, width=width, height=height,
            sha256=hashlib.sha256(content).hexdigest(), created_by_id=user.id))
    event(db, p, user, 'CREATED', payload.description, version_id=p.target_version_id)
    commit(db)
    return output(db, p, detail=True)


@router.get('/{proposal_id}')
def proposal_detail(proposal_id: int, before_revision: int | None = Query(default=None, gt=0),
                    user: User = Depends(access), db: Session = Depends(get_db)):
    return output(db, visible(db, proposal_id, user), detail=True, before_revision=before_revision)


@router.get('/{proposal_id}/attachments/{attachment_id}')
def attachment_content(proposal_id: int, attachment_id: int, user: User = Depends(access), db: Session = Depends(get_db)):
    from .routes import fail
    visible(db, proposal_id, user)
    image = db.get(StudioProposalAttachment, attachment_id)
    if image is None or image.proposal_id != proposal_id:
        fail('studio_not_found', 404)
    return Response(image.content, media_type='image/png', headers={'Cache-Control': 'private, no-store',
        'X-Content-Type-Options': 'nosniff', 'Content-Disposition': 'inline; filename="proposal-evidence.png"'})


@router.post('/{proposal_id}/comments', status_code=201)
def comment(proposal_id: int, payload: CommentInput, user: User = Depends(access), db: Session = Depends(get_db)):
    from .routes import commit
    p = visible(db, proposal_id, user)
    advance(db, p, payload.expected_revision)
    event(db, p, user, 'COMMENT', payload.body)
    commit(db)
    return output(db, p, detail=True)


@router.post('/{proposal_id}/decision')
def decide(proposal_id: int, payload: DecisionInput, user: User = Depends(manager), db: Session = Depends(get_db)):
    from .routes import commit, fail
    p = visible(db, proposal_id, user)
    if p.status != 'PENDING':
        fail('studio_conflict', 409)
    advance(db, p, payload.expected_revision, status=payload.status, decided_at=utcnow(),
        decided_by_id=user.id, decision_reason=payload.reason)
    event(db, p, user, payload.status, payload.reason)
    commit(db)
    return output(db, p, detail=True)


@router.post('/{proposal_id}/drafts', status_code=201)
def proposal_draft(proposal_id: int, payload: ProposalDraftInput, user: User = Depends(manager), db: Session = Depends(get_db)):
    from .routes import build_draft, commit, draft_output, fail
    p = visible(db, proposal_id, user)
    if p.status != 'ACCEPTED':
        fail('studio_proposal_not_accepted', 409)
    base = db.get(DocumentTemplateVersion, payload.base_version_id or p.target_version_id)
    if base is None or base.template_id != p.template_id or base.language != p.language:
        fail('studio_base_mismatch')
    target = db.get(DocumentTemplateVersion, p.target_version_id)
    if base.id != target.id and base.version <= target.version:
        fail('studio_base_mismatch')
    if not base.layout_contract.get('studio') or not base.is_published:
        fail('studio_proposal_reference_only')
    advance(db, p, payload.expected_revision)
    draft = build_draft(db, p.template_id, DraftCreate(title=payload.title, language=p.language, base_version_id=base.id), user)
    db.add(StudioProposalDraft(proposal_id=p.id, draft_id=draft.id, base_version_id=base.id, created_by_id=user.id))
    event(db, p, user, 'DRAFT_CREATED', payload.title, draft_id=draft.id, version_id=base.id)
    commit(db)
    return draft_output(draft)


def record_publication(db, draft, version, user):
    link = db.scalar(select(StudioProposalDraft).where(StudioProposalDraft.draft_id == draft.id))
    if link is None:
        return
    p = db.get(StudioProposal, link.proposal_id)
    advance(db, p, p.revision)
    event(db, p, user, 'PUBLISHED', version.change_note, draft_id=draft.id, version_id=version.id)
