import { act, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, expect, it, vi } from 'vitest'
import App from '../App'
import { I18nProvider } from '../i18n'

const gate = vi.hoisted(() => {
  let release!: () => void
  return { started: vi.fn(), promise: new Promise<void>((resolve) => { release = resolve }), release: () => release() }
})
vi.mock('../features/reports/Reports', async (original) => {
  gate.started()
  await gate.promise
  return original()
})
afterEach(() => vi.unstubAllGlobals())

it('loads reports only on selection; navigating away from a pending import does not resurrect it', async () => {
  vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
    const path = String(input)
    const value = path.endsWith('/auth/me') ? {
      id: 1, role: 'director', preferred_language: 'bg', permissions: ['assets.view', 'reports.view', 'audit.view_operational'],
      is_active: true, is_system_owner: false, must_change_password: false,
    } : path.endsWith('/emergency-access/status') ? { active: false }
      : path.includes('/workspace/machines') ? { items: [], total: 0, page: 1, page_size: 20 }
      : path.includes('/reports/') ? { section: 'overview', generated_at: '2026-10-18T12:00:00Z', filters: { date_from: '2026-09-19', date_to: '2026-10-18' }, previous_filters: { date_from: '2026-08-20', date_to: '2026-09-18' }, capabilities: {}, current: [], metrics: [], attention: [], categories: [], rankings: [], ranking_kind: 'repairs', trends: [], parts: [], articles: [], machines: [], records: { items: [], total: 0, page: 1, page_size: 20, total_pages: 0 } } : []
    return new Response(JSON.stringify(value), { headers: { 'Content-Type': 'application/json' } })
  }))
  render(<I18nProvider initialLocale="bg"><App /></I18nProvider>)
  const reportButton = await screen.findByRole('button', { name: 'Отчети и анализи' })
  expect(gate.started).not.toHaveBeenCalled()
  await userEvent.click(reportButton)
  expect(await screen.findByRole('status')).toHaveTextContent('Зареждане')
  await userEvent.click(screen.getByRole('button', { name: 'Журнал' }))
  expect(await screen.findByRole('button', { name: 'Експорт на одита' })).toBeVisible()
  await act(async () => { gate.release(); await gate.promise })
  expect(screen.getByRole('button', { name: 'Експорт на одита' })).toBeVisible()
  expect(screen.queryByRole('button', { name: 'Изтегли Excel' })).not.toBeInTheDocument()
  await userEvent.click(reportButton)
  expect(await screen.findByRole('button', { name: 'Изтегли Excel' })).toBeVisible()
  expect(gate.started).toHaveBeenCalledTimes(1)
})
