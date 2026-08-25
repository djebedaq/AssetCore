export type OfficialRegistryFile = {
  format: 'docx' | 'pdf'
  download_endpoint: string
  preview_endpoint?: string | null
}

export type OfficialRegistryDocument = {
  document_type: string
  document_number: string
  official_document_id?: number | null
  version?: number | null
  version_status?: string | null
  files: OfficialRegistryFile[]
}

export type OfficialRegistryItem = {
  registry_key: string
  domain_id?: number | null
  machine_id?: number | null
  machine_number?: string | null
  status: string
  signature_status: 'SIGNED' | 'PARTIALLY_SIGNED' | 'UNSIGNED' | 'NOT_REQUIRED' | 'UNKNOWN'
  created_at?: string | null
  started_at?: string | null
  documents: OfficialRegistryDocument[]
}

export type OfficialRegistrySection = {
  count: number
  items: OfficialRegistryItem[]
}

export type OfficialDocumentRegistry = {
  transfers: OfficialRegistrySection
  repairs: OfficialRegistrySection
  parts: OfficialRegistrySection
}
