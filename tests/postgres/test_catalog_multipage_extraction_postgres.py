"""Multi-source extraction on migrated, isolated PostgreSQL QA schemas."""

import pytest
from app.catalog_admin import reference_pages, visual_sources
from app.catalog_admin.parts_extraction import service
from app.catalog_admin.parts_extraction.schemas import (
    ExtractConfirm,
    ExtractSelection,
    PageCreate,
    SourceAssign,
)
from app.models import CatalogRevisionPart, CatalogRevisionPartPageMap, User
from sqlalchemy import select
from test_catalog_builder_parts_postgres import setup
from test_catalog_multipage_extraction import multipage_pdf
from test_concurrency import pg_factory as pg_factory  # noqa: F811

pytestmark = pytest.mark.postgres


@pytest.mark.parametrize("count,headerless", [(2, False), (2, True), (3, True)])
def test_multisource_confirmation_and_exact_page_maps(pg_factory, count, headerless):
    assembly_id, _ = setup(pg_factory)
    with pg_factory() as db:
        actor = db.scalar(select(User).where(User.is_system_owner.is_(True)))
        artifact = visual_sources.store_artifact(db, actor, assembly_id, multipage_pdf(count=count, headerless=headerless), "qa-multipage.pdf", "Synthetic QA")
        page = reference_pages.create(db, actor, assembly_id, PageCreate())
        page = reference_pages.assign(db, actor, page["id"], SourceAssign(expected_version=page["version"], artifact_id=artifact["id"], page_numbers=[1], roles=["EXPLODED_SCHEME"]))
        page = reference_pages.assign(db, actor, page["id"], SourceAssign(expected_version=page["version"], artifact_id=artifact["id"], page_numbers=list(range(2, count + 2)), roles=["SPARE_PARTS_LIST"]))
        previews, previous = [], None
        for source in page["sources"]:
            if source["role"] != "SPARE_PARTS_LIST":
                continue
            result = service.preview(db, actor, page["id"], ExtractSelection(visual_page_id=source["id"], continuation_token=previous))
            assert len(result["rows"]) == 5
            previews.append(result)
            previous = result["token"]
        assert [row["payload"]["position"] for result in previews for row in result["rows"]] == [str(i) for i in range(1, count * 5 + 1)]
        for result in previews:
            data = ExtractConfirm(token=result["token"], rows=[{"index": i, "part": row["payload"]} for i, row in enumerate(result["rows"])], confirm_warnings=True)
            assert service.confirm(db, actor, page["id"], data)["created_count"] == 5
            assert service.confirm(db, actor, page["id"], data)["created_count"] == 0
        parts = list(db.scalars(select(CatalogRevisionPart).where(CatalogRevisionPart.reference_page_id == page["id"])))
        assert len(parts) == count * 5
        for part in parts:
            result = previews[(int(part.position) - 1) // 5]
            assert part.extraction_evidence["source"] == result["source"]
            assert part.extraction_evidence["row"] == result["rows"][(int(part.position) - 1) % 5]
            assert list(db.scalars(select(CatalogRevisionPartPageMap.visual_page_id).where(CatalogRevisionPartPageMap.part_id == part.id))) == [result["source"]["visual_page_id"]]
