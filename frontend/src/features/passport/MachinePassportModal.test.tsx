import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { I18nProvider } from '../../i18n'
import { setSessionUser } from '../../permissions'
import type { MachinePassport, UserSession } from '../../types'
import { MachinePassportModal } from './MachinePassportModal'

import { passport } from './passportTestFixtures'
import { timelinePage } from './timelineTestFixtures'

function session(role: UserSession['role'], permissions: UserSession['permissions']): UserSession {
  return { id: 1, email: 'passport@example.invalid', full_name: 'Passport test', role, preferred_language: 'bg', is_active: true, is_system_owner: false, must_change_password: false, permissions, created_at: '2026-09-01T00:00:00Z', updated_at: '2026-09-01T00:00:00Z', last_login_at: null, password_changed_at: null }
}

function response(value: unknown): Response {
  return new Response(JSON.stringify(value), { status: 200, headers: { 'Content-Type': 'application/json' } })
}

function renderPassport(value: MachinePassport = passport, locale: 'bg' | 'en' | 'ru' = 'bg', onOpenCatalog = vi.fn()) {
  setSessionUser({
    ...session('administrator', ['assets.view', 'assets.edit', 'repairs.edit', 'documents.view', 'audit.view_operational']),
    preferred_language: locale,
  })
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const path = String(input)
    if (path.endsWith('/machines/13/passport')) return response(value)
    if (path.includes('/machines/13/timeline?')) return response(timelinePage())
    if (path.endsWith('/machines/13/qr') || path.includes('/download') || path.includes('/preview/')) return new Response(new Blob(['test'], { type: path.includes('pdf') ? 'application/pdf' : 'application/octet-stream' }))
    return init?.method === 'POST' || init?.method === 'PUT' ? response({ ok: true }) : response({})
  })
  vi.stubGlobal('fetch', fetchMock)
  return { ...render(<I18nProvider initialLocale={locale}><MachinePassportModal machineId={13} onClose={vi.fn()} onOpenCatalog={onOpenCatalog} /></I18nProvider>), fetchMock, onOpenCatalog }
}

describe('Machine Passport V2', () => {
  beforeEach(() => {
    localStorage.clear()
    vi.stubGlobal('requestAnimationFrame', (callback: FrameRequestCallback) => { callback(0); return 1 })
    const NativeURL = URL
    class TestURL extends NativeURL {
      static createObjectURL = vi.fn(() => 'blob:test-only')
      static revokeObjectURL = vi.fn()
    }
    vi.stubGlobal('URL', TestURL)
  })

  afterEach(() => {
    cleanup()
    vi.unstubAllGlobals()
    vi.restoreAllMocks()
  })

  it('renders the persistent identity and authoritative operational summary without raw statuses', async () => {
    const { fetchMock } = renderPassport()

    expect(await screen.findByRole('heading', { name: 'Машина №13' })).toBeVisible()
    expect(screen.getByText('Test-only machine')).toBeVisible()
    expect(screen.getAllByText('Водоструйни машини').length).toBeGreaterThan(0)
    expect(screen.getAllByText('В ремонт').length).toBeGreaterThan(0)
    expect(screen.getAllByText('Test workshop').length).toBeGreaterThan(0)
    expect(screen.getAllByText('Недостъпна').length).toBeGreaterThan(0)
    expect(screen.getAllByText('TEST-TRANSFER-LONG-REFERENCE-123456789').length).toBeGreaterThan(0)
    expect(screen.getAllByText('TEST-REPAIR-ACTIVE-LONG-REFERENCE-123456789').length).toBeGreaterThan(0)
    expect(screen.getByText('TEST-REPAIR-COMPLETE')).toBeVisible()
    expect(screen.getAllByText('TEST-REQUEST-001').length).toBeGreaterThan(0)
    expect(screen.queryByText('DIAGNOSIS')).not.toBeInTheDocument()
    expect(screen.queryByText('COMPLETED')).not.toBeInTheDocument()
    await waitFor(() => expect(fetchMock.mock.calls.some(([url]) => String(url) === '/api/machines/13/qr')).toBe(true))
  })

  it('renders truthful empty summary values for a free READY machine', async () => {
    const free: MachinePassport = {
      ...passport,
      machine: { ...passport.machine, status: 'READY' },
      current_state: {
        ...passport.current_state,
        available: true,
        active_transfer: null,
        active_repair: null,
        last_completed_repair: null,
        last_transfer: null,
        pending_part_requests: { count: 0, latest_request_reference: null },
      },
    }

    renderPassport(free)
    expect(await screen.findByText('Няма активно предаване')).toBeVisible()
    expect(screen.getByText('Няма активен ремонт')).toBeVisible()
    expect(screen.getByText('Няма завършен ремонт')).toBeVisible()
    expect(screen.getByText('Няма предавания')).toBeVisible()
    expect(screen.getByText('Няма активни заявки')).toBeVisible()
    expect(screen.getAllByText('Налична').length).toBeGreaterThan(0)
  })

  it('shows exactly six normal tabs plus permission-controlled Audit and supports keyboard navigation', async () => {
    renderPassport()
    const tablist = await screen.findByRole('tablist', { name: 'Раздели на машинния паспорт' })
    const tabs = within(tablist).getAllByRole('tab')
    expect(tabs.map((item) => item.textContent)).toEqual(['Обща информация', 'История', 'Ремонти', 'Протоколи', 'Резервни части', 'Снимки и файлове', 'Одит'])
    expect(within(tablist).queryByRole('tab', { name: 'Предавания' })).not.toBeInTheDocument()
    expect(within(tablist).queryByRole('tab', { name: 'Заявки' })).not.toBeInTheDocument()
    expect(within(tablist).queryByRole('tab', { name: 'Генерирани документи' })).not.toBeInTheDocument()
    fireEvent.keyDown(tabs[0], { key: 'ArrowRight' })
    expect(within(tablist).getByRole('tab', { name: 'История' })).toHaveAttribute('aria-selected', 'true')
  })

  it('keeps transfer records, canonical documents and authenticated preview actions in Protocols', async () => {
    const { fetchMock } = renderPassport()
    await userEvent.click(await screen.findByRole('tab', { name: 'Протоколи' }))

    expect(screen.getByText('Предавания и приемания')).toBeVisible()
    expect(screen.getByText('Официални протоколи')).toBeVisible()
    expect(screen.getByText('TEST-OFFICIAL-ISSUE')).toBeVisible()
    expect(screen.getByText('Други генерирани документи')).toBeVisible()
    expect(screen.getByText('TEST-LEGACY-OTHER')).toBeVisible()
    const officialSection = screen.getByText('Официални протоколи').closest('section') as HTMLElement
    await userEvent.click(within(officialSection).getByRole('button', { name: 'Преглед' }))
    await waitFor(() => expect(fetchMock.mock.calls.some(([url]) => String(url) === '/api/official-documents/7/preview/pdf')).toBe(true))
  })

  it('consolidates used parts and part requests and preserves the catalog shortcut', async () => {
    const onOpenCatalog = vi.fn()
    renderPassport(passport, 'bg', onOpenCatalog)
    await userEvent.click(await screen.findByRole('tab', { name: 'Резервни части' }))

    expect(screen.getByText('Използвани части')).toBeVisible()
    expect(screen.getByText(/TEST-PART/)).toBeVisible()
    expect(screen.getByText('Заявки за части')).toBeVisible()
    expect(screen.getAllByText('TEST-REQUEST-001').length).toBeGreaterThan(0)
    await userEvent.click(screen.getByRole('button', { name: /Отвори каталога/ }))
    expect(onOpenCatalog).toHaveBeenCalledTimes(1)
  })

  it('keeps attachments, technical documents, revisions and the existing upload action in Files', async () => {
    const { container, fetchMock } = renderPassport()
    await userEvent.click(await screen.findByRole('tab', { name: 'Снимки и файлове' }))

    expect(screen.getByText('test-photo.jpg')).toBeVisible()
    expect(screen.getByText('Технически документи и ръководства')).toBeVisible()
    expect(screen.getByText('Test manual')).toBeVisible()
    expect(screen.getByRole('button', { name: 'R2' })).toBeVisible()
    const input = container.querySelector<HTMLInputElement>('input[type="file"]') as HTMLInputElement
    await userEvent.upload(input, new File(['test'], 'new-test.pdf', { type: 'application/pdf' }))
    await waitFor(() => expect(fetchMock.mock.calls.some(([url, init]) => String(url) === '/api/machines/13/attachments' && init?.method === 'POST')).toBe(true))
  })

  it('preserves custom field editing and Save through the existing endpoint', async () => {
    const { fetchMock } = renderPassport()
    const field = await screen.findByRole('textbox', { name: 'Тестово поле' })
    await userEvent.clear(field)
    await userEvent.type(field, 'Updated test value')
    await userEvent.click(screen.getByRole('button', { name: 'Запази' }))

    await waitFor(() => expect(fetchMock.mock.calls.some(([url, init]) => String(url) === '/api/machines/13/custom-fields' && init?.method === 'PUT')).toBe(true))
  })

  it.each([
    ['bg', 'Оперативно състояние', 'Протоколи'],
    ['en', 'Operational summary', 'Protocols'],
    ['ru', 'Оперативное состояние', 'Протоколы'],
  ] as const)('renders the V2 navigation in %s', async (locale, summary, protocols) => {
    renderPassport(passport, locale)
    expect(await screen.findByText(summary)).toBeVisible()
    expect(screen.getByRole('tab', { name: protocols })).toBeVisible()
  })

  it('keeps Observer on the safe limited payload without tabs, QR or sensitive summaries', async () => {
    const limited: MachinePassport = {
      ...passport,
      limited_view: true,
      machine: { id: 13, inventory_number: '13', name: 'Test-only machine', brand: 'Falch', model: 'Test model', status: 'READY', is_active: true, location: { id: 1, name: 'Test public location' } } as MachinePassport['machine'],
      custom_fields: [], attachments: [], history: [], repairs: [], transfers: [], part_requests: [], parts_used: [], generated_documents: [], official_documents: [], technical_documents: [], audit: [], audit_visible: false, qr_endpoint: null,
      current_state: { available: true, active_transfer: null, active_repair: null, last_completed_repair: null, last_transfer: null, pending_part_requests: { count: 0, latest_request_reference: null }, allowed_actions: { issue: false, return: false, repair: false, edit: false } },
    }
    setSessionUser(session('observer', ['assets.view']))
    vi.stubGlobal('fetch', vi.fn(async () => response(limited)))
    render(<I18nProvider initialLocale="bg"><MachinePassportModal machineId={13} onClose={vi.fn()} /></I18nProvider>)

    expect(await screen.findByText('Ограничен изглед')).toBeVisible()
    expect(screen.getByText('Test public location')).toBeVisible()
    expect(screen.queryByRole('tablist')).not.toBeInTheDocument()
    expect(screen.queryByRole('img')).not.toBeInTheDocument()
    expect(screen.queryByText('TEST-REPAIR-COMPLETE')).not.toBeInTheDocument()
    expect(screen.queryByText('TEST-REQUEST-001')).not.toBeInTheDocument()
  })
})
