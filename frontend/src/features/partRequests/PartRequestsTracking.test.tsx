import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { I18nProvider } from '../../i18n'
import { setSessionUser } from '../../permissions'
import type { MultiPartRequest, UserSession } from '../../types'
import { PartRequestsTracking } from './PartRequestsTracking'

const request: MultiPartRequest = {
  id: 12,
  request_reference: 'PR-2026-000012',
  machine_id: 9,
  machine_number: '9',
  priority: 'NORMAL',
  status: 'WAITING_APPROVAL',
  language: 'bg',
  requested_by_id: 4,
  requested_by_name: 'Проверен заявител',
  submitted_at: '2026-08-24T10:00:00',
  created_at: '2026-08-24T09:55:00',
  lines: [{
    id: 21,
    request_id: 12,
    catalog_part_id: 31,
    position: '8',
    part_number: 'SOURCE-PART',
    description: 'Verified source description',
    quantity: 2,
    unit: 'pcs',
    delivered_quantity: 0,
  }],
  approvals: [],
  attachments: [],
  documents: [{ id: 44, format: 'pdf', filename: 'safe.pdf', download_endpoint: '/generated-documents/44/download' }],
  quantity_compatibility: { status: 'COMPATIBLE', affected_line_ids: [], recovery_action: 'NONE' },
}

function response(value: unknown) {
  return new Response(JSON.stringify(value), {
    status: 200,
    headers: { 'Content-Type': 'application/json' },
  })
}

describe('Заявени части tracking', () => {
  beforeEach(() => {
    localStorage.clear()
  })
  afterEach(() => {
    cleanup()
    vi.restoreAllMocks()
    vi.unstubAllGlobals()
  })

  it('is history-first, shows required data, and hides approval from a mechanic', async () => {
    setSessionUser({ role: 'mechanic', permissions: ['requests.view', 'requests.create', 'parts.view', 'documents.view', 'documents.generate'] } as UserSession)
    vi.stubGlobal('fetch', vi.fn(async () => response([
      { ...request, id: 11, request_reference: 'PR-2026-000011', status: 'DRAFT', submitted_at: null },
      request,
    ])))
    render(<I18nProvider initialLocale="bg"><PartRequestsTracking /></I18nProvider>)
    expect(await screen.findByRole('heading', { name: 'Заявени части' })).toBeInTheDocument()
    expect(screen.getAllByText(/Проверен заявител/)).toHaveLength(2)
    expect(screen.getByText('Подаване на запазената историческа чернова за одобрение')).toBeInTheDocument()
    expect(screen.getByText('Очаква решение от оторизиран одобряващ')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Подай за одобрение' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Одобри' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Нова многоредова заявка' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Заяви непозната част' })).not.toBeInTheDocument()
    expect(screen.getAllByRole('button', { name: 'PDF' })).toHaveLength(2)
  })

  it('shows canonical decision controls only to an approver and refreshes after approval', async () => {
    setSessionUser({ role: 'director', permissions: ['requests.view', 'requests.create', 'requests.approve', 'parts.view', 'documents.view', 'documents.generate'] } as UserSession)
    let current = request
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input)
      if (path.endsWith('/api/part-requests/multi')) return response([current])
      if (path.endsWith('/api/part-requests/12/decision') && init?.method === 'POST') {
        current = { ...request, status: 'APPROVED', decided_at: '2026-08-24T11:00:00' }
        return response(current)
      }
      throw new Error(`Unexpected request: ${path}`)
    })
    vi.stubGlobal('fetch', fetchMock)
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    render(<I18nProvider initialLocale="bg"><PartRequestsTracking /></I18nProvider>)
    await userEvent.click(await screen.findByRole('button', { name: 'Одобри' }))
    await waitFor(() => expect(screen.getByText('Поръчване или отказ на одобрената заявка')).toBeInTheDocument())
    expect(fetchMock.mock.calls.some(([input, init]) => String(input).endsWith('/api/part-requests/12/decision') && init?.method === 'POST')).toBe(true)
  })

  it('hides normal Generate when the canonical protocol exists and keeps document actions', async () => {
    setSessionUser({ role: 'director', permissions: ['requests.view', 'requests.create', 'requests.approve', 'parts.view', 'documents.view', 'documents.generate'] } as UserSession)
    vi.stubGlobal('fetch', vi.fn(async () => response([{
      ...request,
      status: 'CANCELLED',
      documents: [
        { id: 43, format: 'docx', filename: 'safe.docx', download_endpoint: '/generated-documents/43/download' },
        { id: 44, format: 'pdf', filename: 'safe.pdf', download_endpoint: '/generated-documents/44/download' },
      ],
    }])))
    render(<I18nProvider initialLocale="bg"><PartRequestsTracking /></I18nProvider>)
    expect(await screen.findByRole('heading', { name: 'Заявени части' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Генерирай/ })).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'DOCX' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'PDF' })).toBeInTheDocument()
  })

  it('uses integer fulfillment controls and never submits a fractional edit', async () => {
    setSessionUser({ role: 'mechanic', permissions: ['requests.view', 'requests.create', 'parts.view'] } as UserSession)
    const ordered = { ...request, status: 'ORDERED', lines: [{ ...request.lines[0], quantity: 4, delivered_quantity: 0 }], documents: [] }
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input)
      if (path.endsWith('/api/part-requests/multi')) return response([ordered])
      if (path.endsWith('/api/part-requests/12/fulfillment') && init?.method === 'PATCH') return response(ordered)
      throw new Error(`Unexpected request: ${path}`)
    })
    vi.stubGlobal('fetch', fetchMock)
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    render(<I18nProvider initialLocale="bg"><PartRequestsTracking /></I18nProvider>)
    await userEvent.click(await screen.findByRole('button', { name: 'Поръчка / доставка' }))
    const input = screen.getByRole('spinbutton', { name: 'Доставено количество SOURCE-PART' })
    expect(input).toHaveAttribute('step', '1')
    expect(input).toHaveAttribute('min', '0')
    expect(input).toHaveAttribute('max', '4')
    fireEvent.change(input, { target: { value: '1' } })
    expect(input).toHaveValue(1)
    fireEvent.change(input, { target: { value: '1.5' } })
    expect(input).toHaveValue(1)
    await userEvent.click(screen.getByRole('button', { name: 'Запиши изпълнението' }))
    await waitFor(() => expect(fetchMock.mock.calls.some(([inputValue, init]) => String(inputValue).endsWith('/api/part-requests/12/fulfillment') && init?.method === 'PATCH')).toBe(true))
    const mutation = fetchMock.mock.calls.find(([inputValue, init]) => String(inputValue).endsWith('/api/part-requests/12/fulfillment') && init?.method === 'PATCH')
    const body = JSON.parse(String(mutation?.[1]?.body))
    expect(body.lines).toEqual([{ line_id: 21, delivered_quantity: 1 }])
    expect(Number.isInteger(body.lines[0].delivered_quantity)).toBe(true)
  })

  it('renders whole transaction progress cleanly and preserves legacy fractions for read-only history', async () => {
    setSessionUser({ role: 'observer', permissions: ['requests.view', 'parts.view'] } as UserSession)
    vi.stubGlobal('fetch', vi.fn(async () => response([
      { ...request, id: 13, request_reference: 'PR-2026-000013', status: 'DELIVERED', lines: [{ ...request.lines[0], id: 22, request_id: 13, quantity: 4, delivered_quantity: 1 }] },
      { ...request, id: 14, request_reference: 'PR-LEGACY-000014', status: 'DELIVERED', lines: [{ ...request.lines[0], id: 23, request_id: 14, quantity: 1.5, delivered_quantity: 0.5 }] },
    ])))
    render(<I18nProvider initialLocale="bg"><PartRequestsTracking /></I18nProvider>)
    expect(await screen.findByText('Доставено количество: 1 / 4 pcs')).toBeInTheDocument()
    expect(screen.getByText('Доставено количество: 0.5 / 1.5 pcs')).toBeInTheDocument()
    expect(screen.queryByText(/1\.0 \/ 4\.0/)).not.toBeInTheDocument()
  })

  it('identifies a legacy fractional draft and replaces the impossible submit action with recovery guidance', async () => {
    setSessionUser({ role: 'mechanic', permissions: ['requests.view', 'requests.create', 'parts.view'] } as UserSession)
    const legacyDraft: MultiPartRequest = {
      ...request,
      status: 'DRAFT',
      submitted_at: null,
      lines: [{ ...request.lines[0], quantity: 1.04, delivered_quantity: 0 }],
      quantity_compatibility: {
        status: 'LEGACY_FRACTIONAL',
        affected_line_ids: [21],
        recovery_action: 'CREATE_REPLACEMENT',
      },
    }
    vi.stubGlobal('fetch', vi.fn(async () => response([legacyDraft])))

    render(<I18nProvider initialLocale="bg"><PartRequestsTracking /></I18nProvider>)

    expect(await screen.findByRole('alert')).toHaveTextContent('Несъвместимо историческо дробно количество')
    expect(screen.getByRole('alert')).toHaveTextContent('Създайте нова заявка с цели количества')
    expect(screen.getByRole('alert')).toHaveTextContent('Засегнати редове: 21')
    expect(screen.queryByRole('button', { name: 'Подай за одобрение' })).not.toBeInTheDocument()
  })

  it('does not offer approval for a legacy fractional request and retains rejection recovery', async () => {
    setSessionUser({ role: 'director', permissions: ['requests.view', 'requests.create', 'requests.approve', 'parts.view'] } as UserSession)
    const legacyWaiting: MultiPartRequest = {
      ...request,
      lines: [{ ...request.lines[0], quantity: 1.04 }],
      quantity_compatibility: {
        status: 'LEGACY_FRACTIONAL',
        affected_line_ids: [21],
        recovery_action: 'REJECT_AND_RECREATE',
      },
    }
    vi.stubGlobal('fetch', vi.fn(async () => response([legacyWaiting])))

    render(<I18nProvider initialLocale="bg"><PartRequestsTracking /></I18nProvider>)

    expect(await screen.findByRole('alert')).toHaveTextContent('Отхвърлете заявката')
    expect(screen.queryByRole('button', { name: 'Одобри' })).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Отхвърли' })).toBeInTheDocument()
  })

  it('offers GET-listed legacy active requests only cancellation without line mutation', async () => {
    setSessionUser({ role: 'mechanic', permissions: ['requests.view', 'requests.create', 'parts.view'] } as UserSession)
    const legacyOrdered: MultiPartRequest = {
      ...request,
      status: 'ORDERED',
      lines: [{ ...request.lines[0], quantity: 1.04, delivered_quantity: 0.5 }],
      quantity_compatibility: {
        status: 'LEGACY_FRACTIONAL',
        affected_line_ids: [21],
        recovery_action: 'CANCEL_AND_RECREATE',
      },
    }
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input)
      if (path.endsWith('/api/part-requests/multi')) return response([legacyOrdered])
      if (path.endsWith('/api/part-requests/12/fulfillment') && init?.method === 'PATCH') {
        return response({ ...legacyOrdered, status: 'CANCELLED' })
      }
      throw new Error(`Unexpected request: ${path}`)
    })
    vi.stubGlobal('fetch', fetchMock)
    vi.spyOn(window, 'confirm').mockReturnValue(true)

    render(<I18nProvider initialLocale="bg"><PartRequestsTracking /></I18nProvider>)
    await userEvent.click(await screen.findByRole('button', { name: 'Отмени и създай отново' }))

    const status = screen.getByRole('combobox', { name: 'Статус' })
    expect(status).toHaveValue('CANCELLED')
    expect(screen.getAllByRole('option')).toHaveLength(1)
    expect(screen.getByRole('spinbutton', { name: 'Доставено количество SOURCE-PART' })).toBeDisabled()
    await userEvent.click(screen.getByRole('button', { name: 'Запиши изпълнението' }))
    await waitFor(() => expect(fetchMock.mock.calls.some(([inputValue, init]) => String(inputValue).endsWith('/api/part-requests/12/fulfillment') && init?.method === 'PATCH')).toBe(true))
    const mutation = fetchMock.mock.calls.find(([inputValue, init]) => String(inputValue).endsWith('/api/part-requests/12/fulfillment') && init?.method === 'PATCH')
    expect(JSON.parse(String(mutation?.[1]?.body))).toEqual(expect.objectContaining({ status: 'CANCELLED', lines: [] }))
  })
})
