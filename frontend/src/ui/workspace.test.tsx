import { useState } from 'react'
import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, expect, it, vi } from 'vitest'
import { I18nProvider, bg } from '../i18n'
import { clearSessionUser, setSessionUser } from '../permissions'
import type { UserSession } from '../types'
import { CategorySelect, MachineSelect, queryParams, usePage, useWorkspaceFilters } from './workspace'
import Transfers from '../features/transfers/Transfers'
import { IndustrialRepairs } from '../features/repairs/IndustrialRepairs'

const categories = [1, 2].map(id => ({ id, code: `QA_${id}`, name_bg: `QA category ${id}`, is_active: true, asset_count: 1, has_pressure: false }))
const response = (value: unknown) => new Response(JSON.stringify(value), { status: 200 })
const page = (items: unknown[]) => ({ items, total: items.length, page: 1, page_size: 25, total_pages: 1, has_previous: false, has_next: false })
afterEach(() => { cleanup(); clearSessionUser(); vi.unstubAllGlobals(); vi.restoreAllMocks() })
function authorized() { setSessionUser({ permissions: ['transfers.view', 'repairs.view'] } as UserSession) }
function Harness() {
  const filters = useWorkspaceFilters()
  const [value, setValue] = useState('')
  return <><CategorySelect categories={categories} value={filters.values.category} all={false} onChange={category => { filters.change('category', category); setValue('') }} />
    <MachineSelect module="catalog" category={filters.values.category} value={value} onChange={setValue} disabled={!filters.values.category} /></>
}
it('category selection scopes the server machine search and clears an incompatible asset', async () => {
  const fetch = vi.fn(async (url: string) => {
    const query = new URL(url, 'http://qa').searchParams
    const id = Number(query.get('category_id') || 1)
    const machine = { id, inventory_number: `QA-${id}`, name: `QA asset ${id}`, brand: 'QA', category_id: id }
    return response(url.includes('/workspace/machines') ? page([machine]) : machine)
  })
  vi.stubGlobal('fetch', fetch)
  render(<I18nProvider><Harness /></I18nProvider>)
  expect(screen.getByRole('combobox', { name: bg['common.machine'] })).toBeDisabled()
  await userEvent.click(screen.getByRole('combobox', { name: bg['machines.category'] }))
  await userEvent.click(screen.getByRole('option', { name: 'QA category 1' }))
  await waitFor(() => expect(fetch.mock.calls.some(([url]) => url.includes('category_id=1'))).toBe(true))
  await userEvent.click(screen.getByRole('combobox', { name: bg['common.machine'] }))
  await userEvent.click(await screen.findByRole('option', { name: /QA asset 1/ }))
  await userEvent.click(screen.getByRole('combobox', { name: bg['machines.category'] }))
  await userEvent.click(screen.getByRole('option', { name: 'QA category 2' }))
  await waitFor(() => expect(fetch.mock.calls.some(([url]) => url.includes('category_id=2'))).toBe(true))
  expect(screen.getByRole('combobox', { name: bg['common.machine'] })).not.toHaveTextContent('QA asset 1')
  await userEvent.click(screen.getByRole('combobox', { name: bg['common.machine'] }))
  expect(await screen.findByRole('option', { name: /QA asset 2/ })).toBeVisible()
  expect(screen.queryByRole('option', { name: /QA asset 1/ })).not.toBeInTheDocument()
})

it('aborts old pages and ignores late results, including empty and failed states', async () => {
  let resolve!: (value: Response) => void
  const old = new Promise<Response>(done => { resolve = done })
  const fetch = vi.fn((url: string, init?: RequestInit) => { void init; return url.includes('old') ? old : Promise.resolve(response(page(['current']))) })
  vi.stubGlobal('fetch', fetch)
  function Read({ path }: { path: string }) { const { data, error, loading } = usePage<string>(path); return <div>{error ? 'QA failure' : loading ? 'QA loading' : data?.items.join(',') || 'QA empty'}</div> }
  const view = render(<Read path="/old" />)
  view.rerender(<Read path="/new" />)
  expect(await screen.findByText('current')).toBeVisible()
  resolve(response(page(['stale'])))
  await waitFor(() => expect(fetch.mock.calls[0][1]?.signal?.aborted).toBe(true))
  expect(screen.queryByText('stale')).not.toBeInTheDocument()
  fetch.mockImplementation(() => Promise.resolve(response(page([]))))
  view.rerender(<Read path="/empty" />)
  expect(await screen.findByText('QA empty')).toBeVisible()
  fetch.mockImplementation(() => Promise.resolve(new Response('{}', { status: 500 })))
  view.rerender(<Read path="/failure" />)
  expect(await screen.findByText('QA failure')).toBeVisible()
})

it('transfer contexts request separately bounded active and completed data without the old archive read', async () => {
  authorized()
  const fetch = vi.fn(async (url: string) => response(url.includes('/workspace/categories') ? categories : url.includes('/workspace/') ? page([]) : []))
  vi.stubGlobal('fetch', fetch)
  render(<I18nProvider><Transfers /></I18nProvider>)
  expect(await screen.findByText(bg['ux.emptyActive'])).toBeVisible()
  await userEvent.click(screen.getByRole('button', { name: bg['ux.completedBatches'] }))
  expect(await screen.findByText(bg['ux.emptyCompleted'])).toBeVisible()
  expect(fetch.mock.calls.some(([url]) => url.includes('context=active'))).toBe(true)
  expect(fetch.mock.calls.some(([url]) => url.includes('context=completed'))).toBe(true)
  expect(fetch.mock.calls.some(([url]) => url.startsWith('/api/transfer-batches?'))).toBe(false)
})

it('repair filters change the actual API query and reset all transient values', async () => {
  authorized()
  const fetch = vi.fn(async (url: string) => response(url.includes('/workspace/categories') ? categories : page([])))
  vi.stubGlobal('fetch', fetch)
  render(<I18nProvider><IndustrialRepairs /></I18nProvider>)
  await userEvent.click(screen.getByRole('combobox', { name: bg['machines.category'] }))
  await userEvent.click(await screen.findByRole('option', { name: 'QA category 2' }))
  await userEvent.type(screen.getByRole('textbox', { name: bg['common.search'] }), 'QA protocol')
  await userEvent.type(screen.getByLabelText(bg['ux.from']), '2026-10-01')
  await waitFor(() => expect(fetch.mock.calls.some(([url]) => url.includes('category_id=2') && url.includes('q=QA+protocol') && url.includes('date_from=2026-10-01'))).toBe(true))
  await userEvent.click(screen.getByRole('button', { name: bg['ux.reset'] }))
  await waitFor(() => expect(fetch.mock.calls.at(-1)?.[0]).toBe(`/api/workspace/repairs?${queryParams({ sort: 'newest', page: 1 })}`))
  expect(screen.getByRole('textbox', { name: bg['common.search'] })).toHaveValue('')
})
