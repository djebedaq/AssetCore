import type { TranslationKey } from '../../i18n'

export const builderBase = '/admin/catalog-builder'
export type Step = 'catalog' | 'references' | 'documents' | 'parts' | 'hotspots' | 'review'
export const steps: Step[] = ['catalog', 'references', 'documents', 'parts', 'hotspots', 'review']
export type Names = { name_bg: string; name_en: string; name_ru: string }
export type Category = Names & { id: number; code: string; is_active: boolean; capabilities: string[] }
export type Catalog = Names & { id: number; code: string; asset_category_id: number; asset_category: Category;
  manufacturer: string | null; model_reference: string | null; is_active: boolean;
  published_revision: { id: number; revision_code: string } | null; draft_revision_count: number }
export type Revision = { id: number; revision_code: string; status: 'DRAFT' | 'PUBLISHED' | 'RETIRED'; created_at: string }
export type Group = Names & { id: number; code: string; part_count: number; exploded_page_count: number; spare_list_page_count: number;
  artifact_count?: number; hotspot_count?: number; repair_kit_count?: number; repair_kit_component_count?: number }
export type Document = { id: number; filename: string; title: string; sha256: string; page_count: number;
  artifact_ids?: number[];
  assignments: Array<{ id: number; artifact_id: number; page_number: number; assembly_id: number; role: Role }> }
export type Role = 'EXPLODED_SCHEME' | 'SPARE_PARTS_LIST'
export type Issue = { code: string; step?: Step | 'kits'; assembly_id?: number; part_id?: number; reference_page_id?: number;
  visual_page_id?: number; position?: string; artifact_id?: number; missing_positions?: number }
export type Workflow = { ready: boolean; publication_digest: string; current_published_revision_id: number | null;
  errors: Issue[]; warnings: Issue[]; summary: Record<string, number>;
  progress: { position_count: number; completed_positions: number }; resume_step: Step }

export const problemKeys: Record<string, TranslationKey> = {
  catalog_publication_reference_page_incomplete: 'guided.incomplete',
  catalog_reference_page_stale: 'guided.stale', catalog_reference_page_in_use: 'guided.inUse',
  catalog_invalid_update: 'builder.error.invalid', catalog_category_not_supported: 'builder.error.capability',
  catalog_category_inactive: 'builder.error.category', catalog_code_duplicate: 'builder.error.duplicate',
  catalog_source_invalid_pdf: 'builder.error.invalidPdf', catalog_source_too_large: 'builder.error.tooLarge',
  catalog_source_duplicate: 'builder.error.sourceDuplicate', catalog_wizard_page_in_use: 'wizard.pageInUse',
  catalog_visual_page_invalid: 'builder.error.pageInvalid', catalog_visual_page_duplicate: 'builder.error.pageDuplicate',
  catalog_revision_not_draft: 'builder.error.revisionImmutable', catalog_inactive: 'builder.error.inactive',
  catalog_import_group_missing: 'wizard.csvGroupMissing', catalog_part_invalid: 'builder.part.error.invalid',
  catalog_import_template_row: 'wizard.csvTemplateRow',
  catalog_category_in_use: 'wizard.categoryLocked',
  catalog_publication_empty_assembly: 'wizard.emptyGroup',
  catalog_part_import_duplicate_row: 'builder.part.error.duplicate', catalog_part_duplicate: 'builder.part.error.duplicate',
  catalog_part_import_page_required: 'builder.part.error.page', catalog_part_import_page_invalid: 'builder.part.error.page',
  catalog_part_import_page_missing: 'builder.part.error.page', catalog_part_import_page_ambiguous: 'builder.part.error.ambiguous',
  catalog_part_import_sha_invalid: 'builder.part.error.page', catalog_part_import_unmapped: 'builder.part.warning.unmapped',
  catalog_part_import_invalid_file: 'builder.part.error.file', catalog_part_import_conflict: 'builder.part.error.conflict',
  catalog_part_import_token_invalid: 'builder.part.error.token', catalog_part_import_warning_confirmation: 'builder.part.error.warningConfirm',
  catalog_publication_stale: 'builder.publication.stale', catalog_publication_not_ready: 'builder.publication.notReady',
  catalog_publication_conflict: 'builder.publication.conflict', catalog_clone_invalid: 'builder.publication.cloneInvalid',
  catalog_publication_no_assemblies: 'builder.publication.noAssemblies',
  catalog_publication_source_invalid: 'builder.publication.sourceInvalid',
  catalog_publication_visual_page_invalid: 'builder.publication.pageInvalid',
  catalog_publication_part_mapping_invalid: 'builder.publication.mappingInvalid',
  catalog_publication_part_incomplete: 'builder.publication.partIncomplete',
  catalog_publication_hotspot_invalid: 'builder.publication.hotspotInvalid',
  catalog_publication_hotspot_unverified: 'builder.publication.hotspotUnverified',
  catalog_publication_hotspot_coverage: 'builder.publication.hotspotCoverage',
  catalog_publication_kit_incomplete: 'builder.publication.kitIncomplete',
  catalog_asset_category_mismatch: 'builder.error.assetCategory', catalog_asset_already_bound: 'builder.error.assetBound',
  catalog_asset_binding_protected: 'builder.error.assetProtected',
}
