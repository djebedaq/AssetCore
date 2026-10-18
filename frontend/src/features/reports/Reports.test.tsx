import { act, cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { I18nProvider, bg } from '../../i18n'
import { clearSessionUser, setSessionUser } from '../../permissions'
import type { UserSession } from '../../types'
import Reports from './Reports'
import { useReport } from './reportData'

vi.mock('recharts', () => ({ ResponsiveContainer: () => null, LineChart: () => null, BarChart: () => null, Bar: () => null, CartesianGrid: () => null, Legend: () => null, Line: () => null, Tooltip: () => null, XAxis: () => null, YAxis: () => null }))
vi.mock('../../api', async importOriginal => ({ ...await importOriginal<object>(), downloadApiFile: vi.fn(async () => undefined) }))
const page = { items: [], page: 1, page_size: 20, total: 0, total_pages: 0, has_next: false, has_previous: false }
const asset = { id: 100, inventory_number: 'QA-100', name: 'Synthetic QA', brand: 'QA', status: 'READY' }
const metric = { key: 'issues', value: 5, unit: 'count', drill: 'issues', current: false, sample: null, previous: 0, change: 5, percent: null }
const report = { section: 'overview', generated_at: '2026-10-18T12:00:00Z', filters: { date_from: '2026-09-19', date_to: '2026-10-18' }, previous_filters: { date_from: '2026-08-20', date_to: '2026-09-18' }, capabilities: { usage: true, repairs: true, requests: true }, current: [{ ...metric, key: 'total_machines', drill: 'total_machines', current: true, value: 3 }], metrics: [metric], attention: [{ machine: asset, open_count: 1, reasons: [{ code: 'frequent', count: 5, days: 90 }] }], attention_total: 1, categories: [], rankings: [], ranking_kind: 'repairs', ranking_key: 'opened', trends: [{ period: '2026-10-12', issues: 5 }], machines: [], parts: [], articles: [], records: page, delayed: page }
const response = (value: unknown) => new Response(JSON.stringify(value), { status: 200 })
let fetcher: ReturnType<typeof vi.fn>
beforeEach(() => {
  setSessionUser({ permissions: ['reports.view', 'assets.view', 'transfers.view', 'repairs.view', 'requests.view'] } as UserSession)
  fetcher = vi.fn(async (url: string) => response(url.includes('/workspace/categories') ? [{ id: 7, name_bg: 'QA category', name_en: 'QA category', name_ru: 'QA category', is_active: true }] : url.includes('/workspace/machines') ? { ...page, items: [asset] } : url.includes('/reports/records') ? page : url.includes('/reports/') ? { ...report, section: url.split('/reports/')[1].split('?')[0] } : asset))
  vi.stubGlobal('fetch', fetcher)
  vi.stubGlobal('scrollTo', vi.fn())
})
afterEach(() => { cleanup(); clearSessionUser(); vi.unstubAllGlobals(); vi.restoreAllMocks() })
it('mechanics can navigate all four analyses without operational audit', async () => {
  render(<I18nProvider><Reports /></I18nProvider>)
  expect(await screen.findByRole('heading', { name: 'Машини, изискващи внимание' })).toBeVisible()
  for (const label of ['Използване на техниката', 'Ремонти и неизправности', 'Заявки и доставки', 'Общ преглед']) await userEvent.click(screen.getByRole('navigation', { name: 'Отчети и анализи' }).getElementsByTagName('button')[['Общ преглед', 'Използване на техниката', 'Ремонти и неизправности', 'Заявки и доставки'].indexOf(label)])
  await waitFor(() => expect(fetcher.mock.calls.some(([url]) => url.includes('/reports/requests?'))).toBe(true))
  expect(fetcher.mock.calls.some(([url]) => url.includes('audit'))).toBe(false)
})
it('attention details trap focus, close on Escape and restore the invoking control', async () => {
  render(<I18nProvider><Reports /></I18nProvider>)
  const button = await screen.findByRole('button', { name: 'Виж причините' })
  await userEvent.click(button)
  expect(await screen.findByRole('dialog')).toHaveTextContent('5 регистрирани ремонта')
  await userEvent.keyboard('{Escape}')
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  expect(button).toHaveFocus()
})
it('filters scope machine/category, clear incompatible selections, and reset to 30 days', async () => {
  render(<I18nProvider><Reports /></I18nProvider>)
  await screen.findByRole('button', { name: 'Виж причините' })
  await userEvent.click(screen.getByRole('combobox', { name: bg['machines.category'] }))
  await userEvent.click(await screen.findByRole('option', { name: 'QA category' }))
  await waitFor(() => expect(fetcher.mock.calls.some(([url]) => url.includes('/reports/') && url.includes('category_id=7'))).toBe(true))
  await userEvent.click(screen.getByRole('button', { name: bg['ux.reset'] }))
  await waitFor(() => expect(fetcher.mock.calls.at(-1)?.[0]).not.toContain('category_id=7'))
})
it('both exports receive exactly the active section, dates and language', async () => {
  const { downloadApiFile } = await import('../../api')
  render(<I18nProvider initialLocale="en"><Reports /></I18nProvider>)
  await screen.findByRole('heading', { name: 'Machines requiring attention' })
  await userEvent.click(screen.getByRole('button', { name: 'Download PDF' }))
  await userEvent.click(screen.getByRole('button', { name: 'Download Excel' }))
  expect(downloadApiFile).toHaveBeenCalledWith(expect.stringMatching(/\/reports\/export\/pdf\?.*date_from=.*section=overview.*language=en/), expect.any(String))
  expect(downloadApiFile).toHaveBeenCalledWith(expect.stringContaining('/reports/export/xlsx?'), expect.any(String))
})
it.each([['bg', 'Отчети и анализи'], ['en', 'Reports and analytics'], ['ru', 'Отчёты и аналитика']] as const)('renders complete %s labels', async (locale, title) => {
  render(<I18nProvider initialLocale={locale}><Reports /></I18nProvider>)
  expect(screen.getByRole('heading', { name: title })).toBeVisible()
  await waitFor(() => expect(screen.queryByText('methodText')).not.toBeInTheDocument())
})
it('aborts obsolete analytics and discards responses that arrive late', async () => {
  let resolve!: (value: Response) => void
  const slow = new Promise<Response>(done => { resolve = done })
  fetcher.mockImplementation((url: string) => url.includes('old') ? slow : Promise.resolve(response({ ...report, section: 'current' })))
  function Read({ path }: { path: string }) { const state = useReport(path); return <p>{state.loading ? 'loading' : state.error ? 'error' : state.data?.section}</p> }
  const view = render(<Read path="/reports/old" />)
  view.rerender(<Read path="/reports/new" />)
  expect(await screen.findByText('current')).toBeVisible()
  await act(async () => { resolve(response({ ...report, section: 'obsolete' })) })
  expect(fetcher.mock.calls[0][1]?.signal?.aborted).toBe(true)
  expect(screen.queryByText('obsolete')).not.toBeInTheDocument()
})

it('explains changed export data and refreshes before another download', async () => {
  const { ApiError, downloadApiFile } = await import('../../api')
  vi.mocked(downloadApiFile).mockRejectedValueOnce(new ApiError(409, { code: 'reports_changed_refresh' }))
  render(<I18nProvider initialLocale="bg"><Reports /></I18nProvider>)
  await screen.findByRole('button', { name: 'Виж причините' })
  await userEvent.click(screen.getByRole('button', { name: 'Изтегли PDF' }))
  expect(await screen.findByRole('alert')).toHaveTextContent('Данните са променени')
  await userEvent.click(screen.getByRole('button', { name: 'Опитай отново' }))
  await waitFor(() => expect(fetcher.mock.calls.some(([url]) => url.includes('refresh=1'))).toBe(true))
  expect(screen.queryByRole('alert')).not.toBeInTheDocument()
})

it('loads comparison options on demand and preserves the expanded context', async () => {
  const view = render(<I18nProvider initialLocale="bg"><Reports /></I18nProvider>)
  await screen.findByRole('button', { name: 'Виж причините' })
  expect(fetcher.mock.calls.filter(([url]) => url.includes('/workspace/machines?'))).toHaveLength(1)
  await userEvent.click(screen.getByRole('button', { name: 'Избери машини за сравнение' }))
  await waitFor(() => expect(fetcher.mock.calls.filter(([url]) => url.includes('/workspace/machines?'))).toHaveLength(2))
  view.unmount()
  render(<I18nProvider initialLocale="bg"><Reports /></I18nProvider>)
  expect(await screen.findByRole('button', { name: 'Избери машини за сравнение' })).toHaveAttribute('aria-expanded', 'true')
})
