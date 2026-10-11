import { ApiError } from '../../api'
import type { TranslationKey } from '../../i18n'

const messages: Record<string, TranslationKey> = {
  catalog_source_correction_review_required: 'guided.correctionRequired',
  catalog_source_review_incomplete: 'guided.reviewIncomplete', catalog_extraction_candidate_unresolved: 'guided.rowConflict',
  catalog_source_review_inspection_required: 'guided.inspectionRequired', catalog_source_review_manual_required: 'guided.manualRequired',
  catalog_reference_page_stale: 'guided.stale', catalog_reference_page_in_use: 'guided.inUse',
  catalog_wizard_page_in_use: 'guided.inUse', catalog_repair_kit_source_page_in_use: 'guided.inUse',
  catalog_extraction_token_invalid: 'guided.previewExpired', catalog_extraction_busy: 'guided.busyError',
  catalog_extraction_mapping_invalid: 'guided.mappingInvalid',
}
export function guidedError(error: unknown): TranslationKey {
  return error instanceof ApiError && error.code ? messages[error.code] || 'guided.error' : 'guided.error'
}
