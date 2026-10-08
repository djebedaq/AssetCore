import { cleanup, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { I18nProvider } from '../../i18n'
import { clearSessionUser, setSessionUser } from '../../permissions'
import type { UserSession } from '../../types'
import Transfers from './Transfers'

beforeEach(() => setSessionUser({ permissions: ['assets.view', 'transfers.view'], preferred_language: 'bg' } as UserSession))
afterEach(() => { cleanup(); vi.unstubAllGlobals(); clearSessionUser() })

it('keeps active unbatched legacy records reachable while completed batch history stays separate', async () => {
  const calls: URL[] = []
  vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
    const url = new URL(String(input), 'https://qa.invalid')
    calls.push(url)
    const items = url.pathname === '/api/workspace/transfers' ? [{
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
  await userEvent.click(screen.getByRole('button', { name: 'Записи по машини' }))
  const row = await screen.findByRole('row', { name: /QA-LEGACY-ACTIVE/ })
  expect(within(row).getByText('QA legacy asset')).toBeVisible()
  expect(row.querySelector('[data-status="ACTIVE"]')).toBeVisible()
  expect(calls.filter(url => url.pathname === '/api/workspace/transfers').every(url => !url.searchParams.has('status'))).toBe(true)
  await userEvent.click(screen.getByRole('button', { name: 'Индивидуална история' }))
  await waitFor(() => expect(screen.queryByText('QA-LEGACY-ACTIVE')).not.toBeInTheDocument())
  expect(calls.some(url => url.pathname === '/api/workspace/batches' && url.searchParams.get('context') === 'completed')).toBe(true)
})
