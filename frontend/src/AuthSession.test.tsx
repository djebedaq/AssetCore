import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import App from './App'
import { api } from './api'
import { I18nProvider } from './i18n'
import type { UserSession } from './types'

const session: UserSession = {
  id: 8,
  email: 'session-test@example.invalid',
  full_name: 'Тестова Браузър Сесия',
  first_name: 'Тестова',
  middle_name: 'Браузър',
  last_name: 'Сесия',
  job_title: 'QA',
  profile_status: 'PROFILE_COMPLETE',
  role: 'observer',
  preferred_language: 'bg',
  is_active: true,
  is_system_owner: false,
  must_change_password: false,
  permissions: ['assets.view'],
  created_at: '2026-08-26T08:00:00Z',
  updated_at: '2026-08-26T08:00:00Z',
}

function json(value: unknown, status = 200): Response {
  return new Response(JSON.stringify(value), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

function appFetch(options: { bootstrap?: number } = {}) {
  return vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const path = String(input)
    if (path.endsWith('/api/auth/me')) {
      return options.bootstrap === 401
        ? json({ detail: { code: 'invalid_session', message: 'expired' } }, 401)
        : json(session)
    }
    if (path.endsWith('/api/auth/login') && init?.method === 'POST') {
      return json({ user: session })
    }
    if (path.endsWith('/api/auth/logout') && init?.method === 'POST') {
      return new Response(null, { status: 204 })
    }
    if (path.endsWith('/api/emergency-access/status')) {
      return json({ active: false, mfa_verified: false, message: '' })
    }
    if (path.endsWith('/api/protected-expired')) {
      return json({ detail: { code: 'invalid_session', message: 'expired' } }, 401)
    }
    return json([])
  })
}

describe('защитена браузърна сесия', () => {
  beforeEach(() => {
    localStorage.clear()
    document.cookie = 'assetcore_csrf=; Max-Age=0; Path=/'
  })

  afterEach(() => {
    vi.unstubAllGlobals()
    vi.restoreAllMocks()
  })

  it('adds credentials and CSRF centrally without an Authorization bearer header', async () => {
    document.cookie = 'assetcore_csrf=csrf-test-value; Path=/'
    const fetchMock = vi.fn(async (_input: RequestInfo | URL, _init?: RequestInit) => json({ preferred_language: 'en' }))
    vi.stubGlobal('fetch', fetchMock)

    await api('/users/me/preferences', {
      method: 'PATCH',
      body: JSON.stringify({ preferred_language: 'en' }),
    })

    const init = fetchMock.mock.calls[0][1] as RequestInit
    const headers = init.headers as Headers
    expect(init.credentials).toBe('same-origin')
    expect(headers.get('X-CSRF-Token')).toBe('csrf-test-value')
    expect(headers.get('Authorization')).toBeNull()
  })

  it('restores the authoritative user from the server and removes legacy auth storage', async () => {
    localStorage.setItem('assetcore_token', 'legacy-token')
    localStorage.setItem('assetcore_user', JSON.stringify({ permissions: ['settings.manage'] }))
    const fetchMock = appFetch()
    vi.stubGlobal('fetch', fetchMock)

    render(<I18nProvider initialLocale="bg"><App /></I18nProvider>)

    expect(await screen.findByRole('button', { name: 'Машини' })).toBeVisible()
    expect(localStorage.getItem('assetcore_token')).toBeNull()
    expect(localStorage.getItem('assetcore_user')).toBeNull()
    const bootstrap = fetchMock.mock.calls.find(([input]) => String(input).endsWith('/api/auth/me'))
    expect(bootstrap).toBeDefined()
    expect((bootstrap?.[1] as RequestInit).credentials).toBe('same-origin')
  })

  it('logs in without receiving or storing a browser bearer token', async () => {
    const fetchMock = appFetch({ bootstrap: 401 })
    vi.stubGlobal('fetch', fetchMock)
    render(<I18nProvider initialLocale="bg"><App /></I18nProvider>)

    await userEvent.type(await screen.findByLabelText('Имейл'), session.email)
    await userEvent.type(screen.getByLabelText('Парола'), 'BrowserSession123!')
    await userEvent.click(screen.getByRole('button', { name: 'Вход' }))

    expect(await screen.findByRole('button', { name: 'Машини' })).toBeVisible()
    expect(localStorage.getItem('assetcore_token')).toBeNull()
    const loginCall = fetchMock.mock.calls.find(([input]) => String(input).endsWith('/api/auth/login'))
    const headers = (loginCall?.[1] as RequestInit).headers as Headers
    expect(headers.get('Authorization')).toBeNull()
    expect(headers.get('X-AssetCore-Auth-Mode')).toBeNull()
  })

  it('sends the CSRF token on logout and moves to unauthenticated state', async () => {
    document.cookie = 'assetcore_csrf=logout-csrf; Path=/'
    const fetchMock = appFetch()
    vi.stubGlobal('fetch', fetchMock)
    render(<I18nProvider initialLocale="bg"><App /></I18nProvider>)

    await userEvent.click(await screen.findByRole('button', { name: 'Изход' }))
    expect(await screen.findByRole('button', { name: 'Вход' })).toBeVisible()
    const logoutCall = fetchMock.mock.calls.find(([input]) => String(input).endsWith('/api/auth/logout'))
    const headers = (logoutCall?.[1] as RequestInit).headers as Headers
    expect(headers.get('X-CSRF-Token')).toBe('logout-csrf')
  })

  it('moves to unauthenticated state after a protected API returns 401', async () => {
    vi.stubGlobal('fetch', appFetch())
    render(<I18nProvider initialLocale="bg"><App /></I18nProvider>)
    expect(await screen.findByRole('button', { name: 'Машини' })).toBeVisible()

    await expect(api('/protected-expired')).rejects.toMatchObject({ status: 401 })
    await waitFor(() => expect(screen.getByRole('button', { name: 'Вход' })).toBeVisible())
  })
})
