export type Analysis = {
  id: number; artifact_id: number; revision_id: number; status: 'RUNNING' | 'FAILED' | 'COMPLETED' | 'DISMISSED'
  page_count: number; processed_pages: number; error_code: string | null
  counts: Record<string, number>; states: Record<string, number>; ocr_pages: number
  roles?: Record<string, number>; matches?: Record<string, number>
}
export type Kind = 'GROUP' | 'PAGE' | 'PART' | 'HOTSPOT'
export type Location = { page_number: number; bbox: number[]; x: number; y: number; width: number; height: number; method: string }
export type TableEvidence = {
  headers: string[]; bbox: number[]; sample_cells: string[][]
  geometry?: { state: 'RESOLVED' | 'NEEDS_REVIEW'; normalized_boundaries?: number[]
    alternatives?: Array<{ score: number; boundaries: number[]; sample_cells: string[][] }> }
  schema: { state: 'RESOLVED' | 'NEEDS_REVIEW'; mapping: Record<string, string>; score: number; margin?: number | null
    alternatives: Array<{ score: number; mapping: Record<string, string> }> }
}
export type Candidate = {
  id: number; run_id?: number; source_key: string; version: number; kind: Kind
  state: 'PROPOSED' | 'NEEDS_REVIEW' | 'ACCEPTED' | 'REJECTED'; page_number: number | null
  confidence: number; artifact_id: number; sha256: string; warnings: string[]
  payload: {
    name?: string; group_key?: string; role?: string; merge_into_key?: string; assembly_id?: number
    position?: string; part_number?: string; description?: string; quantity?: string | null; quantity_raw?: string | null
    match?: string; locations?: Location[]; verified?: boolean
  }
  evidence: { raw_text?: string; bbox?: number[]; source_heading?: string; method?: string; tables?: TableEvidence[]; geometry?: { x: number; y: number; width: number; height: number } }
}
export type CandidatePage = { items: Candidate[]; next_after: number | null; total: number }
