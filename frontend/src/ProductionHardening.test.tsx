import { fireEvent, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { I18nProvider } from './i18n'
import OfficialDocuments from './OfficialDocuments'
import ProfileCompletion from './ProfileCompletion'
import SignaturePage from './SignaturePage'
import type { UserSession } from './types'

function response(value: unknown, status = 200): Response {
  return new Response(JSON.stringify(value), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

const incompleteUser: UserSession = {
  id: 7,
  email: 'profile@example.invalid',
  full_name: 'Incomplete profile',
  role: 'mechanic',
  preferred_language: 'bg',
  is_active: true,
  is_system_owner: false,
  must_change_password: false,
  profile_status: 'PROFILE_INCOMPLETE',
  permissions: ['documents.generate'],
  created_at: '2026-08-01T10:00:00Z',
  updated_at: '2026-08-01T10:00:00Z',
}

describe('production hardening workflows', () => {
  beforeEach(() => localStorage.clear())
  afterEach(() => vi.unstubAllGlobals())

  it('forces a complete identity profile and submits the three names and job title', async () => {
    const onCompleted = vi.fn()
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      if (String(input).endsWith('/departments')) return response([])
      expect(init?.method).toBe('PUT')
      const body = JSON.parse(String(init?.body))
      expect(body).toMatchObject({
        first_name: 'Test',
        middle_name: 'Middle',
        last_name: 'Profile',
        job_title: 'QA mechanic',
      })
      return response({
        ...incompleteUser,
        ...body,
        full_name: 'Test Middle Profile',
        profile_status: 'PROFILE_COMPLETE',
      })
    })
    vi.stubGlobal('fetch', fetchMock)
    render(
      <I18nProvider initialLocale="bg">
        <ProfileCompletion user={incompleteUser} onCompleted={onCompleted} />
      </I18nProvider>,
    )

    expect(screen.queryByRole('button', { name: 'Отказ' })).not.toBeInTheDocument()
    await userEvent.type(screen.getByLabelText('Собствено име'), 'Test')
    await userEvent.type(screen.getByLabelText('Бащино име'), 'Middle')
    await userEvent.type(screen.getByLabelText('Фамилия'), 'Profile')
    await userEvent.type(screen.getByLabelText('Длъжност'), 'QA mechanic')
    await userEvent.click(screen.getByRole('button', { name: 'Потвърди профила' }))
    expect(onCompleted).toHaveBeenCalledWith(
      expect.objectContaining({ profile_status: 'PROFILE_COMPLETE' }),
    )
  })

  it('renders the three read-only registry sections with lifecycle and document actions', async () => {
    const registry = {
      transfers: {
        count: 2,
        items: [
          {
            registry_key: 'transfer:1', domain_id: 1, machine_number: '9', status: 'INCOMPLETE', signature_status: 'SIGNED', created_at: null, started_at: '2026-08-20T09:00:00Z',
            documents: [{ document_type: 'TRANSFER_ISSUE', document_number: 'TR-REG-009', official_document_id: 1, version: 1, version_status: 'SIGNED', files: [{ format: 'docx', download_endpoint: '/issue.docx', preview_endpoint: '/issue-preview.docx' }, { format: 'pdf', download_endpoint: '/issue.pdf', preview_endpoint: '/issue-preview.pdf' }] }],
          },
          {
            registry_key: 'transfer:2', domain_id: 2, machine_number: '10', status: 'COMPLETE', signature_status: 'PARTIALLY_SIGNED', created_at: '2026-08-22T11:00:00Z', started_at: '2026-08-21T09:00:00Z',
            documents: [
              { document_type: 'TRANSFER_ISSUE', document_number: 'TR-REG-010', official_document_id: 2, version: 1, version_status: 'SIGNED', files: [{ format: 'pdf', download_endpoint: '/issue-10.pdf', preview_endpoint: '/issue-10-preview.pdf' }] },
              { document_type: 'TRANSFER_RETURN', document_number: 'TR-REG-010-R', official_document_id: 3, version: 1, version_status: 'PARTIALLY_SIGNED', files: [{ format: 'pdf', download_endpoint: '/return-10.pdf', preview_endpoint: '/return-10-preview.pdf' }] },
            ],
          },
        ],
      },
      repairs: { count: 1, items: [{ registry_key: 'repair:1', domain_id: 1, machine_number: '11', status: 'COMPLETE', signature_status: 'NOT_REQUIRED', created_at: '2026-08-19T16:00:00Z', documents: [{ document_type: 'REPAIR_PROTOCOL', document_number: 'REP-REG-011', official_document_id: 4, version: 1, version_status: 'FINALIZED', files: [{ format: 'pdf', download_endpoint: '/repair.pdf', preview_endpoint: '/repair-preview.pdf' }] }] }] },
      parts: { count: 1, items: [{ registry_key: 'part-request:1', domain_id: 1, machine_number: '13', status: 'COMPLETE', signature_status: 'UNSIGNED', created_at: '2026-08-23T10:00:00Z', documents: [{ document_type: 'PART_REQUEST', document_number: 'PR-REG-013', official_document_id: 5, version: 1, version_status: 'DRAFT', files: [{ format: 'docx', download_endpoint: '/parts.docx', preview_endpoint: '/parts-preview.docx' }, { format: 'pdf', download_endpoint: '/parts.pdf', preview_endpoint: '/parts-preview.pdf' }] }] }] },
    }
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      expect(String(input)).toContain('/official-documents/registry')
      return response(registry)
    })
    vi.stubGlobal('fetch', fetchMock)
    render(<I18nProvider initialLocale="bg"><OfficialDocuments /></I18nProvider>)

    expect(await screen.findByRole('heading', { name: 'Приемане / предаване' })).toBeVisible()
    expect(screen.getByRole('heading', { name: 'Ремонти' })).toBeVisible()
    expect(screen.getByRole('heading', { name: 'Заявени части' })).toBeVisible()
    expect(screen.getByLabelText('Документи в секцията: 2')).toBeVisible()
    expect(screen.getAllByLabelText('Документи в секцията: 1')).toHaveLength(2)

    const incompleteRow = screen.getByText('TR-REG-009').closest('tr')
    expect(incompleteRow).not.toBeNull()
    expect(within(incompleteRow!).getByText('Незавършен')).toBeVisible()
    expect(within(incompleteRow!).getByText('Подписан')).toBeVisible()
    expect(within(incompleteRow!).getByText('Протокол предаване')).toBeVisible()
    expect(within(incompleteRow!).queryByText('Протокол приемане')).not.toBeInTheDocument()
    expect(within(incompleteRow!).getByRole('button', { name: 'Word' })).toBeVisible()
    expect(within(incompleteRow!).getByRole('button', { name: 'PDF' })).toBeVisible()

    const completedRow = screen.getByText('TR-REG-010-R').closest('tr')
    expect(completedRow).not.toBeNull()
    expect(within(completedRow!).getByText('Завършен')).toBeVisible()
    expect(within(completedRow!).getByText('Частично подписан')).toBeVisible()
    expect(within(completedRow!).getAllByText('Протокол предаване')).toHaveLength(2)
    expect(within(completedRow!).getAllByText('Протокол приемане')).toHaveLength(2)
    expect(screen.getByText('Ремонтен протокол')).toBeVisible()
    expect(screen.getByText('Протокол за заявка за части')).toBeVisible()
    expect(screen.queryByRole('button', { name: 'Нов външен подписващ' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Създай еднократна връзка' })).not.toBeInTheDocument()
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })

  it('keeps a separate empty state and zero count for every registry section', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => response({
      transfers: { count: 0, items: [] },
      repairs: { count: 0, items: [] },
      parts: { count: 0, items: [] },
    })))

    render(<I18nProvider initialLocale="bg"><OfficialDocuments /></I18nProvider>)

    expect(await screen.findByText('Няма създадени протоколи за приемане / предаване.')).toBeVisible()
    expect(screen.getByText('Няма създадени ремонтни протоколи.')).toBeVisible()
    expect(screen.getByText('Няма създадени протоколи за заявени части.')).toBeVisible()
    expect(screen.getAllByLabelText('Документи в секцията: 0')).toHaveLength(3)
  })

  it('requires review and explicit confirmation for the mobile signature', async () => {
    const context = {
      fillRect: vi.fn(),
      beginPath: vi.fn(),
      moveTo: vi.fn(),
      lineTo: vi.fn(),
      stroke: vi.fn(),
      clearRect: vi.fn(),
      set fillStyle(_value: string) {},
      set strokeStyle(_value: string) {},
      set lineWidth(_value: number) {},
      set lineCap(_value: CanvasLineCap) {},
      set lineJoin(_value: CanvasLineJoin) {},
    }
    vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue(context as unknown as CanvasRenderingContext2D)
    vi.spyOn(HTMLCanvasElement.prototype, 'toDataURL').mockReturnValue('data:image/png;base64,dGVzdA==')
    Object.defineProperty(HTMLCanvasElement.prototype, 'setPointerCapture', { value: vi.fn(), configurable: true })
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      if (!init?.method) {
        return response({
          document_number: 'QA-DOC-002', document_type: 'TRANSFER_ISSUE', document_version: 1,
          document_status: 'READY_FOR_SIGNATURE', document_sha256: 'd'.repeat(64),
          participant: { display_name: 'Test Signer', job_title: 'QA' }, operation_role: 'HANDOVER',
          consent_notice: 'Потвърждавам подписването на тази тестова версия.', requires_confirmation: true,
        })
      }
      return response(url.endsWith('/confirm') ? { document_status: 'SIGNED' } : { requires_confirmation: true })
    })
    vi.stubGlobal('fetch', fetchMock)
    render(<I18nProvider initialLocale="bg"><SignaturePage token="test-token" /></I18nProvider>)

    const canvas = await screen.findByLabelText('Поле за ръчен графичен подпис')
    fireEvent.pointerDown(canvas, { pointerId: 1, clientX: 10, clientY: 10 })
    for (let index = 0; index < 8; index += 1) {
      fireEvent.pointerMove(canvas, { pointerId: 1, clientX: 20 + index, clientY: 20 + index })
    }
    fireEvent.pointerUp(canvas, { pointerId: 1 })
    await userEvent.click(screen.getByRole('checkbox'))
    await userEvent.click(screen.getByRole('button', { name: 'Преглед на подписа' }))
    expect(await screen.findByRole('heading', { name: 'Последна проверка' })).toBeVisible()
    await userEvent.click(screen.getByRole('button', { name: 'Потвърди подписа' }))
    expect(await screen.findByRole('heading', { name: 'Документът е подписан' })).toBeVisible()
    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining('/signing/test-token/confirm'),
      expect.objectContaining({ method: 'POST' }),
    )
  })
})
