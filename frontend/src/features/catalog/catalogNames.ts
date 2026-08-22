export type CatalogNameRecord = {
  description: string
  source_description?: string | null
  description_en: string
  description_bg: string
  original_name?: string | null
}

export function catalogDisplayName(record: CatalogNameRecord): string {
  return `${record.description_en} / ${record.description_bg}`
}

export function catalogSourceDescription(record: CatalogNameRecord): string {
  return record.source_description || record.original_name || record.description
}
