import { act, cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { bg, formatDate, I18nProvider } from '../../i18n'
import { clearSessionUser } from '../../permissions'
import type { MachineTimelinePage, TimelineCategory } from '../../types'
import { MachinePassportModal } from './MachinePassportModal'
import { passport } from './passportTestFixtures'
import { TIMELINE_CATEGORIES, CATEGORY_KEYS } from './timelinePresentation'
import { timelineItem, timelinePage } from './timelineTestFixtures'

function response(value: unknown) {
  return new Response(JSON.stringify(value), { status: 200, headers: { 'Content-Type': 'application/json' } })
}
function deferred<T>() {
  let resolve!: (value: T) => void
  let reject!: (reason: unknown) => void
  const promise = new Promise<T>((yes, no) => { resolve = yes; reject = no })
  return { promise, resolve, reject }
}
type Handler = (url: URL, init?: RequestInit) => Promise<MachineTimelinePage>
function mount(handler: Handler = async () => timelinePage(), limited = false) {
  const requests: { url: URL; init?: RequestInit }[] = []
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = new URL(String(input), 'http://localhost')
    if (url.pathname.endsWith('/timeline')) {
      requests.push({ url, init })
      return response(await handler(url, init))
    }
    if (url.pathname.endsWith('/passport')) {
      const machineId = Number(url.pathname.split('/')[3])
      return response({ ...passport, limited_view: limited, machine: { ...passport.machine, id: machineId, inventory_number: String(machineId) } })
    }
    if (url.pathname.endsWith('/qr')) return new Response(new Blob(['test-only']))
    throw new Error('Unexpected test request')
  })
  vi.stubGlobal('fetch', fetchMock)
  const view = (machineId = 13) => <I18nProvider initialLocale="bg"><MachinePassportModal machineId={machineId} onClose={vi.fn()} /></I18nProvider>
  const rendered = render(view())
  return { ...rendered, requests, fetchMock, changeMachine: (id: number) => rendered.rerender(view(id)) }
}
async function history() { await userEvent.click(await screen.findByRole('tab', { name: bg['passport.tab.history'] })) }
function panel() { return within(screen.getByRole('tabpanel')) }
async function choose(category: TimelineCategory) {
  await userEvent.click(panel().getByRole('button', { name: bg[CATEGORY_KEYS[category]] }))
}

beforeEach(() => {
  localStorage.clear()
  clearSessionUser()
  vi.stubGlobal('requestAnimationFrame', (callback: FrameRequestCallback) => { callback(0); return 1 })
  URL.createObjectURL = vi.fn(() => 'blob:qa-only')
  URL.revokeObjectURL = vi.fn()
})
afterEach(() => { cleanup(); vi.unstubAllGlobals(); vi.restoreAllMocks() })

describe('canonical passport timeline requests', () => {
  it('is lazy, fetches once on first History and caches the current filter/page across tabs and rerenders', async () => {
    const view = mount(async (url) => timelinePage({ category: url.searchParams.get('category') as TimelineCategory, page: Number(url.searchParams.get('page')), total: 26, total_pages: 2, has_next: true }))
    await screen.findByRole('tab', { name: bg['passport.tab.overview'] })
    expect(view.requests).toHaveLength(0)
    await history()
    await panel().findByText('QA-TIMELINE-ONLY')
    expect(view.requests).toHaveLength(1)
    expect(view.requests[0].url.pathname + view.requests[0].url.search).toBe('/api/machines/13/timeline?category=all&page=1&page_size=25')
    expect(view.requests[0].init?.credentials).toBe('same-origin')
    expect(view.requests[0].init?.signal).toBeInstanceOf(AbortSignal)
    await choose('transfer')
    await panel().findByText('QA-TIMELINE-ONLY')
    await userEvent.click(panel().getByRole('button', { name: bg['timeline.next'] }))
    await panel().findByText('Страница 2 от 2')
    const before = view.requests.length
    view.changeMachine(13)
    await userEvent.click(screen.getByRole('tab', { name: bg['passport.tab.overview'] }))
    await history()
    expect(panel().getByText('Страница 2 от 2')).toBeVisible()
    expect(panel().getByRole('button', { name: bg['timeline.transfer'] })).toHaveAttribute('aria-pressed', 'true')
    expect(view.requests).toHaveLength(before)
  })

  it('uses all six backend filters, resets page to 1 and never filters or sorts the response locally', async () => {
    const view = mount(async (url) => timelinePage({
      category: url.searchParams.get('category') as TimelineCategory,
      items: [timelineItem({ event_key: 'z', reference: 'SERVER-FIRST', occurred_at: '2025-01-01T00:00:00Z' }), timelineItem({ event_key: 'a', reference: 'SERVER-SECOND' })],
      count: 2, total: 60, total_pages: 3,
    }))
    await history()
    for (const category of [...TIMELINE_CATEGORIES.slice(1), 'all'] as TimelineCategory[]) {
      await choose(category)
      await panel().findByText('SERVER-FIRST')
      expect(view.requests.at(-1)?.url.search).toBe(`?category=${category}&page=1&page_size=25`)
      expect(panel().getByRole('button', { name: bg[CATEGORY_KEYS[category]] })).toHaveAttribute('aria-pressed', 'true')
      expect(panel().getAllByRole('listitem').map((node) => node.getAttribute('data-event-key'))).toEqual(['z', 'a'])
    }
    expect(view.requests).toHaveLength(7)
    expect(screen.getAllByRole('tablist')).toHaveLength(1)
  })

  it('uses server totals/count/page flags, supports next/previous and replaces rather than appends rows', async () => {
    const view = mount(async (url) => {
      const page = Number(url.searchParams.get('page'))
      return timelinePage({ page, total: 26, total_pages: 2, has_next: page === 1, has_previous: page === 2,
        items: [timelineItem({ reference: `PAGE-${page}` })] })
    })
    await history()
    await panel().findByText('PAGE-1')
    expect(panel().getByText('На страницата: 1 · Общо: 26')).toBeVisible()
    expect(panel().getByRole('button', { name: bg['timeline.previous'] })).toBeDisabled()
    await userEvent.click(panel().getByRole('button', { name: bg['timeline.next'] }))
    await panel().findByText('PAGE-2')
    expect(panel().queryByText('PAGE-1')).not.toBeInTheDocument()
    expect(panel().getByRole('button', { name: bg['timeline.next'] })).toBeDisabled()
    await userEvent.click(panel().getByRole('button', { name: bg['timeline.previous'] }))
    await panel().findByText('PAGE-1')
    expect(view.requests.map(({ url }) => url.searchParams.get('page'))).toEqual(['1', '2', '1'])
  })

  it.each(['all', 'repair'] as const)('renders an empty %s category without Page 1 of 0', async (category) => {
    mount(async (url) => timelinePage({ category: url.searchParams.get('category') as TimelineCategory, items: [], total: 0, count: 0, total_pages: 0 }))
    await history()
    if (category !== 'all') await choose(category)
    expect(await panel().findByText(bg[category === 'all' ? 'timeline.emptyAll' : 'timeline.emptyCategory'])).toBeVisible()
    expect(panel().queryByText('Страница 1 от 0')).not.toBeInTheDocument()
    expect(panel().getByRole('button', { name: bg['timeline.next'] })).toBeDisabled()
  })

  it('truthfully renders a now-out-of-range 200 empty page using the backend previous flag', async () => {
    mount(async (url) => url.searchParams.get('page') === '1'
      ? timelinePage({ total: 26, total_pages: 2, has_next: true })
      : timelinePage({ page: 2, total: 1, total_pages: 1, count: 0, items: [], has_previous: true }))
    await history()
    await panel().findByText('QA-TIMELINE-ONLY')
    await userEvent.click(panel().getByRole('button', { name: bg['timeline.next'] }))
    expect(await panel().findByText('Страница 2 е извън наличните 1 страници.')).toBeVisible()
    expect(panel().getByText(bg['timeline.emptyPage'])).toBeVisible()
    expect(panel().getByRole('button', { name: bg['timeline.previous'] })).toBeEnabled()
  })

  it('contains errors, never falls back to passport.history, retries the same GET only on demand', async () => {
    let fail = true
    const view = mount(async (url) => {
      if (fail) throw new Error('RAW INTERNAL ERROR')
      return timelinePage({ category: url.searchParams.get('category') as TimelineCategory })
    })
    await history()
    expect(await panel().findByRole('alert')).toHaveTextContent(bg['timeline.error'])
    expect(screen.getByRole('heading', { name: 'Машина №13' })).toBeVisible()
    expect(panel().queryByText('TEST-EVENT')).not.toBeInTheDocument()
    expect(panel().queryByText('RAW INTERNAL ERROR')).not.toBeInTheDocument()
    await userEvent.click(screen.getByRole('tab', { name: bg['passport.tab.overview'] }))
    await history()
    expect(view.requests).toHaveLength(1)
    fail = false
    await userEvent.click(panel().getByRole('button', { name: bg['official.retry'] }))
    expect(await panel().findByText('QA-TIMELINE-ONLY')).toBeVisible()
    expect(view.requests).toHaveLength(2)
    expect(view.requests[1].url.href).toBe(view.requests[0].url.href)
    expect(view.requests.every(({ init }) => !init?.method || init.method === 'GET')).toBe(true)
  })

  it('clears previous rows immediately when a replacement category fails', async () => {
    const pending = deferred<MachineTimelinePage>()
    mount(async (url) => url.searchParams.get('category') === 'all' ? timelinePage() : pending.promise)
    await history()
    await panel().findByText('QA-TIMELINE-ONLY')
    await choose('repair')
    expect(panel().queryByText('QA-TIMELINE-ONLY')).not.toBeInTheDocument()
    expect(panel().getByRole('status')).toHaveTextContent(bg['timeline.loading'])
    await act(async () => pending.reject(new Error('test-only')))
    expect(panel().getByRole('alert')).toBeVisible()
    expect(panel().queryByText('QA-TIMELINE-ONLY')).not.toBeInTheDocument()
  })

  it('aborts and ignores late filter success/error after a newer category succeeds', async () => {
    const old = deferred<MachineTimelinePage>()
    const view = mount(async (url) => url.searchParams.get('category') === 'all' ? old.promise : timelinePage({ category: 'repair', items: [timelineItem({ reference: 'CURRENT' })] }))
    await history()
    await choose('repair')
    await panel().findByText('CURRENT')
    expect(view.requests[0].init?.signal?.aborted).toBe(true)
    await act(async () => old.resolve(timelinePage({ items: [timelineItem({ reference: 'STALE' })] })))
    expect(panel().queryByText('STALE')).not.toBeInTheDocument()
    expect(panel().getByText('CURRENT')).toBeVisible()
    expect(panel().queryByRole('alert')).not.toBeInTheDocument()
  })

  it('ignores a late page response after a category change and resets to page 1', async () => {
    const old = deferred<MachineTimelinePage>()
    const view = mount(async (url) => url.searchParams.get('page') === '2' ? old.promise : timelinePage({ category: url.searchParams.get('category') as TimelineCategory, has_next: true, total_pages: 2, total: 26 }))
    await history()
    await panel().findByText('QA-TIMELINE-ONLY')
    await userEvent.click(panel().getByRole('button', { name: bg['timeline.next'] }))
    await choose('parts')
    await panel().findByText('QA-TIMELINE-ONLY')
    await act(async () => old.resolve(timelinePage({ page: 2, items: [timelineItem({ reference: 'STALE-PAGE' })] })))
    expect(panel().queryByText('STALE-PAGE')).not.toBeInTheDocument()
    expect(view.requests.at(-1)?.url.search).toBe('?category=parts&page=1&page_size=25')
  })

  it.each(['resolve', 'reject'] as const)('resets on machine change and ignores old-machine %s even if cancellation is ignored', async (finish) => {
    const old = deferred<MachineTimelinePage>()
    const view = mount(async (url) => url.pathname.includes('/13/') ? old.promise : timelinePage({ machine_id: 14, items: [timelineItem({ machine_id: 14, reference: 'CURRENT-MACHINE' })] }))
    await history()
    view.changeMachine(14)
    await screen.findByRole('heading', { name: 'Машина №14' })
    expect(screen.getByRole('tab', { name: bg['passport.tab.overview'] })).toHaveAttribute('aria-selected', 'true')
    expect(view.requests).toHaveLength(1)
    expect(view.requests[0].init?.signal?.aborted).toBe(true)
    await history()
    await panel().findByText('CURRENT-MACHINE')
    await act(async () => finish === 'resolve' ? old.resolve(timelinePage()) : old.reject(new Error('late')))
    expect(panel().queryByText('QA-TIMELINE-ONLY')).not.toBeInTheDocument()
    expect(panel().queryByRole('alert')).not.toBeInTheDocument()
    expect(panel().getByText('CURRENT-MACHINE')).toBeVisible()
  })

  it('drops an already loaded machine cache and does not reuse it after closing/reopening', async () => {
    const first = mount()
    await history()
    await panel().findByText('QA-TIMELINE-ONLY')
    first.unmount()
    const second = mount()
    await history()
    await panel().findByText('QA-TIMELINE-ONLY')
    expect(second.requests).toHaveLength(1)
  })

  it('aborts on tab unmount/close; AbortError does not become a visible error', async () => {
    const old = deferred<MachineTimelinePage>()
    const view = mount(async () => old.promise)
    await history()
    await userEvent.click(screen.getByRole('tab', { name: bg['passport.tab.overview'] }))
    expect(view.requests[0].init?.signal?.aborted).toBe(true)
    await act(async () => old.reject(new DOMException('aborted', 'AbortError')))
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
    view.unmount()
  })

  it('never mounts or fetches timeline for the Observer limited view', async () => {
    const view = mount(undefined, true)
    await screen.findByText(bg['passport.limitedView'])
    expect(screen.queryByRole('tablist')).not.toBeInTheDocument()
    expect(view.requests).toHaveLength(0)
  })

  it('keeps category controls separate from passport keyboard tabs and supports keyboard filter activation', async () => {
    const view = mount(async (url) => timelinePage({ category: url.searchParams.get('category') as TimelineCategory }))
    const overview = await screen.findByRole('tab', { name: bg['passport.tab.overview'] })
    fireEvent.keyDown(overview, { key: 'ArrowRight' })
    await panel().findByText('QA-TIMELINE-ONLY')
    const filter = panel().getByRole('button', { name: bg['timeline.parts'] })
    filter.focus()
    await userEvent.keyboard('{Enter}')
    expect(filter).toHaveAttribute('aria-pressed', 'true')
    expect(view.requests.at(-1)?.url.searchParams.get('category')).toBe('parts')
    expect(screen.getAllByRole('tablist')).toHaveLength(1)
  })
})

describe('industrial lifecycle presentation', () => {
  it('renders server event order, transfer request separately from returned, correct status domains and selected details', async () => {
    const items = [
      timelineItem(),
      timelineItem({ event_key: 'transfer:2:returned', event_type: 'TRANSFER_RETURNED', status_before: 'ISSUED', status_after: 'REPAIR', description: 'QA return notes', details: { condition: 'QA condition', result: 'QA result' } }),
      timelineItem({ event_key: 'repair_event:1', category: 'repair', source_type: 'repair_event', event_type: 'STATUS_CHANGE', reference: 'QA-REPAIR', status_before: 'DIAGNOSIS', status_after: 'REPAIRING', details: { test_passed: false, test_pressure_bar: 500, leaks_detected: true, repair_minutes: 0 } }),
      timelineItem({ event_key: 'request:1', category: 'parts', source_type: 'part_request_transition', event_type: 'PART_REQUEST_PARTIALLY_DELIVERED', status_before: 'ORDERED', status_after: 'PARTIALLY_DELIVERED', reference: 'QA-REQUEST' }),
      timelineItem({ event_key: 'repair_part:1', category: 'parts', source_type: 'repair_part', event_type: 'PART_USED', details: { part_number: 'QA-PART', quantity: 2, unit: 'бр.', source: 'QA source' } }),
      timelineItem({ event_key: 'official_document:1:v2', category: 'document', source_type: 'official_document', event_type: 'OFFICIAL_DOCUMENT_FINALIZED', reference: 'QA-DOCUMENT', status_after: 'FINALIZED', details: { document_type: 'TRANSFER_RETURN', version: 2, version_status: 'FINALIZED', registry_category: 'transfers' } }),
    ]
    mount(async () => timelinePage({ items, count: items.length, total: items.length }))
    await history()
    await panel().findByText('QA-DOCUMENT')
    const cards = panel().getAllByRole('article')
    expect(within(cards[0]).getByText(bg['event.returnRequested'])).toBeVisible()
    expect(within(cards[0]).queryByText(bg['timeline.after'])).not.toBeInTheDocument()
    expect(within(cards[1]).getByText(bg['event.transferReturned'])).toBeVisible()
    expect(within(cards[1]).getByText('Издадена')).toBeVisible()
    expect(within(cards[1]).getByText('В ремонт')).toBeVisible()
    expect(within(cards[2]).getByText('Диагностика')).toBeVisible()
    expect(within(cards[2]).getByText(bg['status.repairing'])).toBeVisible()
    expect(within(cards[2]).getByText('Не')).toBeVisible()
    expect(within(cards[2]).getByText('Да')).toBeVisible()
    expect(within(cards[2]).getByText('500')).toBeVisible()
    expect(within(cards[2]).getByText('0')).toBeVisible()
    expect(within(cards[3]).getByText(bg['event.requestPartial'])).toBeVisible()
    expect(within(cards[3]).getByText(bg['status.partiallyDelivered'])).toBeVisible()
    expect(within(cards[4]).getByText('QA-PART')).toBeVisible()
    expect(within(cards[4]).getByText('QA source')).toBeVisible()
    expect(within(cards[5]).getAllByText(bg['timeline.finalized'])).toHaveLength(2)
    expect(within(cards[5]).getByText(bg['documentType.transferReturn'])).toBeVisible()
    expect(panel().queryByRole('button', { name: bg['common.download'] })).not.toBeInTheDocument()
    expect(panel().queryByRole('link')).not.toBeInTheDocument()
    expect(panel().getAllByText(formatDate('bg', items[0].occurred_at)).length).toBe(6)
  })

  it('escapes operational text, omits null references and rejects nested/unknown details without dumping JSON', async () => {
    const hostile = '<img src=x onerror=alert(1)>'
    mount(async () => timelinePage({ items: [timelineItem({
      category: 'parts', source_type: 'repair_part', event_type: 'PART_USED', reference: null,
      description: hostile, details: JSON.parse('{"part_number":{"hidden":"NESTED"},"source":["ARRAY"],"quantity":true,"signature_image":"SECRET","unknown":"HIDDEN","unit":"бр."}'),
    })] }))
    await history()
    expect(await panel().findByText(hostile)).toBeVisible()
    expect(panel().queryByRole('img')).not.toBeInTheDocument()
    for (const text of ['NESTED', 'ARRAY', 'SECRET', 'HIDDEN', bg['common.system'], '[object Object]']) expect(panel().queryByText(text)).not.toBeInTheDocument()
    expect(panel().getByText('бр.')).toBeVisible()
  })

  it('uses a safe unknown event/source fallback while retaining an unknown human-readable status', async () => {
    mount(async () => timelinePage({ items: [timelineItem({ event_type: 'FUTURE_PRIVATE_CODE', source_type: 'future_source', category: 'asset', status_after: 'Future operational status', details: {} })] }))
    await history()
    expect(await panel().findByText(bg['event.other'])).toBeVisible()
    expect(panel().getByText('Future operational status')).toBeVisible()
    expect(panel().queryByText('FUTURE_PRIVATE_CODE')).not.toBeInTheDocument()
    expect(panel().queryByText('future_source')).not.toBeInTheDocument()
  })
})
