export type Source = { id: number; artifact_id: number; page_number: number; role: 'EXPLODED_SCHEME' | 'SPARE_PARTS_LIST'; title: string; filename: string }
export type ReferencePage = { id: number; assembly_id: number; version: number; stable_key: string; sort_order: number; title: string | null;
  sources: Source[]; scheme_count: number; spare_list_count: number; part_count: number; position_count: number; mapped_position_count: number;
  status: 'COMPLETE' | 'NEEDS_ATTENTION' | 'NOT_STARTED' }
export type PartValues = { position: string; part_number: string; description: string | null; quantity: string | number | null;
  quantity_raw?: string | null; technical_notes?: string | null; technical_specification?: string | null }
export type Preview = { token: string; source: { visual_page_id: number; artifact_id: number; page_number: number; filename: string };
  warnings: string[]; method: string; rows: Array<{ payload: PartValues; warnings: string[]; raw_text: string; bbox?: number[] }>;
  tables: Array<{ bbox?: number[]; headers: string[]; sample_cells: string[][]; schema: { state: string; mapping: Record<string, string> } }> }
