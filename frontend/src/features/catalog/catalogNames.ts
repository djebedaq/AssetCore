export type CatalogNameRecord = {
  description: string
  source_description?: string | null
  description_en: string
  description_bg: string
  description_ru?: string | null
  translation_version?: string
  original_name?: string | null
}

export function catalogDisplayName(record: CatalogNameRecord, locale: 'bg' | 'en' | 'ru' = 'bg'): string {
  if (record.translation_version === 'BUILDER') {
    return record[`description_${locale}`] || record.description
  }
  return `${record.description_en} / ${record.description_bg}`
}

export function catalogSourceDescription(record: CatalogNameRecord): string {
  return record.source_description || record.original_name || record.description
}
