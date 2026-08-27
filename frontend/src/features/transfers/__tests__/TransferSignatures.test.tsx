import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { IssueModal, ReturnModal } from '../../../BulkTransfers'
import { change, fillIssue, fillReturn, issued, issueResult, locations, machines, mockApi, response, returnResult, t, tasks } from './fixtures'

beforeEach(() => {
  const context = { fillRect: vi.fn(), beginPath: vi.fn(), moveTo: vi.fn(), lineTo: vi.fn(), stroke: vi.fn() }
  vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue(context as unknown as CanvasRenderingContext2D)
  vi.spyOn(HTMLCanvasElement.prototype, 'toDataURL').mockReturnValue('data:image/png;base64,dGVzdA==')
  vi.spyOn(HTMLCanvasElement.prototype, 'getBoundingClientRect').mockReturnValue({ x: 0, y: 0, left: 0, top: 0, width: 360, height: 180, bottom: 180, right: 360, toJSON: () => ({}) })
  Object.defineProperty(HTMLCanvasElement.prototype, 'setPointerCapture', { value: vi.fn(), configurable: true })
  vi.stubGlobal('PointerEvent', MouseEvent)
})
afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); document.body.style.overflow = '' })

async function begin(operation: 'issue' | 'return', done: () => void) {
  const user = userEvent.setup()
  if (operation === 'issue') {
    render(<IssueModal items={machines} locations={locations} onClose={vi.fn()} onComplete={done} />)
    await user.click(screen.getByLabelText('Машина №4'))
    await user.click(screen.getByLabelText('Машина №5'))
    fillIssue()
  } else {
    render(<ReturnModal items={issued} onClose={vi.fn()} onComplete={done} />)
    await user.click(screen.getByLabelText('Връщане на машина №4'))
    fillReturn('4')
  }
  await user.click(screen.getByRole('button', { name: t('bulk.reviewConfirm') }))
  await user.click(screen.getByRole('button', { name: t(operation === 'issue' ? 'bulk.confirmIssue' : 'bulk.confirmReturn') }))
  return user
}

describe('real integrated signature UI inside bulk transfer steps', () => {
  it.each([
    { operation: 'issue' as const, legacy: false, count: 2 },
    { operation: 'issue' as const, legacy: true, count: 2 },
    { operation: 'issue' as const, legacy: false, count: 3 },
    { operation: 'return' as const, legacy: false, count: 2 },
    { operation: 'return' as const, legacy: true, count: 2 },
  ])('follows server task order until the final confirm ($operation, legacy=$legacy, tasks=$count)', async ({ operation, legacy, count }) => {
    const configured = count === 2 ? tasks : [...tasks, { ...tasks[1], participant_id: 3, signing_token: 'test-signature-3', signing_endpoint: '/api/signing/test-signature-3' }]
    const result = operation === 'issue' ? issueResult(configured) : returnResult(configured)
    if (legacy) result.signing_tasks = [] // Same task list remains on the first individual record.
    const request = mockApi((path, init) => {
      if (path === `/api/transfers/bulk-${operation}`) return response(result, operation === 'issue' ? 201 : 200)
      if (path.startsWith('/api/signing/')) {
        if (init.method === 'POST') return response({ requires_confirmation: true, document_status: 'SIGNED' })
        const task = configured.find(item => path === item.signing_endpoint)!
        return response({
          document_number: 'QA-SIGN-ACT', document_type: operation === 'issue' ? 'TRANSFER_ISSUE' : 'TRANSFER_RETURN',
          document_version: 1, document_status: 'READY_FOR_SIGNATURE', document_sha256: 'c'.repeat(64),
          batch_reference: result.batch_reference, batch_manifest_sha256: result.batch_manifest_sha256,
          participant: { display_name: task.signer_name, job_title: 'QA' }, operation_role: task.operation_role,
          operation_description: 'QA operation', operation_datetime: '2026-08-01T09:00:00Z',
          consent_notice: 'QA explicit consent', requires_confirmation: true,
        })
      }
      throw new Error('Unexpected test request')
    })
    const done = vi.fn()
    const user = await begin(operation, done)
    for (let index = 0; index < configured.length; index += 1) {
      await waitFor(() => expect(screen.getByRole('button', { name: t('signature.review') })).toBeEnabled())
      expect(screen.getByText(`Подпис ${index + 1} от ${count}`)).toBeVisible()
      expect(screen.getByText(`SHA-256: ${result.batch_manifest_sha256}`)).toBeVisible()
      expect(done).not.toHaveBeenCalled()
      expect(screen.queryByRole('button', { name: 'DOCX' })).not.toBeInTheDocument()
      expect(screen.queryByRole('button', { name: 'PDF' })).not.toBeInTheDocument()
      const canvas = screen.getByLabelText(t('signature.canvas'))
      expect(canvas.closest('.signature-embedded')).not.toBeNull()
      expect(canvas.closest('.integrated-signing')).not.toBeNull()
      fireEvent.pointerDown(canvas, { pointerId: 1, clientX: 10, clientY: 10, pointerType: 'touch' })
      expect(document.body.style.overflow).toBe('hidden')
      for (let point = 0; point < 8; point += 1) fireEvent.pointerMove(canvas, { pointerId: 1, clientX: 20 + point, clientY: 25 + point, pointerType: 'touch' })
      fireEvent.pointerUp(canvas, { pointerId: 1 })
      expect(document.body.style.overflow).toBe('')
      await user.click(screen.getByRole('checkbox', { name: 'QA explicit consent' }))
      await user.click(screen.getByRole('button', { name: t('signature.review') }))
      expect(await screen.findByRole('heading', { name: t('signature.reviewTitle') })).toBeVisible()
      expect(done).not.toHaveBeenCalled()
      expect(request.mock.calls.filter(([path]) => String(path).endsWith('/confirm'))).toHaveLength(index)
      await user.click(screen.getByRole('button', { name: t('signature.confirm') }))
    }
    expect(await screen.findByRole('heading', { name: t(operation === 'issue' ? 'bulk.issueSuccess' : 'bulk.returnSuccess') })).toBeVisible()
    expect(done).toHaveBeenCalledTimes(1)
    expect(screen.getAllByRole('button', { name: 'DOCX' })).toHaveLength(operation === 'issue' ? 2 : 1)
    expect(request.mock.calls.map(([path]) => String(path))).toEqual([
      `/api/transfers/bulk-${operation}`,
      ...configured.flatMap(item => [item.signing_endpoint, item.signing_endpoint, `${item.signing_endpoint}/confirm`]),
    ])
    // No client-side machine mutation, manifest rewrite, per-machine repeat generation or extra signature act.
    expect(request.mock.calls.filter(([path]) => String(path).includes('/transfers/bulk-'))).toHaveLength(1)
  })

  it.each(['issue', 'return'] as const)('keeps %s pending on signature rejection and cancels only through the operation batch', async operation => {
    const result = operation === 'issue' ? issueResult(tasks) : returnResult(tasks)
    const request = mockApi((path, init) => {
      if (path === `/api/transfers/bulk-${operation}`) return response(result)
      if (path.endsWith('/reject')) return response({ message: 'QA rejection' })
      if (path.endsWith('/cancel')) return response({ batch_id: result.batch_id, batch_reference: result.batch_reference, status: 'CANCELLED', cancelled_transfers: 1, invalidated_signing_sessions: 1, message: 'QA' })
      if (path.startsWith('/api/signing/') && !init.method) return response({ document_number: 'QA', document_version: 1, participant: {}, operation_role: 'QA', consent_notice: 'QA explicit consent' })
      throw new Error('Unexpected test request')
    })
    const done = vi.fn()
    const user = await begin(operation, done)
    await user.click(await screen.findByRole('button', { name: t('signature.reject') }))
    expect(await screen.findByRole('alert')).toHaveTextContent(t('bulk.signatureCancelled'))
    expect(done).not.toHaveBeenCalled()
    expect(screen.queryByRole('button', { name: 'DOCX' })).not.toBeInTheDocument()
    if (operation === 'issue') expect(screen.getByRole('button', { name: t('bulk.downloadAllZip') })).toBeDisabled()
    await user.click(screen.getByRole('button', { name: t('bulk.cancelPendingAction') }))
    expect(screen.getByText(t(operation === 'issue' ? 'bulk.cancelIssueEffect' : 'bulk.cancelReturnEffect'))).toBeVisible()
    change(t('bulk.cancelReason'), '  QA refusal  ')
    await user.click(screen.getByRole('button', { name: t('bulk.cancelConfirm') }))
    await waitFor(() => expect(done).toHaveBeenCalledTimes(1))
    expect(request).toHaveBeenCalledWith(`/api/transfer-batches/${result.batch_id}/cancel`, expect.objectContaining({ method: 'POST', body: JSON.stringify({ reason: 'QA refusal' }) }))
    expect(screen.queryByRole('button', { name: t('bulk.cancelPendingAction') })).not.toBeInTheDocument()
    expect(request.mock.calls.some(([path]) => String(path).endsWith('/confirm'))).toBe(false)
  })

  it('keeps an unavailable signature session in the signing step without falsely completing the issue', async () => {
    mockApi(path => path === '/api/transfers/bulk-issue' ? response(issueResult(tasks), 201) : response({ detail: { code: 'signing_session_unavailable' } }, 409))
    const done = vi.fn()
    await begin('issue', done)
    expect(await screen.findByRole('alert')).toHaveTextContent(t('signature.sessionUnavailable'))
    expect(screen.getByRole('button', { name: t('signature.review') })).toBeDisabled()
    expect(done).not.toHaveBeenCalled()
    expect(screen.queryByRole('button', { name: 'DOCX' })).not.toBeInTheDocument()
  })
})
