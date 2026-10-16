import { cleanup, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { bg, I18nProvider } from '../../i18n'
import { clearSessionUser, setSessionUser } from '../../permissions'
import type { UserSession } from '../../types'
import Transfers from './Transfers'

beforeEach(() => setSessionUser({ permissions: ['assets.view', 'transfers.view'], preferred_language: 'bg' } as UserSession))
afterEach(() => { cleanup(); vi.unstubAllGlobals(); clearSessionUser(); window.history.replaceState(null, '', '/') })

it('keeps active unbatched legacy records reachable while completed batch history stays separate', async () => {
  const calls: URL[] = []
  vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
    const url = new URL(String(input), 'https://qa.invalid')
    calls.push(url)
    const items = url.pathname === '/api/workspace/transfers' && url.searchParams.get('status') !== 'completed' ? [{
      id: 7, protocol_number: 'QA-LEGACY-ACTIVE', batch_id: null, batch_reference: null,
      is_active: true, issue_status: 'COMPLETED', return_status: null,
      issued_at: '2026-10-01T12:00:00Z', created_at: '2026-10-01T12:00:00Z',
      machine: { id: 1, name: 'QA legacy asset', inventory_number: 'QA-1', brand: 'QA' },
    }] : []
    const value = ['/api/workspace/categories', '/api/transfers/availability', '/api/locations'].includes(url.pathname)
      ? [] : { items, total: items.length, page: 1, page_size: 25, total_pages: items.length ? 1 : 0, has_previous: false, has_next: false }
    return new Response(JSON.stringify(value), { status: 200, headers: { 'Content-Type': 'application/json' } })
  }))
  render(<I18nProvider initialLocale="bg"><Transfers /></I18nProvider>)
  expect(screen.getAllByRole('tab')).toHaveLength(2)
  await userEvent.selectOptions(screen.getByLabelText('Показване'), 'all')
  const row = await screen.findByRole('row', { name: /QA-LEGACY-ACTIVE/ })
  expect(within(row).getByText('QA legacy asset')).toBeVisible()
  expect(row.querySelector('[data-status="ACTIVE"]')).toBeVisible()
  expect(calls.filter(url => url.pathname === '/api/workspace/transfers').every(url => !url.searchParams.has('status'))).toBe(true)
  await userEvent.click(screen.getByRole('tab', { name: 'История по машини' }))
  await waitFor(() => expect(screen.queryByText('QA-LEGACY-ACTIVE')).not.toBeInTheDocument())
  expect(calls.some(url => url.pathname === '/api/workspace/transfers' && url.searchParams.get('status') === 'completed')).toBe(true)
})

function page(items: unknown[], pageNumber = 1, total = items.length) {
  return { items, total, page: pageNumber, page_size: 1, total_pages: total, has_previous: pageNumber > 1, has_next: pageNumber < total }
}
function cycle(id = 7) {
  return { id, protocol_number: `QA-ISSUE-${id}`, batch_id: 11, batch_reference: 'QA-A',
    is_active: false, issue_status: 'COMPLETED', return_status: 'COMPLETED',
    issued_at: '2026-10-01T12:00:00Z', returned_at: '2026-10-02T12:00:00Z',
    machine: { id: 1, name: 'QA cycle asset', inventory_number: 'QA-7', brand: 'QA', model: 'QA', category_id: 1 },
    documents: [{ document_type: 'TRANSFER_ISSUE', document_number: `QA-ISSUE-${id}`, official_document_id: id,
      created_at: '2026-10-01T12:00:00Z', version: 1, files: [{ format: 'pdf', download_endpoint: `/official-documents/${id}/versions/1/download/pdf` }] },
      { document_type: 'TRANSFER_RETURN', document_number: `QA-RETURN-${id}`, official_document_id: id + 100,
      created_at: '2026-10-02T12:00:00Z', version: 1, files: [{ format: 'docx', download_endpoint: `/official-documents/${id + 100}/versions/1/download/docx` }] }] }
}
function mockWorkspace(resolver: (url: URL) => unknown) {
  const calls: URL[] = []
  vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
    const url = new URL(String(input), 'https://qa.invalid'); calls.push(url)
    return new Response(JSON.stringify(resolver(url)), { status: 200, headers: { 'Content-Type': 'application/json' } })
  }))
  return calls
}

it('pages completed cycles on the server and opens only the chosen cycle with archived files and focus recovery', async () => {
  const calls = mockWorkspace(url => {
    if (url.pathname === '/api/workspace/transfers/8') return cycle(8)
    if (url.pathname === '/api/workspace/transfers') return url.searchParams.get('page') === '2' ? page([cycle(8)], 2, 2) : page([cycle(7)], 1, 2)
    if (url.pathname === '/api/workspace/batches' || url.pathname === '/api/workspace/machines') return page([])
    return []
  })
  render(<I18nProvider initialLocale="bg"><Transfers /></I18nProvider>)
  await userEvent.click(screen.getByRole('tab', { name: 'История по машини' }))
  await screen.findByText('QA-ISSUE-7')
  await userEvent.click(screen.getByRole('button', { name: 'Следваща страница' }))
  const row = await screen.findByRole('row', { name: /QA-ISSUE-8/ })
  const trigger = within(row).getByRole('button', { name: 'Детайли' })
  await userEvent.click(trigger)
  const dialog = await screen.findByRole('dialog', { name: 'Детайли на цикъл' })
  expect(await within(dialog).findByText('QA-RETURN-8')).toBeVisible()
  expect(within(dialog).queryByText('QA-ISSUE-7')).not.toBeInTheDocument()
  expect(within(dialog).getAllByRole('button', { name: 'PDF' })).toHaveLength(1)
  expect(within(dialog).getAllByRole('button', { name: 'DOCX' })).toHaveLength(1)
  expect(within(dialog).getByRole('button', { name: 'Преглед' })).toBeVisible()
  expect(calls.some(url => url.pathname === '/api/transfer-batches/11')).toBe(false)
  expect(within(dialog).getByRole('button', { name: 'Затвори' })).toHaveFocus()
  await userEvent.tab({ shift: true })
  expect(within(dialog).getByRole('button', { name: 'DOCX' })).toHaveFocus()
  await userEvent.tab()
  expect(within(dialog).getByRole('button', { name: 'Затвори' })).toHaveFocus()
  await userEvent.keyboard('{Escape}')
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  expect(trigger).toHaveFocus()
  expect(document.body.style.overflow).toBe('')
  expect(calls.some(url => url.searchParams.get('status') === 'completed' && url.searchParams.get('page') === '2')).toBe(true)
})

it('opens a batch in a modal and leaves the page list compact', async () => {
  const batch = { batch_id: 11, batch_reference: 'QA-A', status: 'PARTIALLY_RETURNED', total_machines: 3,
    returned_machines: 2, still_issued_machines: 1, awaiting_signature_machines: 0, machine_numbers: ['QA-7','QA-8','QA-10'],
    category_ids: [], mixed_categories: false, registered_machines: 3, created_at: '2026-10-01T12:00:00Z',
    transfers: [], zip_download_endpoint: '/transfer-batches/11/documents.zip' }
  mockWorkspace(url => url.pathname === '/api/workspace/batches' ? page([batch]) : url.pathname === '/api/transfer-batches/11' ? batch : url.pathname === '/api/workspace/machines' ? page([]) : [])
  const { container } = render(<I18nProvider initialLocale="bg"><Transfers /></I18nProvider>)
  await userEvent.click(await screen.findByRole('button', { name: 'Детайли' }))
  const dialog = await screen.findByRole('dialog', { name: 'Детайли на партида' })
  expect(await within(dialog).findByText('QA-A')).toBeVisible()
  expect(container.querySelector('.batch-list .batch-details')).toBeNull()
  expect(within(dialog).getByText('Върнати: 2 · Все още издадени: 1 · Общо: 3')).toBeVisible()
  await userEvent.keyboard('{Escape}')
  expect(screen.getAllByRole('tab')).toHaveLength(2)
})

it('restores a direct cycle link after remount and ignores a late response after closing', async () => {
  window.history.replaceState(null, '', '/transfers?record_id=7')
  let resolve!: (value: Response) => void
  vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
    const url = new URL(String(input), 'https://qa.invalid')
    if (url.pathname === '/api/workspace/transfers/7') return new Promise<Response>(done => { resolve = done })
    return new Response(JSON.stringify(url.pathname === '/api/workspace/transfers' || url.pathname === '/api/workspace/machines' ? page([]) : []), { status: 200 })
  }))
  render(<I18nProvider initialLocale="bg"><Transfers /></I18nProvider>)
  const dialog = screen.getByRole('dialog', { name: 'Детайли на цикъл' })
  expect(within(dialog).getByRole('status')).toHaveTextContent('Зареждане')
  await userEvent.keyboard('{Escape}')
  resolve(new Response(JSON.stringify(cycle(7)), { status: 200 }))
  await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
  expect(window.location.search).not.toContain('record_id')
})

it('keeps completed batches and their cancelled return operations reachable through the secondary control', async () => {
  const operation = { batch_id: 12, batch_reference: 'QA-CANCELLED-RETURN', created_at: '2026-10-01T12:00:00Z',
    status: 'CANCELLED', signing_status: 'CANCELLED', machine_numbers: ['QA-7'], transfer_ids: [7], issue_batch_ids: [11], signing_document_id: 90, batch_manifest_sha256: null }
  const batch = { batch_id: 11, batch_reference: 'QA-COMPLETED', status: 'RETURNED', total_machines: 1,
    returned_machines: 1, still_issued_machines: 0, awaiting_signature_machines: 0, machine_numbers: ['QA-7'],
    category_ids: [], mixed_categories: false, registered_machines: 1, created_at: '2026-10-01T12:00:00Z',
    transfers: [], return_operations: [operation], zip_download_endpoint: '/transfer-batches/11/documents.zip' }
  const calls = mockWorkspace(url => url.pathname === '/api/workspace/batches' ? page(url.searchParams.get('context') === 'all' ? [batch] : []) : url.pathname === '/api/transfer-batches/11' ? batch : url.pathname === '/api/workspace/machines' ? page([]) : [])
  render(<I18nProvider initialLocale="bg"><Transfers /></I18nProvider>)
  await userEvent.selectOptions(screen.getByLabelText('Показване'), 'all_batches')
  await userEvent.click(await screen.findByRole('button', { name: 'Детайли' }))
  expect(await screen.findByText(/QA-CANCELLED-RETURN/)).toBeVisible()
  expect(screen.getAllByRole('tab')).toHaveLength(2)
  expect(calls.some(url => url.pathname === '/api/workspace/batches' && url.searchParams.get('context') === 'all')).toBe(true)
})

it('refreshes availability exactly once after cancellation from the main workspace', async () => {
  setSessionUser({ permissions: ['assets.view', 'transfers.view', 'transfers.create', 'transfers.return'], preferred_language: 'bg' } as UserSession)
  let cancelled = false
  const batch = { batch_id: 11, batch_reference: 'QA-PENDING', status: 'AWAITING_SIGNATURE', total_machines: 0,
    returned_machines: 0, still_issued_machines: 0, awaiting_signature_machines: 1, machine_numbers: ['QA-7'],
    category_ids: [], mixed_categories: false, registered_machines: 1, created_at: '2026-10-01T12:00:00Z',
    operation: 'ISSUE', transfers: [], cancellable_batch_ids: [11], zip_download_endpoint: '/transfer-batches/11/documents.zip' }
  const calls = mockWorkspace(url => {
    if (url.pathname.endsWith('/cancel')) { cancelled = true; return { batch_id: 11, batch_reference: 'QA-PENDING', status: 'CANCELLED', cancelled_transfers: 1, invalidated_signing_sessions: 2, message: 'QA' } }
    if (url.pathname === '/api/transfer-batches/11') return batch
    if (url.pathname === '/api/workspace/batches') return page(cancelled ? [] : [batch])
    return url.pathname === '/api/workspace/machines' ? page([]) : []
  })
  render(<I18nProvider initialLocale="bg"><Transfers /></I18nProvider>)
  await userEvent.click(await screen.findByRole('button', { name: bg['bulk.cancelPendingAction'] }))
  const dialog = await screen.findByRole('dialog')
  await userEvent.type(within(dialog).getByLabelText(bg['bulk.cancelReason']), 'QA cancellation reason')
  await userEvent.click(within(dialog).getByRole('button', { name: bg['bulk.cancelConfirm'] }))
  await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
  await waitFor(() => expect(calls.filter(url => url.pathname === '/api/transfers/availability')).toHaveLength(2))
})
