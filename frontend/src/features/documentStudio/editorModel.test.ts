import { describe, expect, it } from 'vitest'
import { change, duplicateBlock, moveBlock, patchBlock, redo, removeBlock, undo, type Layout } from './editorModel'
import { editorBg, editorEn, editorRu } from './editorTranslations'

const layout = (): Layout => ({ schema_version: 1, positioning: 'flow', page: { format: 'A4', orientation: 'portrait', margin_mm: 15 }, blocks: [
  { id: 'number', type: 'field', field: 'DOCUMENT_NUMBER' }, { id: 'text', type: 'text', text: 'Чернова' },
  { id: 'left', type: 'signature', slot: 'LEFT_SIGNATURE' }, { id: 'last', type: 'text', text: 'Конец' },
] })
describe('Studio editing commands', () => {
  it('reorders the selected block in both directions without mutating the prior layout', () => {
    const before = layout(), next = moveBlock(before, 'text', 'last')
    expect(next.blocks.map(b => b.id)).toEqual(['number', 'left', 'last', 'text'])
    expect(moveBlock(next, 'text', 'number').blocks.map(b => b.id)).toEqual(['text', 'number', 'left', 'last'])
    expect(before.blocks[1].id).toBe('text')
  })
  it('protects required number/signature slots from removal and duplication', () => {
    const before = layout()
    for (const id of ['number', 'left']) {
      expect(removeBlock(before, id)).toBe(before)
      expect(duplicateBlock(before, id)).toBe(before)
    }
    const next = duplicateBlock(before, 'text')
    expect(next.blocks).toHaveLength(5)
    expect(new Set(next.blocks.map(b => b.id)).size).toBe(5)
    expect(removeBlock(next, 'text').blocks).toHaveLength(4)
  })
  it('upgrades v1 by retaining all values and changes only the selected block', () => {
    const before = layout(), next = patchBlock(before, 'text', { text: 'Обновена чернова', style: { bold: true } })
    expect(next.schema_version).toBe(2)
    expect(next.blocks[0]).toBe(before.blocks[0])
    expect(next.blocks[1].text).toBe('Обновена чернова')
    expect(before.blocks[1].text).toBe('Чернова')
  })
  it('undoes and redoes local changes and drops the redo branch after a new edit', () => {
    const original = { title: 'QA', layout: layout() }, first = { ...original, title: 'First' }
    const changed = change({ present: original, past: [], future: [] }, first)
    expect(undo(changed).present).toEqual(original)
    expect(redo(undo(changed)).present).toEqual(first)
    expect(change(undo(changed), { ...original, title: 'Other' }).future).toEqual([])
    expect(undo({ present: original, past: [], future: [] }).present).toEqual(original)
  })
  it('bounds history and supplies complete BG/EN/RU translations', () => {
    let history = { present: { title: 'QA', layout: layout() }, past: [], future: [] } as Parameters<typeof change>[0]
    for (let i = 0; i < 80; i++) history = change(history, { ...history.present, title: String(i) })
    expect(history.past).toHaveLength(50)
    expect(Object.keys(editorBg)).toEqual(Object.keys(editorEn))
    expect(Object.keys(editorBg)).toEqual(Object.keys(editorRu))
    for (const dictionary of [editorBg, editorEn, editorRu]) expect(Object.values(dictionary).every(Boolean)).toBe(true)
  })
})
