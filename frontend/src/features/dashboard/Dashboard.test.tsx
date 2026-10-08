import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, expect, it, vi } from 'vitest'
import { I18nProvider } from '../../i18n'
import { setSessionUser } from '../../permissions'
import type { UserSession } from '../../types'
import Dashboard, { AnimatedNumber, type DashboardData } from './Dashboard'

afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals() })
const data: DashboardData = {
  total_machines: 3, ready: 2, in_use: 1, open_repairs: 0, pending_parts: 0, status_breakdown: { READY: 2, ISSUED: 1 },
  categories: [{ id: 12, code: 'QA', name_bg: 'QA dynamic category', is_active: true, asset_count: 3, has_pressure: false }], uncategorized_assets: 0,
  recent_repairs: [], recent_activity: [{ event_key: 'QA-operation', event_type: 'TRANSFER_ISSUED', module: 'transfers', record_id: 27, occurred_at: '2026-10-08T09:32:00Z', machine_id: 12, inventory_number: 'QA-12', reference: 'QA protocol', status: 'ISSUED' }],
}
it('renders actual counts, truthful progress and navigates to the original permitted record', async () => {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify(data), { status: 200 })))
  setSessionUser({ permissions: ['transfers.view'] } as UserSession)
  const navigate = vi.fn()
  window.addEventListener('assetcore:operation', navigate)
  render(<I18nProvider><Dashboard /></I18nProvider>)
  expect(screen.getByRole('status')).toHaveTextContent('Зареждане')
  await screen.findByRole('heading', { name: 'Машини по категории' })
  expect(screen.getByText('QA dynamic category')).toBeVisible()
  const meters = screen.getAllByRole('meter')
  expect(meters[0]).toHaveAttribute('aria-valuenow', '2')
  await waitFor(() => expect(meters[0].querySelector('i')?.style.width).toBe(`${2 / 3 * 100}%`))
  await userEvent.click(screen.getByRole('button', { name: /QA protocol/ }))
  expect((navigate.mock.calls[0][0] as CustomEvent).detail).toEqual({ module: 'transfers', recordId: 27, machineId: 12 })
  window.removeEventListener('assetcore:operation', navigate)
})
it('shows final KPI immediately with reduced motion', () => {
  vi.stubGlobal('matchMedia', vi.fn().mockReturnValue({ matches: true }))
  const { container } = render(<AnimatedNumber value={43} />)
  expect(container.querySelector('[aria-hidden=true]')).toHaveTextContent('43')
})
it('handles empty activity and failed loading without invented events', async () => {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({ ...data, recent_activity: [] }), { status: 200 })))
  const { unmount } = render(<Dashboard />)
  await screen.findByText('Все още няма оперативна активност.')
  unmount()
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('{}', { status: 500 })))
  render(<Dashboard />)
  expect(await screen.findByRole('alert')).toBeVisible()
})
