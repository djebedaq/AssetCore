import { ApiError } from '../../api'
import type { TranslationKey } from '../../i18n'

export function studioError(error: unknown): TranslationKey {
  if (!(error instanceof ApiError)) return 'studio.error'
  if (error.status === 409) return 'studio.conflict'
  if (error.code === 'studio_image_invalid' || error.code === 'studio_image_size') return 'studio.invalidImage'
  if (error.code === 'studio_docx_unsafe') return 'studio.invalidDocx'
  if (error.code === 'studio_required_block') return 'studio.requiredBlock'
  return error.status === 422 ? 'studio.invalid' : 'studio.error'
}

export type Identity = {
  legal_name: string; short_name: string; registration_number: string; vat_number: string;
  address: string; city: string; country: string; phone: string; email: string; website: string;
  primary_color: string; secondary_color: string; default_language: 'bg' | 'en' | 'ru'; timezone: string;
  primary_logo_id: number | null; secondary_logo_id: number | null; identity_image_ids: number[];
}
export type Profile = { revision: number; identity: Identity }
export type BrandImage = { id: number; purpose: 'PRIMARY' | 'SECONDARY' | 'IDENTITY'; width: number; height: number; download_endpoint: string }
export type StudioVersion = {
  id: number; version: number; language: 'bg' | 'en' | 'ru'; status: 'DRAFT' | 'PUBLISHED' | 'REFERENCE';
  validation_status: 'NOT_VALIDATED' | 'PASSED' | 'FAILED'; source_sha256: string | null;
  change_note: string | null; created_at: string; published_at: string | null; numbering_rule: string | null;
  source_filename: string | null; download_endpoint: string;
}
export type StudioTemplate = {
  id: number; code: string; document_type: string; name_bg: string; name_en: string | null; name_ru: string | null;
  authoring_supported: boolean; versions: StudioVersion[];
}
export type Draft = {
  id: number; template_id: number; base_version_id: number | null; language: string; title: string;
  revision: number; updated_at: string; status: 'DRAFT';
  layout: { schema_version: 1; positioning: 'flow'; page: { format: 'A4'; orientation: 'portrait' | 'landscape'; margin_mm: number };
    blocks: Array<{ id: string; type: string; field?: string; slot?: string }> };
}
