import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import App from './App'
import { I18nProvider } from './i18n'
import { MachinePassportModal } from './IndustrialPlatform'
import { setSessionUser } from './permissions'
import type { PermissionCode, UserSession } from './types'

function session(role: UserSession['role'], permissions: PermissionCode[]): UserSession {
  return {
    id: 10,
    email: `${role}@example.invalid`,
    full_name: 'Role test',
    role,
    preferred_language: 'bg',
    is_active: true,
    is_system_owner: false,
    must_change_password: false,
    permissions,
    created_at: '2026-08-01T00:00:00Z',
    updated_at: '2026-08-01T00:00:00Z',
    last_login_at: null,
    password_changed_at: null,
  }
}

function json(value: unknown): Response {
  return new Response(JSON.stringify(value), { status: 200, headers: { 'Content-Type': 'application/json' } })
}

function renderRole(user: UserSession) {
  setSessionUser(user)
  vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
    const path = String(input)
    if (path.endsWith('/api/auth/me')) return json(user)
    if (path.endsWith('/api/dashboard')) return json({ total_machines: 0, ready: 0, in_use: 0, open_repairs: 0, pending_parts: 0, status_breakdown: {}, recent_repairs: [] })
    return json([])
  }))
  return render(<I18nProvider initialLocale="bg"><App /></I18nProvider>)
}

describe('ролево меню', () => {
  beforeEach(() => localStorage.clear())
  afterEach(() => {
    vi.unstubAllGlobals()
    vi.restoreAllMocks()
  })

  it('не показва потребители и настройки на механика', async () => {
    renderRole(session('mechanic', ['assets.view', 'transfers.view', 'repairs.view', 'parts.view', 'requests.view', 'documents.view']))
    expect(await screen.findByRole('button', { name: 'Машини' })).toBeVisible()
    expect(screen.queryByRole('button', { name: 'Потребители' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Настройки' })).not.toBeInTheDocument()
  })

  it('показва на наблюдателя само изгледа за машини', async () => {
    renderRole(session('observer', ['assets.view']))
    expect(await screen.findByRole('button', { name: 'Машини' })).toBeVisible()
    expect(screen.queryByRole('button', { name: 'Табло' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Приемане / предаване' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Ремонти' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Потребители' })).not.toBeInTheDocument()
    expect(screen.queryByText('Налягане')).not.toBeInTheDocument()
  })

  it('показва ограничен паспорт без QR, сериен номер и история', async () => {
    setSessionUser(session('observer', ['assets.view']))
    vi.stubGlobal('fetch', vi.fn(async () => json({
      limited_view: true,
      machine: { id: 1, inventory_number: 'TEST-ONLY', name: 'Test only', brand: 'Test', model: null, status: 'READY', location: { id: 1, name: 'Test location' } },
      current_state: { available: true, allowed_actions: { issue: false, return: false, repair: false, edit: false } },
      custom_fields: [], repairs: [], transfers: [], part_requests: [], generated_documents: [], technical_documents: [], history: [], parts_used: [], attachments: [], audit: [], audit_visible: false,
    })))
    render(<I18nProvider initialLocale="bg"><MachinePassportModal machineId={1} onClose={vi.fn()} /></I18nProvider>)
    expect(await screen.findByText('Test location')).toBeVisible()
    expect(screen.queryByText('Сериен номер')).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'История' })).not.toBeInTheDocument()
    expect(document.querySelector('img')).toBeNull()
  })

  it('заключва background scroll и пази отделна touch-scroll област за цялото mobile меню', async () => {
    vi.spyOn(window, 'scrollX', 'get').mockReturnValue(0)
    vi.spyOn(window, 'scrollY', 'get').mockReturnValue(480)
    const scrollTo = vi.fn()
    vi.stubGlobal('scrollTo', scrollTo)
    const user = userEvent.setup()
    renderRole(session('administrator', [
      'assets.view', 'transfers.view', 'repairs.view', 'parts.view', 'requests.view',
      'documents.view', 'documents.generate', 'audit.view_operational', 'users.view',
      'settings.manage',
    ]))

    await user.click(await screen.findByRole('button', { name: 'Отвори' }))
    const sidebar = document.querySelector<HTMLElement>('.sidebar') as HTMLElement
    const navigation = document.querySelector<HTMLElement>('.sidebar-navigation') as HTMLElement

    expect(sidebar).toHaveClass('open')
    expect(document.body.style.position).toBe('fixed')
    expect(document.body.style.top).toBe('-480px')
    expect(navigation.contains(screen.getByRole('button', { name: 'Настройки' }))).toBe(true)

    fireEvent.touchStart(navigation, { touches: [{ clientY: 700 }] })
    navigation.scrollTop = 320
    fireEvent.touchMove(navigation, { touches: [{ clientY: 200 }] })
    fireEvent.scroll(navigation)
    expect(navigation.scrollTop).toBe(320)
    expect(document.body.style.top).toBe('-480px')

    await user.click(document.querySelector<HTMLButtonElement>('.sidebar-backdrop') as HTMLButtonElement)
    expect(sidebar).not.toHaveClass('open')
    expect(document.body.style.position).toBe('')
    await waitFor(() => expect(scrollTo).toHaveBeenCalledTimes(2))
    expect(scrollTo).toHaveBeenLastCalledWith(0, 480)
  })
})
