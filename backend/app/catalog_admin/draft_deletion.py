"""Catalog-locked, previewable deletion of owned draft data only.

Audit entries and referenced source blobs are independent and are never removed.
Any FK outside this explicit ownership graph is a protected dependency.
"""

import hashlib
import json

from fastapi import HTTPException
from sqlalchemy import delete, or_, select

from ..audit import add_audit_log
from ..database import Base
from ..models import (
    CatalogAssetBinding as Binding,
)
from ..models import (
    CatalogDefinition as Catalog,
)
from ..models import (
    CatalogExtractionAttempt as Attempt,
)
from ..models import (
    CatalogExtractionCandidate as Candidate,
)
from ..models import (
    CatalogExtractionSession as Extraction,
)
from ..models import (
    CatalogExtractionSource as Source,
)
from ..models import (
    CatalogRevision as Revision,
)
from ..models import (
    CatalogRevisionArtifact as Artifact,
)
from ..models import (
    CatalogRevisionAssembly as Assembly,
)
from ..models import (
    CatalogRevisionPart as Part,
)
from ..models import (
    CatalogRevisionPartPageMap as Mapping,
)
from ..models import (
    CatalogRevisionPositionHotspot as Hotspot,
)
from ..models import (
    CatalogRevisionReferencePage as Group,
)
from ..models import (
    CatalogRevisionRepairKit as Kit,
)
from ..models import (
    CatalogRevisionRepairKitComponent as Component,
)
from ..models import (
    CatalogRevisionVisualPage as Page,
)
from ..models import CatalogSourceBlob as Blob
from ..models import (
    CatalogSourceReviewDecision as Decision,
)
from . import visual_sources
from .service import fail

KINDS = {
    "catalog": Catalog,
    "revision": Revision,
    "assembly": Assembly,
    "group": Group,
    "document": Artifact,
    "source": Page,
    "part": Part,
    "hotspot": Hotspot,
    "kit": Kit,
}


def plan(db, kind, identity):
    model = KINDS.get(kind)
    if model is None:
        raise fail("catalog_delete_kind_invalid", 422)
    root = db.get(model, identity)
    if root is None:
        raise fail("catalog_delete_not_found", 404)
    if kind == "catalog":
        catalog_id = root.id
    elif kind == "revision":
        catalog_id = root.catalog_id
    else:
        if kind == "source":
            assembly_id = db.get(Artifact, root.artifact_id).assembly_id
        elif kind == "hotspot":
            assembly_id = db.get(
                Artifact, db.get(Page, root.visual_page_id).artifact_id
            ).assembly_id
        elif kind == "assembly":
            assembly_id = root.id
        else:
            assembly_id = root.assembly_id
        catalog_id = db.get(Revision, db.get(Assembly, assembly_id).revision_id).catalog_id
    catalog = visual_sources.lock_catalog(db, catalog_id)
    # Re-read after waiting on the authoritative catalog lock.
    root = db.get(model, identity)
    if root is None or catalog is None:
        raise fail("catalog_delete_not_found", 404)
    revision_ids = (
        list(db.scalars(select(Revision.id).where(Revision.catalog_id == catalog_id)))
        if kind == "catalog"
        else [root.id if kind == "revision" else db.get(Assembly, assembly_id).revision_id]
    )
    if any(
        row.status != "DRAFT" or row.published_at is not None
        for row in db.scalars(select(Revision).where(Revision.id.in_(revision_ids)))
    ):
        raise fail("catalog_delete_published_protected")
    owned = {table.name: set() for table in Base.metadata.tables.values()}

    def put(cls, ids):
        owned[cls.__tablename__].update(ids)

    def ids(cls):
        return owned[cls.__tablename__]

    def find(cls, condition):
        return set(db.scalars(select(cls.id).where(condition)))

    put(model, [identity])
    if kind == "catalog":
        put(Revision, revision_ids)
        put(Binding, find(Binding, Binding.catalog_id == catalog_id))
    if kind in {"catalog", "revision"}:
        put(Assembly, find(Assembly, Assembly.revision_id.in_(ids(Revision))))
    if ids(Assembly):
        put(Group, find(Group, Group.assembly_id.in_(ids(Assembly))))
        put(Artifact, find(Artifact, Artifact.assembly_id.in_(ids(Assembly))))
        put(Part, find(Part, Part.assembly_id.in_(ids(Assembly))))
        put(Kit, find(Kit, Kit.assembly_id.in_(ids(Assembly))))
    put(
        Page,
        find(
            Page, or_(Page.artifact_id.in_(ids(Artifact)), Page.reference_page_id.in_(ids(Group)))
        ),
    )
    put(Part, find(Part, Part.reference_page_id.in_(ids(Group))))
    # Removing a list owns its exclusively mapped parts. Multi-page occurrences
    # with a surviving source retain their identity and lose only this mapping.
    put(
        Part,
        find(
            Part,
            Part.id.in_(select(Mapping.part_id).where(Mapping.visual_page_id.in_(ids(Page))))
            & ~Part.id.in_(select(Mapping.part_id).where(~Mapping.visual_page_id.in_(ids(Page)))),
        ),
    )
    scoped_assemblies = (
        ids(Assembly)
        | set(db.scalars(select(Artifact.assembly_id).join(Page).where(Page.id.in_(ids(Page)))))
        | set(db.scalars(select(Part.assembly_id).where(Part.id.in_(ids(Part)))))
    )
    put(
        Kit,
        find(
            Kit, Kit.source_visual_page_id.in_(ids(Page)) & Kit.assembly_id.in_(scoped_assemblies)
        ),
    )
    put(
        Component,
        find(
            Component,
            or_(
                Component.kit_id.in_(ids(Kit)),
                Component.part_id.in_(ids(Part))
                & Component.kit_id.in_(
                    select(Kit.id).where(Kit.assembly_id.in_(scoped_assemblies))
                ),
            ),
        ),
    )
    put(
        Mapping,
        find(Mapping, or_(Mapping.part_id.in_(ids(Part)), Mapping.visual_page_id.in_(ids(Page)))),
    )
    put(Hotspot, find(Hotspot, Hotspot.visual_page_id.in_(ids(Page))))
    # Remove markers only when the last local variant of a deleted part goes.
    for part in db.scalars(select(Part).where(Part.id.in_(ids(Part)))):
        remaining = db.scalar(
            select(Part.id)
            .where(
                Part.assembly_id == part.assembly_id,
                Part.reference_page_id == part.reference_page_id,
                Part.position == part.position,
                ~Part.id.in_(ids(Part)),
            )
            .limit(1)
        )
        if remaining is None:
            local_pages = (
                select(Page.id)
                .join(Artifact)
                .where(
                    Artifact.assembly_id == part.assembly_id,
                    Page.reference_page_id == part.reference_page_id,
                )
            )
            put(
                Hotspot,
                find(
                    Hotspot,
                    Hotspot.visual_page_id.in_(local_pages) & (Hotspot.position == part.position),
                ),
            )
    put(
        Extraction,
        find(
            Extraction,
            Extraction.revision_id.in_(revision_ids)
            & or_(
                Extraction.revision_id.in_(ids(Revision)),
                Extraction.assembly_id.in_(ids(Assembly)),
                Extraction.reference_page_id.in_(ids(Group)),
            ),
        ),
    )
    put(
        Source,
        find(
            Source,
            or_(
                Source.session_id.in_(ids(Extraction)),
                Source.visual_page_id.in_(ids(Page))
                & Source.session_id.in_(
                    select(Extraction.id).where(Extraction.revision_id.in_(revision_ids))
                ),
            ),
        ),
    )
    put(Attempt, find(Attempt, Attempt.source_id.in_(ids(Source))))
    put(Candidate, find(Candidate, Candidate.source_id.in_(ids(Source))))
    put(Decision, find(Decision, Decision.source_id.in_(ids(Source))))
    # Shared originals have independent ownership. Lock candidate blobs and
    # collect only those with no surviving reference anywhere in the schema.
    blob_ids = set(
        db.scalars(select(Artifact.source_blob_id).where(Artifact.id.in_(ids(Artifact))))
    )
    blob_ids.update(db.scalars(select(Source.source_blob_id).where(Source.id.in_(ids(Source)))))
    blob_ids.discard(None)
    for blob in db.scalars(
        select(Blob).where(Blob.id.in_(blob_ids)).order_by(Blob.id).with_for_update()
    ):
        shared = any(
            db.scalar(
                select(table.c.id)
                .where(fk.parent == blob.id, ~table.c.id.in_(owned[table.name]))
                .limit(1)
            )
            is not None
            for table in Base.metadata.tables.values()
            for fk in table.foreign_keys
            if fk.column.table.name == Blob.__tablename__
        )
        if not shared:
            put(Blob, [blob.id])
    # Scope records are temporary too when their final source is removed.
    put(
        Extraction,
        find(
            Extraction,
            Extraction.id.in_(select(Source.session_id).where(Source.id.in_(ids(Source))))
            & ~Extraction.id.in_(select(Source.session_id).where(~Source.id.in_(ids(Source)))),
        ),
    )
    blockers = []
    for table in Base.metadata.tables.values():
        for fk in table.foreign_keys:
            targets = owned.get(fk.column.table.name)
            if targets:
                found = (
                    set(db.scalars(select(table.c.id).where(fk.parent.in_(targets))))
                    - owned[table.name]
                )
                if found:
                    blockers.append(
                        {
                            "table": table.name,
                            "field": fk.parent.name,
                            "count": len(found),
                            "record_ids": sorted(found),
                        }
                    )
    # Include row values, not only counts, in optimistic concurrency evidence.
    snapshot = {}
    for table in Base.metadata.tables.values():
        if owned[table.name]:
            columns = [column for column in table.c if column.type.python_type is not bytes]
            snapshot[table.name] = [
                dict(row)
                for row in db.execute(
                    select(*columns).where(table.c.id.in_(owned[table.name])).order_by(table.c.id)
                ).mappings()
            ]
    digest = hashlib.sha256(
        json.dumps(
            {"kind": kind, "id": identity, "rows": snapshot, "blockers": blockers},
            sort_keys=True,
            default=str,
        ).encode()
    ).hexdigest()
    return (
        {
            "kind": kind,
            "id": identity,
            "catalog_id": catalog.id,
            "catalog_code": catalog.code,
            "digest": digest,
            "counts": {name: len(values) for name, values in owned.items() if values},
            "blockers": blockers,
        },
        owned,
        revision_ids,
    )


def preview(db, kind, identity):
    return plan(db, kind, identity)[0]


def remove(db, actor, kind, identity, expected_digest=None):
    try:
        summary, owned, revision_ids = plan(db, kind, identity)
    except HTTPException as error:
        if expected_digest is not None and error.status_code == 404:
            raise fail("catalog_delete_stale") from None
        raise
    if summary["blockers"]:
        raise HTTPException(
            409,
            detail={
                "code": "catalog_delete_protected_dependency",
                "dependencies": summary["blockers"],
            },
        )
    if expected_digest is not None and expected_digest != summary["digest"]:
        raise fail("catalog_delete_stale")
    # Invalidate surviving review evidence before altering local parts/maps.
    from .parts_extraction import ledger

    for candidate in db.scalars(
        select(Candidate)
        .join(Source)
        .join(Extraction)
        .where(
            Candidate.part_id.in_(owned[Part.__tablename__]),
            ~Candidate.id.in_(owned[Candidate.__tablename__]),
            Extraction.revision_id.in_(revision_ids),
        )
    ):
        candidate.state, candidate.reason = "CONFLICT", "ACCEPTED_PART_REMOVED"
        candidate.part_id, candidate.part_created_at = None, None
        candidate.version += 1
    affected = set(
        db.execute(
            select(Part.assembly_id, Part.reference_page_id).where(
                Part.id.in_(owned[Part.__tablename__])
            )
        ).all()
    )
    affected.update(
        db.execute(
            select(Artifact.assembly_id, Page.reference_page_id)
            .join(Page)
            .where(Page.id.in_(owned[Page.__tablename__]))
        ).all()
    )
    for source in db.scalars(
        select(Source)
        .join(Extraction)
        .where(
            Extraction.revision_id.in_(revision_ids), ~Source.id.in_(owned[Source.__tablename__])
        )
    ):
        session = db.get(Extraction, source.session_id)
        if (session.assembly_id, session.reference_page_id) in affected:
            ledger.invalidate(source)
    for page in db.scalars(
        select(Group)
        .join(Assembly)
        .where(Assembly.revision_id.in_(revision_ids), ~Group.id.in_(owned[Group.__tablename__]))
    ):
        if (page.assembly_id, page.id) in affected:
            from .reference_pages import touch

            touch(page)
    db.flush()
    for kit in db.scalars(
        select(Kit).where(
            ~Kit.id.in_(owned[Kit.__tablename__]),
            Kit.id.in_(
                select(Component.kit_id).where(Component.id.in_(owned[Component.__tablename__]))
            ),
        )
    ):
        kit.version += 1
    db.flush()
    # All children first; every deleted table is part of the explicit draft graph.
    for model in [
        Decision,
        Candidate,
        Attempt,
        Source,
        Extraction,
        Component,
        Kit,
        Hotspot,
        Mapping,
        Part,
        Page,
        Group,
        Artifact,
        Assembly,
        Revision,
        Binding,
        Catalog,
        Blob,
    ]:
        table = model.__table__
        if owned[table.name]:
            db.execute(delete(table).where(table.c.id.in_(owned[table.name])))
    add_audit_log(db, actor, "catalog_draft_deletion", identity, "CATALOG_DRAFT_DELETED", summary)
    db.commit()
