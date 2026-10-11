import type { Preview, ReviewSession } from './guidedTypes'

// Stateful API fixture: resume returns saved server data, including corrections.
export class ReviewTestTransport {
  previews = new Map<number, Preview>()
  record(preview: Preview) {
    const previous = this.previews.get(preview.source.visual_page_id)
    const saved: Preview = { ...preview, rows: preview.rows.map((row, i) => ({ ...row,
      payload: previous?.rows[i]?.payload || row.payload,
      candidate_id: preview.source.visual_page_id * 1000 + i, candidate_version: previous?.rows[i]?.candidate_version || 1,
      candidate_state: previous?.rows[i]?.candidate_state || 'PENDING',
    })) }
    this.previews.set(preview.source.visual_page_id, saved)
    return saved
  }
  handle(path: string, init?: RequestInit) {
    if (path.endsWith('/review-session') || path.endsWith('/source-review')) {
      const session: ReviewSession = { id: 1, selection_digest: 'qa', sources: [...this.previews.values()].map(preview => ({
        id: preview.source.visual_page_id, visual_page_id: preview.source.visual_page_id, version: 1, fingerprint: 'qa',
        source: preview.source, preview, processing_state: 'SUCCEEDED', review_state: 'NEEDS_REVIEW', candidates: [], attempts: [],
      })) }
      return new Response(JSON.stringify(session), { headers: { 'Content-Type': 'application/json' } })
    }
    if (path.includes('/extraction-candidates/')) {
      const id = Number(path.split('/').at(-1)), data = JSON.parse(String(init?.body))
      let result = {}
      for (const preview of this.previews.values()) for (const row of preview.rows) if (row.candidate_id === id) {
        row.payload = data.values || row.payload
        row.candidate_version = (row.candidate_version || 1) + 1
        row.candidate_state = data.action === 'REJECT' ? 'REJECTED' : 'PENDING'
        result = { version: row.candidate_version, state: row.candidate_state }
      }
      return new Response(JSON.stringify(result), { headers: { 'Content-Type': 'application/json' } })
    }
    return null
  }
}
