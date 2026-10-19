import { expect, it } from 'vitest'
import { flowPages } from './flowPages'
import type { Block } from './editorModel'

it('moves whole blocks to the following A4 page and splits oversized flow without losing height', () => {
  const blocks: Block[] = [{ id: 'a', type: 'text' }, { id: 'b', type: 'table' }, { id: 'c', type: 'text' }]
  const pages = flowPages(blocks, { a: 70, b: 60, c: 230 }, 100)
  expect(pages[0].map(s => s.block.id)).toEqual(['a'])
  expect(pages[1].map(s => s.block.id)).toEqual(['b', 'c'])
  expect(pages.flat().filter(s => s.block.id === 'c').reduce((sum, s) => sum + s.height, 0)).toBe(230)
  expect(pages.every(p => p.reduce((sum, s) => sum + s.height, 0) <= 100)).toBe(true)
  expect(pages.flat().filter(s => s.block.id === 'c').map(s => s.offset)).toEqual([0, 40, 140])
})

it('honors explicit breaks while keeping the empty editor a real A4 sheet', () => {
  expect(flowPages([], {}, 100)).toEqual([[]])
  const pages = flowPages([{ id: 'a', type: 'text' }, { id: 'break', type: 'page_break' }, { id: 'b', type: 'text' }], { a: 10, break: 5, b: 20 }, 100)
  expect(pages.map(p => p.map(s => s.block.id))).toEqual([['a'], ['break', 'b']])
})
