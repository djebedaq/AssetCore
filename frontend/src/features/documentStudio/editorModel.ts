export type BlockType = 'text' | 'heading' | 'field' | 'image' | 'logo' | 'table' | 'dynamic_table' | 'line' | 'frame' | 'signature' | 'qr' | 'page_number' | 'page_break' | 'conditional'
export type Style = { font: string; size_pt: number; color: string; align: 'left' | 'center' | 'right'; spacing_mm: number; bold: boolean; italic: boolean; background: string; border_pt: number; width_percent: number }
export type Column = { key: string; label: string; width_percent: number }
export type Block = { id: string; type: BlockType; region?: 'body' | 'header' | 'footer'; style?: Partial<Style>; text?: string; field?: string; when_field?: string; slot?: string; required?: true; image_id?: number; width_mm?: number; height_mm?: number; rows?: string[][]; widths?: number[] | null; repeat_header?: boolean; flow?: true; source?: string; columns?: Column[] }
export type Layout = { schema_version: 1 | 2; positioning: 'flow'; page: { format: 'A4'; orientation: 'portrait' | 'landscape'; margin_mm: number }; blocks: Block[] }
export const defaultStyle: Style = { font: 'Arial', size_pt: 11, color: '#183153', align: 'left', spacing_mm: 2, bold: false, italic: false, background: '#ffffff', border_pt: 0, width_percent: 100 }
export const requiredBlock = (b: Block) => b.type === 'signature' || (b.type === 'field' && ['DOCUMENT_NUMBER', 'PREPARER_NAME', 'SIGNATURE_STATUS'].includes(b.field || ''))
export const tableKeys = (source?: string) => source === 'REPAIR_EVENTS' ? ['date', 'event_type', 'description'] : source === 'PARTS_USED' ? ['position', 'part_number', 'description', 'quantity', 'unit'] : ['position', 'part_number', 'description', 'quantity', 'unit', 'note']
let sequence = 0
export const blockId = () => `b_${Date.now().toString(36)}_${++sequence}`
export function moveBlock(layout: Layout, id: string, target: string): Layout {
  if (id === target) return layout
  const blocks = [...layout.blocks], from = blocks.findIndex(b => b.id === id), to = blocks.findIndex(b => b.id === target)
  if (from < 0 || to < 0) return layout
  blocks.splice(to, 0, blocks.splice(from, 1)[0])
  return { ...layout, blocks }
}
export function removeBlock(layout: Layout, id: string): Layout {
  const block = layout.blocks.find(b => b.id === id)
  return !block || requiredBlock(block) ? layout : { ...layout, blocks: layout.blocks.filter(b => b.id !== id) }
}
export function duplicateBlock(layout: Layout, id: string): Layout {
  const block = layout.blocks.find(b => b.id === id)
  if (!block || requiredBlock(block) || layout.blocks.length >= 200) return layout
  const copy = structuredClone(block), blocks = [...layout.blocks]
  copy.id = blockId(); blocks.splice(blocks.indexOf(block) + 1, 0, copy)
  return { ...layout, blocks }
}
export function patchBlock(layout: Layout, id: string, patch: Partial<Block>): Layout {
  return { ...layout, schema_version: 2, blocks: layout.blocks.map(b => b.id === id ? { ...b, ...patch } : b) }
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
