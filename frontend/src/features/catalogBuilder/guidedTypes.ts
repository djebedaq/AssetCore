export type Source = { id: number; artifact_id: number; sha256?: string; sort_order?: number; page_number: number; role: 'EXPLODED_SCHEME' | 'SPARE_PARTS_LIST'; title: string; filename: string }
export type ReferencePage = { id: number; assembly_id: number; version: number; stable_key: string; sort_order: number; title: string | null;
  sources: Source[]; scheme_count: number; spare_list_count: number; part_count: number; position_count: number; mapped_position_count: number;
  status: 'COMPLETE' | 'NEEDS_ATTENTION' | 'NOT_STARTED' }
export type PartValues = { position: string; part_number: string; description: string | null; quantity: string | number | null;
  quantity_raw?: string | null; technical_notes?: string | null; technical_specification?: string | null }
export type Preview = { token: string; source: { visual_page_id: number; artifact_id: number; page_number: number; filename: string };
  warnings: string[]; method: string; rows: Array<{ payload: PartValues; warnings: string[]; raw_text: string; bbox?: number[];
    candidate_id?: number; candidate_version?: number; candidate_state?: string }>;
  tables: Array<{ bbox?: number[]; headers: string[]; sample_cells: string[][]; schema: { state: string; mapping: Record<string, string> } }> }

export type ReviewCandidate = { id: number; version: number; state: string; part_id: number | null;
  values: PartValues; reason: string | null; original: { payload: PartValues } }
export type ReviewSource = { id: number; visual_page_id: number; version: number; fingerprint: string;
  processing_state: 'QUEUED' | 'RUNNING' | 'SUCCEEDED' | 'FAILED' | 'CANCELLED';
  review_state: 'NOT_REVIEWED' | 'NEEDS_REVIEW' | 'VERIFIED'; source: Preview['source']; preview: Preview | null;
  attempts: Array<{ id: number; state: 'RUNNING' | 'SUCCEEDED' | 'FAILED' | 'CANCELLED'; row_count: number; error_code: string | null }>;
  candidates: ReviewCandidate[] }
export type ReviewSession = { id: number; selection_digest: string; sources: ReviewSource[] }
