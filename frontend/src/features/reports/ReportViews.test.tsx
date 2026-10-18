import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, expect, it, vi } from 'vitest'
import { I18nProvider, bg } from '../../i18n'
import { Records, ReportTabs } from './ReportViews'
import labels from './labels.json'
import type { Asset, RecordRow } from './reportData'

const asset = { id: 100, inventory_number: 'QA-100', name: 'Synthetic QA', brand: 'QA', status: 'READY' } as Asset
const event = '2026-10-14T12:00:00Z', start = '2026-08-01T12:00:00Z'
const format = (value: string) => new Intl.DateTimeFormat('bg', { timeZone: 'Europe/Sofia', dateStyle: 'medium', timeStyle: 'short' }).format(new Date(value))
const page = (items: RecordRow[]) => ({ items, page: 1, page_size: 20, total: items.length, total_pages: 1, has_next: false, has_previous: false })
afterEach(() => { cleanup(); vi.unstubAllGlobals(); vi.restoreAllMocks() })

it.each([
  ['usage', 'completed_cycles', 'returned_at'],
  ['repairs', 'closed', 'closed_at'],
  ['requests', 'ordered', 'ordered_at'],
  ['requests', 'delivered', 'delivered_at'],
  ['requests', 'approved', 'approved_at'],
  ['requests', 'rejected', 'rejected_at'],
  ['usage', 'issues', 'issued_at'],
  ['repairs', 'opened', 'opened_at'],
  ['requests', 'created', 'created_at'],
  ['repairs', 'current_repairs', 'as_of'],
] as const)('shows the %s/%s event date and date heading', (kind, metric, basis) => {
  render(<I18nProvider><Records kind={kind} metric={metric} params={{}} onPassport={vi.fn()} initial={page([{ id: 1, machine: asset, issued_at: start, opened_at: start, created_at: start, metric_date: event, date_basis: basis }])} /></I18nProvider>)
  expect(screen.getByRole('columnheader', { name: labels[basis][0] })).toBeVisible()
  const dateCell = screen.getAllByRole('row')[1].children[2]
  expect(dateCell).toHaveTextContent(format(event))
  expect(dateCell).not.toHaveTextContent(format(start))
})

it('does not replace a missing metric date with a different historical timestamp', () => {
  render(<I18nProvider><Records kind="requests" metric="delivered" params={{}} onPassport={vi.fn()} initial={page([{ id: 1, created_at: start, metric_date: null, date_basis: 'delivered_at' }])} /></I18nProvider>)
  expect(screen.getAllByRole('row')[1].children[2]).toHaveTextContent('—')
  expect(screen.queryByText(format(start))).not.toBeInTheDocument()
})

it('passes the selected metric and oldest sort to the paginated endpoint', async () => {
  const fetcher = vi.fn<(url: string) => Promise<Response>>(async () => new Response(JSON.stringify(page([])), { status: 200 }))
  vi.stubGlobal('fetch', fetcher)
  render(<I18nProvider><Records kind="repairs" metric="closed" params={{ category_id: 7 }} onPassport={vi.fn()} initial={page([])} /></I18nProvider>)
  await userEvent.click(screen.getByRole('combobox', { name: bg['ux.sort'] }))
  await userEvent.click(screen.getByRole('option', { name: bg['ux.oldest'] }))
  await waitFor(() => expect(fetcher).toHaveBeenCalled())
  const url = new URL(fetcher.mock.calls[0][0] as string, 'http://localhost')
  expect(Object.fromEntries(url.searchParams)).toMatchObject({ kind: 'repairs', metric: 'closed', sort: 'oldest', page: '1', category_id: '7' })
})

it('shows one unique machine and opens its two issues with the same filters', async () => {
  const fetcher = vi.fn<(url: string) => Promise<Response>>(async () => new Response(JSON.stringify(page([{ id: 201, protocol_number: 'QA-CYCLE-1' }, { id: 202, protocol_number: 'QA-CYCLE-2' }])), { status: 200 }))
  vi.stubGlobal('fetch', fetcher)
  render(<I18nProvider><Records kind="usage" metric="unique_issued" params={{ category_id: 7, date_from: '2026-10-01', date_to: '2026-10-18', q: 'QA' }} onPassport={vi.fn()} initial={page([{ id: asset.id, machine_id: asset.id, machine: asset, issue_count: 2, metric_date: event, date_basis: 'last_issued_at' }])} /></I18nProvider>)
  expect(screen.getAllByRole('row')).toHaveLength(2)
  const button = screen.getByRole('button', { name: 'Виж издаванията (2)' })
  await userEvent.click(button)
  const details = await screen.findByRole('region', { name: 'Индивидуални издавания · №QA-100' })
  await waitFor(() => expect(within(details).getAllByRole('row')).toHaveLength(3))
  const url = new URL(fetcher.mock.calls[0][0] as string, 'http://localhost')
  expect(Object.fromEntries(url.searchParams)).toMatchObject({ kind: 'usage', metric: 'issues', machine_id: '100', category_id: '7', date_from: '2026-10-01', date_to: '2026-10-18', q: 'QA' })
  expect(button).toHaveAttribute('aria-expanded', 'true')
  await userEvent.click(screen.getByRole('button', { name: 'Скрий издаванията' }))
  expect(button).toHaveFocus()
  expect(screen.queryByRole('region', { name: 'Индивидуални издавания · №QA-100' })).not.toBeInTheDocument()
  expect(screen.getAllByRole('row')).toHaveLength(2)
})

it('offers accessible overflow arrows only while directions are hidden', async () => {
  render(<I18nProvider><ReportTabs tabs={['overview', 'usage', 'repairs', 'requests']} active="overview" onSelect={vi.fn()} /></I18nProvider>)
  const nav = screen.getByRole('navigation', { name: 'Отчети и анализи' })
  let width = 240
  Object.defineProperty(nav, 'clientWidth', { configurable: true, get: () => width })
  Object.defineProperty(nav, 'scrollWidth', { configurable: true, get: () => 660 })
  nav.scrollBy = vi.fn(options => { nav.scrollLeft = Math.min(420, Math.max(0, nav.scrollLeft + (typeof options === 'object' ? options.left || 0 : 0))); fireEvent.scroll(nav) })
  fireEvent(window, new Event('resize'))
  expect(await screen.findByRole('button', { name: 'Следващи направления' })).toBeEnabled()
  expect(screen.getByRole('button', { name: 'Предходни направления' })).toBeDisabled()
  expect(nav).toHaveAccessibleDescription(labels.moreDirections[0])
  const last = within(nav).getByRole('button', { name: 'Заявки и доставки' })
  last.scrollIntoView = vi.fn()
  fireEvent.focus(last)
  expect(last.scrollIntoView).toHaveBeenCalledWith({ block: 'nearest', inline: 'nearest', behavior: 'auto' })
  for (let i = 0; i < 3; i++) await userEvent.click(screen.getByRole('button', { name: 'Следващи направления' }))
  expect(screen.getByRole('button', { name: 'Следващи направления' })).toBeDisabled()
  expect(screen.getByRole('button', { name: 'Предходни направления' })).toBeEnabled()
  expect(nav.scrollBy).toHaveBeenCalledWith({ left: 192, behavior: 'auto' })
  width = 1000; nav.scrollLeft = 0; fireEvent(window, new Event('resize'))
  expect(screen.queryByRole('button', { name: 'Следващи направления' })).not.toBeInTheDocument()
})
