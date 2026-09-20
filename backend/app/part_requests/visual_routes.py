"""Read-only historical evidence, scoped to its owning request line."""

import hashlib

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from ..database import get_db
from ..models import PartRequestLine, PartVisualArtifact, PartVisualSnapshot, User
from ..permissions import Permission, require_permission
from .visual_schemas import VisualReferenceOut
from .visual_snapshots import _integrity_error, snapshot_response

router = APIRouter()


def _line(db: Session, request_id: int, line_id: int) -> PartRequestLine:
    line = db.scalar(
        select(PartRequestLine)
        .options(
            selectinload(PartRequestLine.visual_snapshot).selectinload(
                PartVisualSnapshot.occurrences
            ),
        )
        .where(PartRequestLine.id == line_id, PartRequestLine.request_id == request_id)
    )
    if line is None:
        raise HTTPException(404, "Редът на заявката не е намерен.")
    return line


@router.get(
    "/part-requests/{request_id}/lines/{line_id}/visual-snapshot", response_model=VisualReferenceOut
)
def read_visual_snapshot(
    request_id: int,
    line_id: int,
    _: User = Depends(require_permission(Permission.REQUESTS_VIEW)),
    db: Session = Depends(get_db),
) -> dict:
    return snapshot_response(_line(db, request_id, line_id))


@router.get("/part-requests/{request_id}/lines/{line_id}/visual-snapshot/artifacts/{sha256}")
def download_visual_artifact(
    request_id: int,
    line_id: int,
    sha256: str,
    _: User = Depends(require_permission(Permission.REQUESTS_VIEW)),
    _document_viewer: User = Depends(require_permission(Permission.DOCUMENTS_VIEW)),
    db: Session = Depends(get_db),
) -> Response:
    result = snapshot_response(_line(db, request_id, line_id))["snapshot"]
    reference = (
        next(
            (value for value in result["visual_references"] if value["artifact_sha256"] == sha256),
            None,
        )
        if result
        else None
    )
    if reference is None:
        raise HTTPException(404, "Историческият източник не е намерен.")
    artifact = db.get(PartVisualArtifact, sha256)
    if artifact is None or hashlib.sha256(artifact.content).hexdigest() != sha256:
        raise _integrity_error()
    return Response(
        artifact.content,
        media_type=reference["source_metadata"]["media_type"],
        headers={
            "Content-Disposition": f'attachment; filename="visual-source-{sha256}"',
            "X-Content-Type-Options": "nosniff",
            "X-Content-SHA256": sha256,
            "Cache-Control": "private, no-store",
        },
    )
