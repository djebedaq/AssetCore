import { fireEvent, render, screen } from '@testing-library/react'
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

  it('shows partial signature progress and loads every eligible internal participant', async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input)
      if (url.endsWith('/external-signers')) return response([])
      if (url.endsWith('/document-participants/internal-candidates')) {
        return response([{ id: 3, display_name: 'Test Internal Signer', job_title: 'QA', role: 'mechanic' }])
      }
      return response([
        {
          id: 1,
          document_number: 'QA-DOC-001',
          document_type: 'TRANSFER_ISSUE',
          created_at: '2026-08-01T10:00:00Z',
          current_version: {
            id: 2,
            version: 1,
            status: 'PARTIALLY_SIGNED',
            language: 'bg',
            snapshot_sha256: 'a'.repeat(64),
            docx_sha256: 'b'.repeat(64),
            pdf_sha256: 'c'.repeat(64),
            created_at: '2026-08-01T10:00:00Z',
          },
          signed_count: 1,
          required_count: 2,
          participants: [
            { id: 9, slot_code: 'HANDOVER', participant_kind: 'INTERNAL', operation_role: 'HANDOVER', identity_snapshot: { display_name: 'Test Internal Signer', job_title: 'QA' }, signed: true },
            { id: 10, slot_code: 'ACCEPTANCE', participant_kind: 'EXTERNAL', operation_role: 'ACCEPTANCE', identity_snapshot: { display_name: 'Test External Signer', job_title: 'QA' }, signed: false },
          ],
        },
      ])
    })
    vi.stubGlobal('fetch', fetchMock)
    render(<I18nProvider initialLocale="bg"><OfficialDocuments /></I18nProvider>)

    await userEvent.click(await screen.findByText('QA-DOC-001'))
    expect(screen.getByText('1 / 2')).toBeVisible()
    expect(screen.getByText(/Частично подписан документ/)).toBeVisible()
    expect(screen.getByRole('button', { name: 'Създай еднократна връзка' })).toBeVisible()
    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining('/document-participants/internal-candidates'),
      expect.anything(),
    )
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
