export type CatalogPart = {
  id: number
  source_record_key: string
  source_id: string
  source_row_index: number
  family: string
  brand: string
  model: string
  assembly: string
  position: string
  part_number: string
  order_part_number: string
  replaced_by_part_number?: string | null
  description: string
  original_name?: string | null
  description_2?: string | null
  quantity?: number | null
  quantity_raw: string
  valid_for_raw?: string | null
  repair_kit_code?: string | null
  source_document: string
  source_page: number
  source_figure?: string | null
  source_version: string
  source_document_sha256: string
  verification_status: string
  source_anomaly_codes: string[]
  is_verified: boolean
}

export type CatalogDiagram = {
  id: number
  source_id: string
  page_number: number
  title: string
  source_pdf_sha256: string
  render_version: string
  technical_document_id: number
  preview_endpoint: string
  download_endpoint: string
}

export type CatalogAssembly = {
  source_id: string
  family: string
  assembly: string
  title: string
  document_reference?: string | null
  part_count: number
  diagram_count: number
  verified_hotspot_count: number
  diagrams: CatalogDiagram[]
}

export type MachineCatalog = {
  dataset_version: string
  supported: boolean
  message: string
  machine_id: number
  machine_number: string
  brand?: string | null
  model?: string | null
  family?: string | null
  assemblies: CatalogAssembly[]
}

export type AssemblyDetails = {
  dataset_version: string
  machine_id: number
  machine_number: string
  family: string
  source_id: string
  assembly: string
  title: string
  diagrams: CatalogDiagram[]
  parts: CatalogPart[]
}

export type PositionProvenance = 'AUTO_MATCHED' | 'MANUALLY_CONFIRMED'

export type PositionHotspot = {
  id: number
  hotspot_key: string
  diagram_id: number
  page_number: number
  position: string
  x: number
  y: number
  width: number
  height: number
  is_verified: boolean
  provenance: PositionProvenance
  confidence?: number | null
  verified_at?: string | null
  variants: CatalogPart[]
}

export type HotspotUpdate = Pick<
  PositionHotspot,
  'x' | 'y' | 'width' | 'height' | 'is_verified'
> & { reason: string }

export type HotspotUpdateResult = Pick<
  PositionHotspot,
  'id' | 'x' | 'y' | 'width' | 'height' | 'is_verified' | 'verified_at' | 'provenance' | 'confidence'
>

export type PositionMappingCoverage = {
  review_version: string
  reviewed_diagram_page_count: number
  sources: Array<Record<string, unknown>>
  totals: Record<string, number>
}

export type RepairKitComponent = {
  id: number
  part_id: number
  source_record_key: string
  position: string
  part_number: string
  description: string
  quantity: number
  quantity_raw: string
  source_document: string
  source_page: number
}

export type CatalogRepairKit = {
  id: number
  code: string
  name: string
  family: string
  source_id: string
  brand: string
  model: string
  assembly: string
  source_document: string
  source_page: number
  source_document_sha256: string
  source_version: string
  is_approved: boolean
  is_active: boolean
  components: RepairKitComponent[]
}

export type CatalogCartLine = {
  catalog_part_id: number
  source_record_key: string
  position: string
  part_number: string
  source_part_number: string
  description: string
  quantity: number
  source_quantity_raw: string
  assembly: string
  source_document: string
  source_page: number
  replacement_applied: boolean
}
