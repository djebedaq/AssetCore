import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, expect, it, vi } from 'vitest'
import App from '../App'
import { downloadApiFile } from '../api'
import { bg, I18nProvider } from '../i18n'
import { setSessionUser } from '../permissions'
import type { PermissionCode, UserSession } from '../types'
import { AdministrationPanel } from '../features/administration/AdministrationPanel'

vi.mock('../api', async (original) => ({ ...await original<typeof import('../api')>(), downloadApiFile: vi.fn().mockResolvedValue(undefined) }))

const machine = { id: 3, inventory_number: '7', name: 'HPWJ №7', brand: 'Falch', model: 'Wheel Jet 30-e', status: 'READY' }
const passport = { limited_view: true, machine, custom_fields: [], attachments: [], history: [], repairs: [], transfers: [], part_requests: [], parts_used: [], generated_documents: [], technical_documents: [], audit: [], audit_visible: false,
  current_state: { available: true, allowed_actions: { issue: false, return: false, repair: false, edit: false } } }
function fixture(permissions: PermissionCode[]) {
  const user = { id: 1, email: 'shell@example.invalid', role: 'administrator', preferred_language: 'bg', is_active: true,
    is_system_owner: false, must_change_password: false, permissions } as UserSession
  setSessionUser(user)
  const fetchMock = vi.fn(async (input: RequestInfo | URL, _init?: RequestInit) => {
    const path = String(input)
    const data = path.endsWith('/auth/me') ? user
      : path.endsWith('/emergency-access/status') ? { active: false }
      : path.endsWith('/machines') ? [machine]
      : path.endsWith('/machines/3/passport') ? passport
      : path.includes('/search?') ? { query: 'Falch', machines: [machine], parts: [], documents: [], repairs: [], part_requests: [], transfers: [], generated_documents: [] }
      : path.endsWith('/audit') ? [{ id: 1, entity_type: 'machine', entity_id: 3, action: 'TEST_ONLY', created_at: '2026-08-27T10:00:00Z', details: JSON.stringify({ nested_value: { valid: true, list: [7] } }) }]
      : path.endsWith('/admin/reference-data') ? { locations: [], departments: [] }
      : []
    return new Response(JSON.stringify(data), { headers: { 'Content-Type': 'application/json' } })
  })
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}
function renderApp() { return render(<I18nProvider initialLocale="bg"><App /></I18nProvider>) }
afterEach(() => {
  window.history.replaceState({}, '', '/')
  vi.unstubAllGlobals()
  vi.clearAllMocks()
})

it('retains report and audit downloads, nested audit display and filtering through lazy pages', async () => {
  fixture(['assets.view', 'audit.view_operational'])
  renderApp()
  await userEvent.click(await screen.findByRole('button', { name: bg['nav.reports'] }))
  await userEvent.click(await screen.findByRole('button', { name: bg['reports.downloadDaily'] }))
  expect(downloadApiFile).toHaveBeenCalledWith('/reports/daily.pdf', 'assetcore-daily-report.pdf')
  await userEvent.click(screen.getByRole('button', { name: bg['nav.audit'] }))
  expect(await screen.findByText('nested value')).toBeVisible()
  expect(screen.getByText(bg['common.yes'])).toBeVisible()
  await userEvent.type(screen.getByLabelText(bg['audit.search']), 'not-present')
  expect(screen.getByText(bg['audit.empty'])).toBeVisible()
  await userEvent.click(screen.getByRole('button', { name: bg['audit.export'] }))
  expect(downloadApiFile).toHaveBeenCalledWith('/audit/export.json', 'assetcore-audit.json')
})

it('global search opens the original machine passport and closes without navigating or losing the query', async () => {
  const fetchMock = fixture(['assets.view'])
  renderApp()
  await userEvent.type(await screen.findByLabelText(bg['global.search']), 'Falch')
  await userEvent.click(await screen.findByRole('button', { name: /HPWJ №7.*Falch/ }))
  const modal = await screen.findByRole('dialog', { name: /№7/ })
  expect(fetchMock.mock.calls.some(([url]) => String(url) === '/api/search?q=Falch')).toBe(true)
  expect(fetchMock.mock.calls.some(([url]) => String(url) === '/api/machines/3/passport')).toBe(true)
  expect(within(modal).queryByRole('button', { name: bg['passport.tab.history'] })).not.toBeInTheDocument()
  await userEvent.click(within(modal).getByRole('button', { name: bg['common.close'] }))
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  expect(screen.getByLabelText(bg['global.search'])).toHaveValue('Falch')
  expect(window.location.pathname).toBe('/')
})

it('retains /machine/:id deep links for limited observers', async () => {
  fixture(['assets.view'])
  window.history.replaceState({}, '', '/machine/3')
  renderApp()
  const modal = await screen.findByRole('dialog', { name: /№7/ })
  expect(within(modal).queryByRole('img')).not.toBeInTheDocument()
  expect(window.location.pathname).toBe('/machine/3')
})

it('preserves administration permission gating and exact location create payload', async () => {
  const fetchMock = fixture(['assets.view'])
  const { rerender } = render(<I18nProvider initialLocale="bg"><AdministrationPanel /></I18nProvider>)
  expect(fetchMock).not.toHaveBeenCalled()
  const allowedFetch = fixture(['settings.manage'])
  rerender(<I18nProvider initialLocale="bg"><AdministrationPanel key="authorized" /></I18nProvider>)
  await userEvent.click(await screen.findByRole('button', { name: bg['admin.addLocation'] }))
  const modal = screen.getByRole('dialog')
  await userEvent.type(within(modal).getByRole('textbox', { name: bg['admin.locationName'] }), 'QA-only location')
  await userEvent.click(within(modal).getByRole('button', { name: bg['common.save'] }))
  await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
  const request = allowedFetch.mock.calls.find(([url, init]) => String(url) === '/api/admin/locations' && init?.method === 'POST')
  expect(JSON.parse(request?.[1]?.body as string)).toEqual({ name: 'QA-only location', description: '' })
})
