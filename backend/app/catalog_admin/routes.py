"""Permissioned administration API for Builder workspaces."""

from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, Query, Response, UploadFile
from sqlalchemy.orm import Session

from ..catalog.references import ReferenceCreate, ReferenceRevoke
from ..database import get_db
from ..models import User
from ..permissions import Permission, require_permission
from . import (
    hotspots,
    parts,
    publication,
    repair_kits,
    repository,
    service,
    visual_sources,
    wizard,
    wizard_documents,
)
from .schemas import (
    ArtifactUpload,
    AssemblyCreate,
    AssemblyUpdate,
    CatalogCreate,
    CatalogUpdate,
    ClassifyDocumentPages,
    CloneRevision,
    HotspotCreate,
    HotspotUpdate,
    PartCreate,
    PartImportConfirm,
    PartImportPreview,
    PartPageMapCreate,
    PartUpdate,
    PublishRevision,
    RepairKitComponentCreate,
    RepairKitComponentUpdate,
    RepairKitCreate,
    RepairKitUpdate,
    RevisionCreate,
    RevisionUpdate,
    SimpleCatalogCreate,
    SimpleGroupCreate,
    VersionPrecondition,
    VisualPageCreate,
)

router = APIRouter(prefix="/api/admin/catalog-builder", tags=["catalog-builder"])
manager = require_permission(Permission.PARTS_MANAGE)


@router.get("/reference-sources")
def reference_sources(_: User = Depends(manager), db: Session = Depends(get_db)):
    from ..catalog.references import sources
    return sources(db)


@router.get("/reference-sources/{list_id}/parts")
def reference_parts(list_id: int, _: User = Depends(manager), db: Session = Depends(get_db)):
    from ..catalog.references import list_parts
    return list_parts(db, list_id)


@router.post("/reference-associations", status_code=201)
def create_reference(data: ReferenceCreate, actor: User = Depends(manager), db: Session = Depends(get_db)):
    from ..catalog.references import create
    return create(db, actor, data)


@router.post("/reference-associations/{association_id}/revoke")
def revoke_reference(association_id: int, data: ReferenceRevoke, actor: User = Depends(manager), db: Session = Depends(get_db)):
    from ..catalog.references import revoke
    return revoke(db, actor, association_id, data.reason)



@router.post("/simple/catalogs", status_code=201)
def create_simple_catalog(data: SimpleCatalogCreate, actor: User = Depends(manager),
                          db: Session = Depends(get_db)) -> dict:
    return wizard.create_catalog(db, actor, data)


@router.post("/catalogs/{catalog_id}/edit", status_code=201)
def edit_simple_catalog(catalog_id: int, actor: User = Depends(manager),
                        db: Session = Depends(get_db)) -> dict:
    return wizard.edit_catalog(db, actor, catalog_id)


@router.post("/revisions/{revision_id}/groups", status_code=201)
def create_simple_group(revision_id: int, data: SimpleGroupCreate, actor: User = Depends(manager),
                        db: Session = Depends(get_db)) -> dict:
    return wizard.create_group(db, actor, revision_id, data.name)


@router.get("/revisions/{revision_id}/documents")
def list_wizard_documents(revision_id: int, _: User = Depends(manager),
                          db: Session = Depends(get_db)) -> list[dict]:
    return wizard_documents.documents(db, revision_id)


@router.post("/revisions/{revision_id}/documents", status_code=201)
def upload_wizard_document(revision_id: int, data: ArtifactUpload, actor: User = Depends(manager),
                           db: Session = Depends(get_db)) -> dict:
    return wizard_documents.upload(db, actor, revision_id, data)


@router.post("/revisions/{revision_id}/pdf", status_code=201)
def upload_binary_document(revision_id: int, file: UploadFile = File(...),
                           title: str = Form(default="", max_length=255),
                           actor: User = Depends(manager), db: Session = Depends(get_db)) -> dict:
    from sqlalchemy import select

    from ..models import CatalogRevisionAssembly
    from . import source_storage

    visual_sources._revision(db, revision_id, mutate=True)
    group = db.scalar(select(CatalogRevisionAssembly).where(
        CatalogRevisionAssembly.revision_id == revision_id).order_by(CatalogRevisionAssembly.id).limit(1))
    try:
        content, digest = source_storage.read_upload(file.file)
        # Same SHA in this revision is an idempotent upload, including double-clicks.
        existing = db.scalar(select(visual_sources.CatalogRevisionArtifact).join(CatalogRevisionAssembly).where(
            CatalogRevisionAssembly.revision_id == revision_id,
            visual_sources.CatalogRevisionArtifact.sha256 == digest).order_by(visual_sources.CatalogRevisionArtifact.id))
        if existing:
            db.commit()
            return {**visual_sources._artifact_dict(existing), "duplicate": True}
        if group is None:
            raise service.fail("catalog_reference_required", 422)
        filename = file.filename or "source.pdf"
        return visual_sources.store_artifact(db, actor, group.id, content, filename, title or filename)
    except Exception:
        db.rollback()
        raise
    finally:
        file.file.close()


@router.get("/revisions/{revision_id}/workflow")
def simple_workflow_summary(revision_id: int, _: User = Depends(manager),
                            db: Session = Depends(get_db)) -> dict:
    return wizard.workflow(db, revision_id)


@router.post("/artifacts/{artifact_id}/classify")
def classify_document_pages(artifact_id: int, data: ClassifyDocumentPages, actor: User = Depends(manager),
                            db: Session = Depends(get_db)) -> list[dict]:
    return wizard_documents.classify(db, actor, artifact_id, data)


@router.get("/revisions/{revision_id}/parts/template")
def catalog_csv_template(revision_id: int, _: User = Depends(manager), db: Session = Depends(get_db)) -> Response:
    return Response(wizard.csv_template(db, revision_id), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": 'attachment; filename="catalog-parts.csv"'})


@router.post("/revisions/{revision_id}/parts/import-preview")
def catalog_import_preview(revision_id: int, data: PartImportPreview, actor: User = Depends(manager),
                           db: Session = Depends(get_db)) -> dict:
    return wizard.import_preview(db, actor, revision_id, data)


@router.post("/revisions/{revision_id}/parts/import-confirm")
def catalog_import_confirm(revision_id: int, data: PartImportConfirm, actor: User = Depends(manager),
                           db: Session = Depends(get_db)) -> dict:
    return wizard.import_confirm(db, actor, revision_id, data.token, data.confirm_warnings)


@router.get("/catalogs")
def list_catalogs(_: User = Depends(manager), db: Session = Depends(get_db)) -> list[dict]:
    return repository.catalogs(db)


@router.post("/catalogs", status_code=201)
def create_catalog(data: CatalogCreate, actor: User = Depends(manager), db: Session = Depends(get_db)) -> dict:
    return service.create_catalog(db, actor, data)


@router.get("/catalogs/{catalog_id}")
def get_catalog(catalog_id: int, _: User = Depends(manager), db: Session = Depends(get_db)) -> dict:
    return service.catalog_dict(db, service.catalog(db, catalog_id))


@router.patch("/catalogs/{catalog_id}")
def update_catalog(catalog_id: int, data: CatalogUpdate, actor: User = Depends(manager),
                   db: Session = Depends(get_db)) -> dict:
    return service.update_catalog(db, actor, catalog_id, data)


@router.get("/catalogs/{catalog_id}/revisions")
def list_revisions(catalog_id: int, _: User = Depends(manager), db: Session = Depends(get_db)) -> list[dict]:
    return service.revisions(db, catalog_id)


@router.post("/catalogs/{catalog_id}/revisions", status_code=201)
def create_revision(catalog_id: int, data: RevisionCreate, actor: User = Depends(manager),
                    db: Session = Depends(get_db)) -> dict:
    return service.create_revision(db, actor, catalog_id, data)


@router.patch("/revisions/{revision_id}")
def update_revision(revision_id: int, data: RevisionUpdate, actor: User = Depends(manager),
                    db: Session = Depends(get_db)) -> dict:
    return service.update_revision(db, actor, revision_id, data)


@router.get("/revisions/{revision_id}/publication-readiness")
def publication_readiness(revision_id: int, _: User = Depends(manager),
                          db: Session = Depends(get_db)) -> dict:
    return publication.readiness(db, revision_id)


@router.post("/revisions/{revision_id}/publish")
def publish_revision(revision_id: int, data: PublishRevision,
                     actor: User = Depends(manager), db: Session = Depends(get_db)) -> dict:
    return publication.publish(db, actor, revision_id, data.expected_publication_digest,
                               data.expected_current_published_revision_id, data.confirmed)


@router.post("/revisions/{revision_id}/clone", status_code=201)
def clone_revision(revision_id: int, data: CloneRevision,
                   actor: User = Depends(manager), db: Session = Depends(get_db)) -> dict:
    return publication.clone(db, actor, revision_id, data.revision_code, data.change_note)


@router.get("/catalogs/{catalog_id}/assets")
def list_assets(catalog_id: int, _: User = Depends(manager), db: Session = Depends(get_db)) -> list[dict]:
    service.catalog(db, catalog_id)
    return repository.assets(db, catalog_id)


@router.get("/catalogs/{catalog_id}/eligible-assets")
def eligible_assets(catalog_id: int, search: str | None = Query(default=None, max_length=120),
                    _: User = Depends(manager), db: Session = Depends(get_db)) -> list[dict]:
    return service.eligible_assets(db, catalog_id, search)


@router.post("/catalogs/{catalog_id}/assets/{machine_id}", status_code=201)
def bind_asset(catalog_id: int, machine_id: int, actor: User = Depends(manager),
               db: Session = Depends(get_db)) -> dict:
    return service.bind_asset(db, actor, catalog_id, machine_id)


@router.delete("/catalogs/{catalog_id}/assets/{machine_id}", status_code=204)
def unbind_asset(catalog_id: int, machine_id: int, actor: User = Depends(manager),
                 db: Session = Depends(get_db)) -> Response:
    service.unbind_asset(db, actor, catalog_id, machine_id)
    return Response(status_code=204)


@router.get("/revisions/{revision_id}/assemblies")
def list_assemblies(revision_id: int, _: User = Depends(manager), db: Session = Depends(get_db)) -> list[dict]:
    return visual_sources.list_assemblies(db, revision_id)


@router.post("/revisions/{revision_id}/assemblies", status_code=201)
def create_assembly(revision_id: int, data: AssemblyCreate, actor: User = Depends(manager),
                    db: Session = Depends(get_db)) -> dict:
    return visual_sources.create_assembly(db, actor, revision_id, data)


@router.patch("/assemblies/{assembly_id}")
def update_assembly(assembly_id: int, data: AssemblyUpdate, actor: User = Depends(manager),
                    db: Session = Depends(get_db)) -> dict:
    return visual_sources.update_assembly(db, actor, assembly_id, data)


@router.delete("/assemblies/{assembly_id}", status_code=204)
def delete_assembly(assembly_id: int, actor: User = Depends(manager), db: Session = Depends(get_db)) -> Response:
    visual_sources.delete_assembly(db, actor, assembly_id)
    return Response(status_code=204)


@router.get("/assemblies/{assembly_id}/artifacts")
def list_artifacts(assembly_id: int, _: User = Depends(manager), db: Session = Depends(get_db)) -> list[dict]:
    return visual_sources.list_artifacts(db, assembly_id)


@router.post("/assemblies/{assembly_id}/artifacts", status_code=201)
def upload_artifact(assembly_id: int, data: ArtifactUpload, actor: User = Depends(manager),
                    db: Session = Depends(get_db)) -> dict:
    return visual_sources.upload_artifact(db, actor, assembly_id, data)


@router.get("/artifacts/{artifact_id}")
def get_artifact(artifact_id: int, _: User = Depends(manager), db: Session = Depends(get_db)) -> dict:
    return visual_sources.get_artifact(db, artifact_id)


@router.delete("/artifacts/{artifact_id}", status_code=204)
def delete_artifact(artifact_id: int, actor: User = Depends(manager), db: Session = Depends(get_db)) -> Response:
    visual_sources.delete_artifact(db, actor, artifact_id)
    return Response(status_code=204)


@router.get("/artifacts/{artifact_id}/download")
def download_artifact(artifact_id: int, _: User = Depends(manager), db: Session = Depends(get_db)) -> Response:
    content, filename = visual_sources.download_artifact(db, artifact_id)
    return Response(content, media_type="application/pdf",
                    headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff",
                             "Content-Disposition": "attachment; filename=\"catalog-source.pdf\"; "
                             f"filename*=UTF-8''{quote(filename, safe='')}"})


@router.get("/artifacts/{artifact_id}/pages/{page_number}/preview")
def preview_artifact_page(artifact_id: int, page_number: int, thumbnail: bool = False, _: User = Depends(manager),
                          db: Session = Depends(get_db)) -> Response:
    return Response(visual_sources.preview_page(db, artifact_id, page_number, thumbnail=thumbnail), media_type="image/png",
                    headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"})


@router.get("/artifacts/{artifact_id}/visual-pages")
def list_visual_pages(artifact_id: int, _: User = Depends(manager), db: Session = Depends(get_db)) -> list[dict]:
    return visual_sources.list_visual_pages(db, artifact_id)


@router.post("/artifacts/{artifact_id}/visual-pages", status_code=201)
def assign_visual_pages(artifact_id: int, data: VisualPageCreate, actor: User = Depends(manager),
                        db: Session = Depends(get_db)) -> list[dict]:
    return visual_sources.assign_visual_pages(db, actor, artifact_id, data)


@router.delete("/visual-pages/{assignment_id}", status_code=204)
def remove_visual_page(assignment_id: int, actor: User = Depends(manager),
                       db: Session = Depends(get_db)) -> Response:
    visual_sources.remove_visual_page(db, actor, assignment_id)
    return Response(status_code=204)


@router.get("/assemblies/{assembly_id}/parts")
def list_parts(assembly_id: int, _: User = Depends(manager), db: Session = Depends(get_db)) -> list[dict]:
    return parts.list_parts(db, assembly_id)


@router.post("/assemblies/{assembly_id}/parts", status_code=201)
def create_part(assembly_id: int, data: PartCreate, actor: User = Depends(manager),
                db: Session = Depends(get_db)) -> dict:
    return parts.create_part(db, actor, assembly_id, data)


@router.get("/parts/{part_id}")
def get_part(part_id: int, _: User = Depends(manager), db: Session = Depends(get_db)) -> dict:
    return parts.get_part(db, part_id)


@router.patch("/parts/{part_id}")
def update_part(part_id: int, data: PartUpdate, actor: User = Depends(manager),
                db: Session = Depends(get_db)) -> dict:
    return parts.update_part(db, actor, part_id, data)


@router.delete("/parts/{part_id}", status_code=204)
def delete_part(part_id: int, actor: User = Depends(manager), db: Session = Depends(get_db)) -> Response:
    parts.delete_part(db, actor, part_id)
    return Response(status_code=204)


@router.get("/assemblies/{assembly_id}/spare-list-pages")
def spare_list_pages(assembly_id: int, _: User = Depends(manager), db: Session = Depends(get_db)) -> list[dict]:
    return parts.spare_list_pages(db, assembly_id)


@router.get("/parts/{part_id}/source-pages")
def list_part_pages(part_id: int, _: User = Depends(manager), db: Session = Depends(get_db)) -> list[dict]:
    return parts.list_mappings(db, part_id)


@router.post("/parts/{part_id}/source-pages", status_code=201)
def map_part_pages(part_id: int, data: PartPageMapCreate, actor: User = Depends(manager),
                   db: Session = Depends(get_db)) -> list[dict]:
    return parts.map_pages(db, actor, part_id, data)


@router.delete("/part-page-maps/{mapping_id}", status_code=204)
def unmap_part_page(mapping_id: int, actor: User = Depends(manager), db: Session = Depends(get_db)) -> Response:
    parts.unmap_page(db, actor, mapping_id)
    return Response(status_code=204)


@router.post("/assemblies/{assembly_id}/parts/import-preview")
def import_parts_preview(assembly_id: int, data: PartImportPreview, actor: User = Depends(manager),
                         db: Session = Depends(get_db)) -> dict:
    return parts.import_preview(db, actor, assembly_id, data)


@router.post("/assemblies/{assembly_id}/parts/import-confirm")
def import_parts_confirm(assembly_id: int, data: PartImportConfirm, actor: User = Depends(manager),
                         db: Session = Depends(get_db)) -> dict:
    return parts.import_confirm(db, actor, assembly_id, data.token, data.confirm_warnings)


@router.get("/assemblies/{assembly_id}/exploded-pages")
def exploded_pages(assembly_id: int, _: User = Depends(manager), db: Session = Depends(get_db)) -> list[dict]:
    return hotspots.exploded_pages(db, assembly_id)


@router.get("/assemblies/{assembly_id}/hotspot-coverage")
def hotspot_coverage(assembly_id: int, _: User = Depends(manager), db: Session = Depends(get_db)) -> list[dict]:
    return hotspots.coverage(db, assembly_id)


@router.get("/visual-pages/{visual_page_id}/hotspots")
def list_hotspots(visual_page_id: int, _: User = Depends(manager), db: Session = Depends(get_db)) -> list[dict]:
    return hotspots.list_hotspots(db, visual_page_id)


@router.post("/visual-pages/{visual_page_id}/hotspots", status_code=201)
def create_hotspot(visual_page_id: int, data: HotspotCreate, actor: User = Depends(manager),
                   db: Session = Depends(get_db)) -> dict:
    return hotspots.create_hotspot(db, actor, visual_page_id, data)


@router.patch("/hotspots/{hotspot_id}")
def update_hotspot(hotspot_id: int, data: HotspotUpdate, actor: User = Depends(manager),
                   db: Session = Depends(get_db)) -> dict:
    return hotspots.update_hotspot(db, actor, hotspot_id, data)


@router.post("/hotspots/{hotspot_id}/verify")
def verify_hotspot(hotspot_id: int, data: VersionPrecondition, actor: User = Depends(manager),
                   db: Session = Depends(get_db)) -> dict:
    return hotspots.set_verified(db, actor, hotspot_id, data.expected_version, True)


@router.post("/hotspots/{hotspot_id}/unverify")
def unverify_hotspot(hotspot_id: int, data: VersionPrecondition, actor: User = Depends(manager),
                     db: Session = Depends(get_db)) -> dict:
    return hotspots.set_verified(db, actor, hotspot_id, data.expected_version, False)


@router.delete("/hotspots/{hotspot_id}", status_code=204)
def delete_hotspot(hotspot_id: int, expected_version: int = Query(ge=1),
                   actor: User = Depends(manager), db: Session = Depends(get_db)) -> Response:
    hotspots.delete_hotspot(db, actor, hotspot_id, expected_version)
    return Response(status_code=204)


@router.get("/assemblies/{assembly_id}/repair-kits")
def list_repair_kits(assembly_id: int, _: User = Depends(manager), db: Session = Depends(get_db)) -> list[dict]:
    return repair_kits.list_kits(db, assembly_id)


@router.post("/assemblies/{assembly_id}/repair-kits", status_code=201)
def create_repair_kit(assembly_id: int, data: RepairKitCreate, actor: User = Depends(manager),
                      db: Session = Depends(get_db)) -> dict:
    return repair_kits.create_kit(db, actor, assembly_id, data)


@router.get("/repair-kits/{kit_id}")
def get_repair_kit(kit_id: int, _: User = Depends(manager), db: Session = Depends(get_db)) -> dict:
    return repair_kits.get_kit(db, kit_id)


@router.patch("/repair-kits/{kit_id}")
def update_repair_kit(kit_id: int, data: RepairKitUpdate, actor: User = Depends(manager),
                      db: Session = Depends(get_db)) -> dict:
    return repair_kits.update_kit(db, actor, kit_id, data)


@router.delete("/repair-kits/{kit_id}", status_code=204)
def delete_repair_kit(kit_id: int, expected_version: int = Query(ge=1),
                      actor: User = Depends(manager), db: Session = Depends(get_db)) -> Response:
    repair_kits.delete_kit(db, actor, kit_id, expected_version)
    return Response(status_code=204)


@router.post("/repair-kits/{kit_id}/components", status_code=201)
def add_repair_kit_component(kit_id: int, data: RepairKitComponentCreate, actor: User = Depends(manager),
                             db: Session = Depends(get_db)) -> dict:
    return repair_kits.add_component(db, actor, kit_id, data)


@router.patch("/repair-kit-components/{component_id}")
def update_repair_kit_component(component_id: int, data: RepairKitComponentUpdate,
                                actor: User = Depends(manager), db: Session = Depends(get_db)) -> dict:
    return repair_kits.update_component(db, actor, component_id, data)


@router.delete("/repair-kit-components/{component_id}", status_code=204)
def remove_repair_kit_component(component_id: int, expected_version: int = Query(ge=1),
                                actor: User = Depends(manager), db: Session = Depends(get_db)) -> Response:
    repair_kits.remove_component(db, actor, component_id, expected_version)
    return Response(status_code=204)
