// HTTP fixtures for migrating existing workflow tests to additive paginated reads.
// New filtering tests assert the actual query parameters independently.
import type { Mock } from 'vitest'

export function pageFixture(items: unknown[]) {
  return { items, total: items.length, page: 1, page_size: 25, total_pages: items.length ? 1 : 0, has_previous: false, has_next: false }
}
const json = (value: unknown, status = 200) => new Response(JSON.stringify(value), { status, headers: { 'Content-Type': 'application/json' } })
export function withWorkspaceRoutes(mock: Mock) {
  const original = mock.getMockImplementation()
  if (!original) throw new Error('Missing fixture implementation')
  mock.mockImplementation(async (input: RequestInfo | URL, init?: RequestInit) => {
    const path = String(input)
    const parsed = new URL(path, 'http://qa.invalid')
    if (parsed.pathname === '/api/workspace/categories') return json([{ id: 1, code: 'QA', name_bg: 'QA workspace category', name_en: 'QA workspace category', name_ru: 'QA workspace category', is_active: true, asset_count: 2, has_pressure: true }])
    let legacy = path
    const kind = parsed.pathname.split('/').pop()
    const page = parsed.pathname.startsWith('/api/workspace/')
    const detail = /^\/api\/machines\/(\d+)$/.exec(path)
    if (page && kind === 'machines') {
      const category = parsed.searchParams.get('category_id')
      legacy = category && parsed.searchParams.get('module') !== 'catalog' && parsed.searchParams.get('module') !== 'repairs' && parsed.searchParams.get('module') !== 'transfers' ? `/api/machines?category_id=${category}` : '/api/machines'
    } else if (page && kind === 'repairs') legacy = '/api/repair-cases'
    else if (page && kind === 'requests') legacy = '/api/part-requests/multi'
    else if (detail) legacy = '/api/machines'
    const result = await original(legacy, init) as Response
    if (!page && !detail) return result
    const body: unknown = await result.clone().json()
    if (!Array.isArray(body)) return result
    let items = body as Array<Record<string, unknown>>
    if (kind === 'machines' || detail) items = items.map(item => ({ category_id: 1, category_capabilities: ['HAS_TRANSFER_WORKFLOW', 'HAS_REPAIR_WORKFLOW', 'HAS_PARTS_CATALOG'], ...item }))
    if (detail) return items.find(item => item.id === Number(detail[1])) ? json(items.find(item => item.id === Number(detail[1]))) : json({ detail: { code: 'machine_not_found' } }, 404)
    const query = parsed.searchParams.get('q')?.toLowerCase()
    if (query) items = items.filter(item => JSON.stringify(item).toLowerCase().includes(query))
    const status = parsed.searchParams.get('status')
    if (status) items = items.filter(item => item.status === status)
    return json(pageFixture(items))
  })
  return mock
}
