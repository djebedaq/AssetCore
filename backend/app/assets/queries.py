"""Existing asset relationship queries; transfer mutation remains in transfer_service."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import TransferProtocol


def _active_transfer(db: Session, machine_id: int) -> TransferProtocol | None:
    return db.scalar(
        select(TransferProtocol).where(
            TransferProtocol.machine_id == machine_id,
            TransferProtocol.is_active.is_(True),
        )
    )
