import { describe, expect, it } from 'vitest'
import { allBlocks, applyDensity, change, emptyGrid, undo, type Layout } from './editorModel'
import { proposalBg, proposalEn, proposalRu } from './proposalTranslations'

describe('Draft density and proposal language contracts', () => {
  it('keeps immutable input, repeating regions, flow and protected identity while supporting undo', () => {
    const layout: Layout = { schema_version: 3, positioning: 'flow', page: { format: 'A4', orientation: 'portrait', margin_mm: 11, header_mm: 30 }, blocks: [
      { id: 'header', type: 'grid', region: 'header', ...emptyGrid() },
      { id: 'signers', type: 'grid', ...emptyGrid() },
      { id: 'rows', type: 'dynamic_table', source: 'REQUEST_LINES', repeat_header: true, keep_rows_together: true },
    ] }
    layout.blocks[1].grid_rows![0].cells[0].blocks.push({ id: 'sign', type: 'signature', slot: 'RIGHT_SIGNATURE', required: true, min_height_mm: 30 })
    const original = structuredClone(layout), compact = applyDensity(layout, 'compact')
    expect(layout).toEqual(original)
    expect(compact.blocks[0]).toEqual(original.blocks[0])
    expect(compact.page).toEqual(original.page)
    expect(compact.blocks[2]).toMatchObject({ cell_padding_mm: .6, min_height_mm: 4, repeat_header: true, keep_rows_together: true })
    expect(allBlocks(compact.blocks).find(b => b.id === 'sign')).toMatchObject({ slot: 'RIGHT_SIGNATURE', required: true, min_height_mm: 14 })
    expect(undo(change({ present: { title: 'QA', layout }, past: [], future: [] }, { title: 'QA', layout: compact })).present.layout).toEqual(original)
    expect(applyDensity(layout, 'spacious').blocks[2].cell_padding_mm).toBeGreaterThan(compact.blocks[2].cell_padding_mm!)
  })
  it('has complete nonempty BG/EN/RU proposal and governance translations', () => {
    expect(Object.keys(proposalEn).sort()).toEqual(Object.keys(proposalBg).sort())
    expect(Object.keys(proposalRu).sort()).toEqual(Object.keys(proposalBg).sort())
    for (const messages of [proposalBg, proposalEn, proposalRu]) expect(Object.values(messages).every(s => s.trim().length > 0)).toBe(true)
  })
})
