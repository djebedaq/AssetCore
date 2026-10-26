export type BlockType = 'native_paragraph' | 'native_image' | 'grid' | 'text' | 'heading' | 'field' | 'image' | 'logo' | 'table' | 'dynamic_table' | 'line' | 'frame' | 'signature' | 'qr' | 'page_number' | 'page_break' | 'conditional'
export type Style = { font: string; size_pt: number; color: string; align: 'left' | 'center' | 'right'; spacing_mm: number; paragraph_before_mm: number; bold: boolean; italic: boolean; background: string; border_pt: number; width_percent: number }
export type Column = { key: string; label: string; width_percent: number }
export type GridCell = { blocks: Block[]; colspan: number; padding_mm: number | null; vertical_align: 'top' | 'center' | 'bottom'; style?: Partial<Style> }
export type GridRow = { cells: GridCell[]; min_height_mm: number; keep_together: boolean; page_break_before: boolean }
export type Block = { request_variant?: 'MACHINE' | 'FREE_FORM' | null; id: string; type: BlockType; grid_rows?: GridRow[]; repeat_rows?: number; keep_together?: boolean; show_identity?: boolean; label?: string; min_height_mm?: number | null; region?: 'body' | 'header' | 'footer'; style?: Partial<Style>; text?: string; field?: string; when_field?: string; slot?: string; required?: true; image_id?: number | null; cell_padding_mm?: number | null; width_mm?: number; height_mm?: number; rows?: string[][]; widths?: number[] | null; repeat_header?: boolean; native_properties?: boolean; empty_label?: string; keep_rows_together?: boolean; group_by?: 'assembly' | null; flow?: true; source?: string; columns?: Column[] }
export type Layout = { schema_version: 1 | 2 | 3 | 4; positioning: 'flow'; page: { format: 'A4'; orientation: 'portrait' | 'landscape'; margin_mm: number; header_mm?: number; footer_mm?: number; top_mm?: number | null; bottom_mm?: number | null; left_mm?: number | null; right_mm?: number | null; header_distance_mm?: number | null; footer_distance_mm?: number | null }; blocks: Block[]; native?: Record<string, unknown> | null }
export const defaultStyle: Style = { font: 'Arial', size_pt: 11, color: '#183153', align: 'left', spacing_mm: 2, paragraph_before_mm: 0, bold: false, italic: false, background: 'transparent', border_pt: 0, width_percent: 100 }
export function allBlocks(blocks: Block[]): Block[] { return blocks.flatMap(b => [b, ...(b.grid_rows?.flatMap(r => r.cells.flatMap(c => allBlocks(c.blocks))) || [])]) }
export const requiredBlock = (b: Block): boolean => b.type === 'signature' || (b.type === 'field' && ['DOCUMENT_NUMBER', 'PREPARER_NAME', 'SIGNATURE_STATUS'].includes(b.field || '')) || !!b.grid_rows?.some(r => r.cells.some(c => c.blocks.some(requiredBlock)))
export const tableKeys = (source?: string) => ({ REPAIR_EVENTS: ['date', 'event_type', 'description'], EQUIPMENT_CHECKLIST: ['position', 'component', 'condition', 'measurement', 'note'], REPAIR_PARTICIPANTS: ['name', 'job_title', 'contribution', 'duration'], REPAIR_ATTACHMENTS: ['filename', 'stage', 'description'] }[source || ''] || (source === 'PARTS_USED' ? ['position', 'part_number', 'description', 'quantity', 'unit'] : ['position', 'part_number', 'description', 'quantity', 'unit', 'note', 'assembly']))
let sequence = 0
export const blockId = () => `b_${Date.now().toString(36)}_${++sequence}`
export const emptyCell = (): GridCell => ({ blocks: [], colspan: 1, padding_mm: 1.5, vertical_align: 'top', style: { border_pt: .5, color: '#000000' } })
export const emptyGrid = (): Pick<Block, 'widths' | 'grid_rows'> => ({ widths: [33, 34, 33], grid_rows: [{ cells: [emptyCell(), emptyCell(), emptyCell()], min_height_mm: 12, keep_together: false, page_break_before: false }] })
function transform(blocks: Block[], edit: (items: Block[]) => Block[]): Block[] {
  return edit(blocks.map(b => b.grid_rows ? { ...b, grid_rows: b.grid_rows.map(r => ({ ...r, cells: r.cells.map(c => ({ ...c, blocks: transform(c.blocks, edit) })) })) } : b))
}
export function siblings(layout: Layout, id: string): Block[] {
  if (layout.blocks.some(b => b.id === id)) return layout.blocks
  for (const b of allBlocks(layout.blocks)) for (const r of b.grid_rows || []) for (const c of r.cells) if (c.blocks.some(b => b.id === id)) return c.blocks
  return []
}
export function moveBlock(layout: Layout, id: string, target: string): Layout {
  if (id === target) return layout
  return { ...layout, blocks: transform(layout.blocks, items => {
    const blocks = [...items], from = blocks.findIndex(b => b.id === id), to = blocks.findIndex(b => b.id === target)
    if (from < 0 || to < 0) return items
    blocks.splice(to, 0, blocks.splice(from, 1)[0]); return blocks
  }) }
}
export function removeBlock(layout: Layout, id: string): Layout {
  const block = allBlocks(layout.blocks).find(b => b.id === id)
  if (!block || requiredBlock(block)) return layout
  return { ...layout, blocks: transform(layout.blocks, items => items.filter(b => b.id !== id)) }
}
export function duplicateBlock(layout: Layout, id: string): Layout {
  const original = allBlocks(layout.blocks).find(b => b.id === id)
  if (!original || requiredBlock(original) || allBlocks(layout.blocks).length + allBlocks([original]).length > 200) return layout
  return { ...layout, blocks: transform(layout.blocks, items => items.flatMap(b => {
    if (b.id !== id) return [b]
    const copy = structuredClone(b); allBlocks([copy]).forEach(child => { child.id = blockId() }); return [b, copy]
  })) }
}
export function patchBlock(layout: Layout, id: string, patch: Partial<Block>): Layout {
  return { ...layout, schema_version: Math.max(2, layout.schema_version) as Layout['schema_version'], blocks: transform(layout.blocks, items => items.map(b => b.id === id ? { ...b, ...patch } : b)) }
}
export function insertInCell(layout: Layout, target: { grid: string; row: number; cell: number }, block: Block): Layout {
  const grid = allBlocks(layout.blocks).find(b => b.id === target.grid), rows = structuredClone(grid?.grid_rows)
  const cell = rows?.[target.row]?.cells[target.cell]
  if (!grid || !cell || allBlocks(layout.blocks).length >= 200) return layout
  cell.blocks.push({ ...block, region: 'body' })
  return { ...patchBlock(layout, grid.id, { grid_rows: rows }), schema_version: 3 }
}
export function relocateToCell(layout: Layout, target: { grid: string; row: number; cell: number }, id: string): Layout {
  const block = allBlocks(layout.blocks).find(b => b.id === id)
  if (!block || allBlocks([block]).some(b => b.id === target.grid)) return layout
  const next = { ...layout, blocks: transform(layout.blocks, items => items.filter(b => b.id !== id)) }
  return insertInCell(next, target, block)
}
export type EditorContent = { title: string; layout: Layout }
export type History = { present: EditorContent; past: EditorContent[]; future: EditorContent[] }
export function change(history: History, next: EditorContent): History {
  if (JSON.stringify(next) === JSON.stringify(history.present)) return history
  return { present: next, past: [...history.past.slice(-49), history.present], future: [] }
}
export function undo(history: History): History {
  return history.past.length ? { present: history.past.at(-1)!, past: history.past.slice(0, -1), future: [history.present, ...history.future] } : history
}
export function redo(history: History): History {
  return history.future.length ? { present: history.future[0], past: [...history.past, history.present], future: history.future.slice(1) } : history
}

export type Density = 'compact' | 'standard' | 'spacious'
export function applyDensity(layout: Layout, preset: Density): Layout {
  const next = structuredClone(layout)
  const [size, spacing, padding, height] = { compact: [9, .5, .6, 4], standard: [10, 1.5, 1.2, 6], spacious: [11, 3, 2, 8] }[preset]
  // Repeating regions retain their reserved geometry. No exact heights, flow
  // rules, image dimensions, fields or protected signature slots are changed.
  for (const b of allBlocks(next.blocks.filter(b => (b.region || 'body') === 'body'))) {
    const current = { ...defaultStyle, ...b.style }
    b.style = { ...current, size_pt: b.type === 'heading' ? size + 3 : current.size_pt > 14 ? current.size_pt : size,
      spacing_mm: spacing, paragraph_before_mm: 0 }
    if (b.type === 'signature') b.min_height_mm = 14
    if (b.type === 'table' || b.type === 'dynamic_table') { b.cell_padding_mm = padding; b.min_height_mm = height }
    for (const row of b.grid_rows || []) { row.min_height_mm = height; for (const cell of row.cells) cell.padding_mm = padding }
  }
  return next
}
