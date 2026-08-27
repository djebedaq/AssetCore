"""Machine attachment persistence and authorized download responses."""

from __future__ import annotations

import hashlib

from fastapi import HTTPException, Response
from sqlalchemy.orm import Session

from ..attachment_io import _attachment_dict, _decode_file
from ..audit import add_audit_log
from ..industrial_schemas import AttachmentCreate
from ..models import Machine, MachineAttachment, User
from ..persistence import _commit
from ..workflow import add_machine_event


def add_machine_attachment(
    machine_id: int, payload: AttachmentCreate, user: User, db: Session
) -> dict:
    machine = db.get(Machine, machine_id)
    if machine is None:
        raise HTTPException(404, "Машината не е намерена.")
    filename, content = _decode_file(payload)
    item = MachineAttachment(
        machine_id=machine.id,
        kind=payload.kind,
        filename=filename,
        media_type=payload.media_type,
        content=content,
        sha256=hashlib.sha256(content).hexdigest(),
        description=payload.description,
        created_by_id=user.id,
    )
    db.add(item)
    db.flush()
    add_machine_event(
        db,
        machine,
        user,
        "ATTACHMENT_ADDED",
        reference=str(item.id),
        details={"filename": filename, "kind": payload.kind},
    )
    add_audit_log(
        db,
        user,
        "machine_attachment",
        item.id,
        "Добавен файл към машината",
        {"machine_number": machine.inventory_number, "filename": filename, "sha256": item.sha256},
    )
    _commit(db)
    db.refresh(item)
    return _attachment_dict(item, "machine")


def download_machine_attachment(attachment_id: int, _: User, db: Session) -> Response:
    item = db.get(MachineAttachment, attachment_id)
    if item is None:
        raise HTTPException(404, "Файлът не е намерен.")
    return Response(
        item.content,
        media_type=item.media_type,
        headers={
            "Content-Disposition": f'attachment; filename="{item.filename}"',
            "X-Content-Type-Options": "nosniff",
        },
    )
