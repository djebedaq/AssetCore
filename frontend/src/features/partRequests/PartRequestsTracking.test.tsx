import { cleanup, render, screen, waitFor } from '@testing-library/react'
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
})
