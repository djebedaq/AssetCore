import { render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import App from './App'
import { I18nProvider } from './i18n'
import { MachinePassportModal } from './IndustrialPlatform'
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
  localStorage.setItem('assetcore_token', 'test-token')
  localStorage.setItem('assetcore_user', JSON.stringify(user))
  vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
    const path = String(input)
    if (path.endsWith('/api/dashboard')) return json({ total_machines: 0, ready: 0, in_use: 0, open_repairs: 0, pending_parts: 0, status_breakdown: {}, recent_repairs: [] })
    return json([])
  }))
  return render(<I18nProvider initialLocale="bg"><App /></I18nProvider>)
}

describe('ролево меню', () => {
  beforeEach(() => localStorage.clear())
  afterEach(() => vi.unstubAllGlobals())

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
    localStorage.setItem('assetcore_user', JSON.stringify(session('observer', ['assets.view'])))
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
})
