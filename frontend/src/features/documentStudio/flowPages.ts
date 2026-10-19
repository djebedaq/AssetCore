import type { Block } from './editorModel'
export type Slice = { block: Block; offset: number; height: number; split: boolean }
export function flowPages(blocks: Block[], heights: Record<string, number>, limit: number): Slice[][] {
  const pages: Slice[][] = [[]]
  let used = 0
  for (const block of blocks) {
    if (block.type === 'page_break') { if (pages.at(-1)!.length) { pages.push([]); used = 0 } }
    let remaining = Math.max(1, heights[block.id] || 28), offset = 0
    if (remaining <= limit && used + remaining > limit) { pages.push([]); used = 0 }
    while (remaining > 0) {
      const height = Math.min(remaining, limit - used)
      if (height <= 0) { pages.push([]); used = 0; continue }
      pages.at(-1)!.push({ block, offset, height, split: remaining > height || offset > 0 })
      remaining -= height; offset += height; used += height
      if (remaining > 0) { pages.push([]); used = 0 }
    }
  }
  return pages
}
