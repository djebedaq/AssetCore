import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { I18nProvider } from '../../i18n'
import { setSessionUser } from '../../permissions'
import type { MachinePassport, UserSession } from '../../types'
import { MachinePassportModal } from './MachinePassportModal'

const passport: MachinePassport = {
  limited_view: false,
  machine: {
    id: 13, inventory_number: '13', name: 'Test-only machine', brand: 'Falch', model: 'Test model', pressure_bar: 500,
    serial_number: 'TEST-SERIAL', status: 'REPAIR', location_id: 1, location: { id: 1, name: 'Test workshop', is_active: true },
    category: 'HPWJ', category_definition: { id: 1, code: 'HPWJ', name_bg: 'Водоструйни машини', name_en: 'Water-jet machines', name_ru: 'Водоструйные машины', is_active: true, created_at: '2026-09-01T00:00:00Z', fields: [] },
    notes: null, asset_type: 'Test asset', subtype: 'Test subtype', manufacturer: 'Test manufacturer', manufacture_year: 2024,
    commissioning_date: '2025-01-02T00:00:00Z', ownership: 'Test ownership', department: 'Test department', responsible_person: 'Test owner',
    capacity: 'Test capacity', dimensions: 'Test dimensions', is_active: true, created_at: '2026-09-01T00:00:00Z', updated_at: '2026-09-01T00:00:00Z',
  },
  custom_fields: [{ id: 1, category_id: 1, code: 'test_field', label_bg: 'Тестово поле', label_en: 'Test field', label_ru: 'Тестовое поле', field_type: 'TEXT', is_required: true, sort_order: 1, is_active: true, field_id: 1, value: 'Test value' }],
  attachments: [{ id: 1, filename: 'test-photo.jpg', media_type: 'image/jpeg', sha256: 'a'.repeat(64), created_at: '2026-09-03T09:00:00Z', download_endpoint: '/machine-attachments/1/download' }],
  history: [{ id: 1, event_type: 'TRANSFER_ISSUED', reference: 'TEST-EVENT', previous_status: 'READY', new_status: 'ISSUED', created_at: '2026-09-01T08:00:00Z' }],
  repairs: [{ id: 3, repair_reference: 'TEST-REPAIR-ACTIVE-LONG-REFERENCE-123456789', status: 'DIAGNOSIS', reported_problem: 'Test-only reported problem', opened_at: '2026-09-03T08:00:00Z' }],
  transfers: [{ id: 2, protocol_number: 'TEST-TRANSFER-LONG-REFERENCE-123456789', batch_reference: 'TEST-BATCH', is_active: true, issued_at: '2026-09-03T07:00:00Z', location_text: 'Test location', accepted_by: 'Test recipient' }],
  part_requests: [{ id: 4, request_reference: 'TEST-REQUEST-001', status: 'ORDERED', priority: 'URGENT', created_at: '2026-09-03T06:00:00Z' }],
  parts_used: [{ id: 5, repair_id: 2, repair_reference: 'TEST-REPAIR-COMPLETE', part_number: 'TEST-PART', description: 'Test used part', quantity: 4, unit: 'бр.', source: 'Test source', created_at: '2026-09-02T06:00:00Z' }],
  generated_documents: [{ id: 6, document_number: 'TEST-LEGACY-OTHER', document_type: 'OTHER', format: 'pdf', filename: 'test-other.pdf', created_at: '2026-09-02T05:00:00Z', download_endpoint: '/generated-documents/6/download', display_separately: true }],
  official_documents: [{
    category: 'transfers', registry_key: 'transfer:2', domain_id: 2, machine_id: 13, machine_number: '13', status: 'INCOMPLETE', signature_status: 'SIGNED', started_at: '2026-09-03T07:00:00Z',
    documents: [{ document_type: 'TRANSFER_ISSUE', document_number: 'TEST-OFFICIAL-ISSUE', official_document_id: 7, version: 1, version_status: 'FINALIZED', files: [
      { format: 'docx', download_endpoint: '/official-documents/7/versions/1/download/docx' },
      { format: 'pdf', download_endpoint: '/official-documents/7/versions/1/download/pdf', preview_endpoint: '/official-documents/7/preview/pdf' },
    ] }],
  }],
  technical_documents: [{ id: 8, brand: 'Test', category: 'HPWJ', title: 'Test manual', document_type: 'TECHNICAL', language: 'bg', revision: 'R1', sha256: 'b'.repeat(64), created_at: '2026-09-01T00:00:00Z', source_label: 'Test source', document_date: '2026-09-01', linked_machine_numbers: ['13'], download_endpoint: '/technical-library/8/download', revisions: [{ id: 9, version: 2, revision_label: 'R2', filename: 'test-manual-r2.pdf', sha256: 'c'.repeat(64), created_at: '2026-09-02T00:00:00Z', download_endpoint: '/technical-library/revisions/9/download' }] }],
  current_state: {
    available: false,
    active_transfer: { id: 2, protocol_number: 'TEST-TRANSFER-LONG-REFERENCE-123456789', batch_reference: 'TEST-BATCH', issued_at: '2026-09-03T07:00:00Z', company_unit: 'Test unit', department: 'Test department', vessel: 'Test vessel', dock: 'Test dock', location_text: 'Test location' },
    active_repair: { id: 3, repair_reference: 'TEST-REPAIR-ACTIVE-LONG-REFERENCE-123456789', status: 'DIAGNOSIS', reported_problem: 'Test-only reported problem', opened_at: '2026-09-03T08:00:00Z' },
    last_completed_repair: { id: 2, repair_reference: 'TEST-REPAIR-COMPLETE', status: 'COMPLETED', opened_at: '2026-08-30T08:00:00Z', closed_at: '2026-09-02T08:00:00Z', test_passed: true },
    last_transfer: { id: 2, protocol_number: 'TEST-TRANSFER-LONG-REFERENCE-123456789', batch_reference: 'TEST-BATCH', is_active: true, issued_at: '2026-09-03T07:00:00Z', location_text: 'Test location' },
    pending_part_requests: { count: 1, latest_request_reference: 'TEST-REQUEST-001' },
    last_movement: { event_type: 'TRANSFER_ISSUED', reference: 'TEST-EVENT', created_at: '2026-09-03T07:00:00Z' },
    last_inspection: { repair_reference: 'TEST-REPAIR-COMPLETE', completed_at: '2026-09-02T07:00:00Z' },
    last_test: { repair_reference: 'TEST-REPAIR-COMPLETE', passed: true, completed_at: '2026-09-02T08:00:00Z' },
    allowed_actions: { issue: false, return: true, repair: false, edit: true },
  },
  audit_visible: true,
  audit: [{ id: 10, entity_type: 'machine', entity_id: 13, action: 'TEST_AUDIT', user_name: 'Test user', created_at: '2026-09-03T10:00:00Z' }],
  qr_endpoint: '/machines/13/qr',
}

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
