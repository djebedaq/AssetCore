"""The official appendix consumes 01A snapshots on real PostgreSQL."""

import hashlib

import pytest
from app.documents.part_request_documents import make_part_request_documents
from app.industrial_api import create_multi_part_request
from app.industrial_schemas import MultiPartRequestCreate
from app.models import (
    GeneratedDocument,
    OfficialDocument,
    OfficialDocumentVersion,
    PartRequest,
    User,
)
from sqlalchemy import func, select
from test_concurrency import pg_factory as pg_factory  # noqa: F811
from visual_snapshot_cases import future_catalog, request_payload

pytestmark = pytest.mark.postgres


def test_pg_official_visual_document_and_failed_render_rollback(pg_factory, monkeypatch):
    data = future_catalog(pg_factory)
    with pg_factory() as db:
        created = create_multi_part_request(
            MultiPartRequestCreate.model_validate(request_payload(data)),
            db.get(User, data["actor_id"]),
            db,
        )
    request_id = created["id"]
    with pg_factory() as db:
        request = db.get(PartRequest, request_id)
        records = make_part_request_documents(db, request, data["actor_id"], "bg")
        db.add_all(records)
        db.commit()
        by_format = {record.format: record for record in records}
        assert by_format["docx"].snapshot["visual_appendix"]["lines"][0]["blocks"]
        official = db.scalar(
            select(OfficialDocument).where(
                OfficialDocument.document_number == request.request_reference
            )
        )
        version = db.get(OfficialDocumentVersion, official.current_version_id)
        assert version.docx_sha256 == hashlib.sha256(by_format["docx"].content).hexdigest()
        assert version.pdf_sha256 == hashlib.sha256(by_format["pdf"].content).hexdigest()
    with pg_factory() as db:
        second = create_multi_part_request(
            MultiPartRequestCreate.model_validate(request_payload(data)),
            db.get(User, data["actor_id"]),
            db,
        )
    from app.documents import part_request_grouped_visuals

    def fail(*_args, **_kwargs):
        raise RuntimeError("QA forced raster failure")

    monkeypatch.setattr(part_request_grouped_visuals, "_render_page", fail)
    with pg_factory() as db, pytest.raises(RuntimeError, match="QA forced raster"):
        make_part_request_documents(db, db.get(PartRequest, second["id"]), data["actor_id"])
        db.commit()
    with pg_factory() as db:
        assert (
            db.scalar(
                select(func.count())
                .select_from(GeneratedDocument)
                .where(GeneratedDocument.part_request_id == second["id"])
            )
            == 0
        )
        assert (
            db.scalar(
                select(func.count())
                .select_from(OfficialDocument)
                .where(OfficialDocument.document_number == second["request_reference"])
            )
            == 0
        )
