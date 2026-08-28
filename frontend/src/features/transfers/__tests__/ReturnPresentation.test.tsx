import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ReturnModal } from '../ReturnFlow'
import * as apiClient from '../../../api'
import { canonicalIssueDetails, canonicalReturnDetails, change, deferred, fillReturn, issued, mockApi, response, returnFields, returnResult, t, tasks as issueTasks } from './fixtures'
import type { BulkReturnResult } from '../../../types'

const tasks = issueTasks.map((task, index) => ({ ...task, slot_code: index === 0 ? 'RETURNED_BY' : 'ACCEPTED_RETURN' }))

// Isolated HTTP fixtures, using the real API client and signature component.
beforeEach(() => {
  vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue({ fillRect: vi.fn(), beginPath: vi.fn(), moveTo: vi.fn(), lineTo: vi.fn(), stroke: vi.fn() } as unknown as CanvasRenderingContext2D)
  vi.spyOn(HTMLCanvasElement.prototype, 'toDataURL').mockReturnValue('data:image/png;base64,dGVzdA==')
  vi.spyOn(HTMLCanvasElement.prototype, 'getBoundingClientRect').mockReturnValue({ x: 0, y: 0, left: 0, top: 0, width: 360, height: 180, bottom: 180, right: 360, toJSON: () => ({}) })
  Object.defineProperty(HTMLCanvasElement.prototype, 'setPointerCapture', { value: vi.fn(), configurable: true })
  vi.stubGlobal('PointerEvent', MouseEvent)
})
afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); document.body.style.overflow = '' })

const modal = () => screen.getByRole('dialog', { name: t('bulk.return') })
function setup(result: BulkReturnResult, read: (path: string) => Response | Promise<Response>, finalConfirm?: Promise<Response>) {
  let confirmations = 0
  let cancelled = false
  const request = mockApi((path, init) => {
    if (path === '/api/transfers/bulk-return') return response(result)
    if (path === `/api/transfer-batches/${result.batch_id}/cancel`) {
      cancelled = true
      return response({ batch_id: result.batch_id, batch_reference: result.batch_reference, status: 'CANCELLED', cancelled_transfers: result.returned.length, invalidated_signing_sessions: 1, message: 'QA' })
    }
    if (path.startsWith('/api/signing/')) {
      if (path.endsWith('/confirm')) {
        confirmations += 1
        if (confirmations === tasks.length && finalConfirm) return finalConfirm
      }
      if (init.method === 'POST') return response({ document_status: 'SIGNED' })
      return response({ document_number: 'QA-RETURN-ACT', document_version: 1, participant: {}, operation_role: 'QA', consent_notice: 'QA consent' })
    }
    // No progress request is allowed before the final confirmation or explicit cancellation.
    expect(confirmations === tasks.length || cancelled).toBe(true)
    return read(path)
  })
  return request
}
async function begin(result: BulkReturnResult, done = vi.fn(), close = vi.fn()) {
  const user = userEvent.setup()
  render(<ReturnModal items={issued} onClose={close} onComplete={done} />)
  for (const item of result.returned) {
    await user.click(screen.getByLabelText(`Връщане на машина №${item.machine_number}`))
    fillReturn(item.machine_number)
    if (item.new_status === 'REPAIR') await user.click(returnFields(item.machine_number).getByRole('radio', { name: t('bulk.outcomeRepair') }))
    fireEvent.change(returnFields(item.machine_number).getByLabelText(t('common.notes')), { target: { value: ` QA retained note ${item.machine_number} ` } })
  }
  await user.click(screen.getByRole('button', { name: t('bulk.reviewConfirm') }))
  await user.click(screen.getByRole('button', { name: t('bulk.confirmReturn') }))
  await screen.findByRole('button', { name: t('signature.review') })
  return { user, done, close }
}
async function sign(user: ReturnType<typeof userEvent.setup>) {
  await waitFor(() => expect(screen.getByRole('button', { name: t('signature.review') })).toBeEnabled())
  const canvas = screen.getByLabelText(t('signature.canvas'))
  fireEvent.pointerDown(canvas, { pointerId: 1, clientX: 10, clientY: 10 })
  for (let i = 0; i < 8; i += 1) fireEvent.pointerMove(canvas, { pointerId: 1, clientX: 20 + i, clientY: 30 + i })
  fireEvent.pointerUp(canvas, { pointerId: 1 })
  await user.click(screen.getByRole('checkbox', { name: 'QA consent' }))
  await user.click(screen.getByRole('button', { name: t('signature.review') }))
  await user.click(await screen.findByRole('button', { name: t('signature.confirm') }))
}
async function cancel(user: ReturnType<typeof userEvent.setup>) {
  await user.click(screen.getByRole('button', { name: t('signature.reject') }))
  await user.click(await screen.findByRole('button', { name: t('bulk.cancelPendingAction') }))
  change(t('bulk.cancelReason'), 'QA cancellation')
  const dialog = screen.getByLabelText(t('bulk.cancelReason')).closest('[role="dialog"]')!
  await user.click(screen.getByRole('button', { name: t('bulk.cancelConfirm') }))
  await user.click(await within(dialog as HTMLElement).findByRole('button', { name: t('common.done') }))
}
function expectProgress(returned: number, issuedCount: number, status: 'batch.partiallyReturned' | 'batch.returned' | 'batch.active') {
  const view = within(modal())
  expect(view.getByText(t(status))).toBeVisible()
  expect(view.getByText(`Върнати: ${returned} · Все още издадени: ${issuedCount} · Общо: 2`)).toBeVisible()
  expect(modal().querySelector('.batch-awaiting')).toBeNull()
}

describe('canonical return result presentation after server-confirmed operations', () => {
  it.each(['partial REPAIR', 'full READY'] as const)('refreshes %s without local progress arithmetic or extra returns', async mode => {
    const result = returnResult(tasks)
    if (mode === 'full READY') {
      result.returned[0].new_status = 'READY'
      result.returned.push({ ...result.returned[0], transfer_id: 102, machine_id: 2, machine_number: '5', official_document_id: 302, signing_tasks: [], documents: result.returned[0].documents.map(document => ({ ...document, id: document.id + 10, filename: `QA-302.${document.format}`, download_endpoint: `/api/generated-documents/${document.id + 10}/download` })) })
      result.batches[0].awaiting_signature_machines = 2
    }
    const operation = canonicalReturnDetails(result)
    const original = canonicalIssueDetails(result)
    const download = vi.spyOn(apiClient, 'downloadApiFile').mockResolvedValue()
    // The server's finalized document list is authoritative too (never stale draft metadata).
    operation.transfers[0].return_documents = operation.transfers[0].return_documents.map(document => ({ ...document, filename: `final-${document.filename}` }))
    const finalConfirm = deferred<Response>()
    const progress = deferred<Response>()
    const request = setup(result, path => path === '/api/transfer-batches/12' ? response(operation) : progress.promise, finalConfirm.promise)
    const { user, done, close } = await begin(result)
    await sign(user)
    expect(done).not.toHaveBeenCalled()
    await sign(user)
    expect(request.mock.calls.some(([path]) => String(path).startsWith('/api/transfer-batches/'))).toBe(false)
    await act(async () => finalConfirm.resolve(response({ document_status: 'SIGNED' })))
    expect(await screen.findByText(t('common.loading'))).toBeVisible()
    expect(screen.queryByText(t('bulk.returnSuccess'))).not.toBeInTheDocument()
    expect(modal().querySelector('.batch-card')).toBeNull() // pre-signature counts are not final evidence
    expect(done).not.toHaveBeenCalled()
    await act(async () => progress.resolve(response(original)))
    expect(await screen.findByRole('heading', { name: t('bulk.returnSuccess') })).toBeVisible()
    const partial = mode === 'partial REPAIR'
    expectProgress(partial ? 1 : 2, partial ? 1 : 0, partial ? 'batch.partiallyReturned' : 'batch.returned')
    const rows = modal().querySelectorAll('.return-confirm-list > div')
    expect(rows).toHaveLength(partial ? 1 : 2)
    expect(rows[0]).toHaveTextContent(t(partial ? 'status.repair' : 'status.ready'))
    if (partial) {
      expect(rows[0]).not.toHaveTextContent('№5')
      expect(original.transfers[1]).toMatchObject({ current_status: 'ISSUED', is_active: true, returned_at: null, return_status: null, return_documents: [] })
    }
    expect(screen.getAllByRole('button', { name: 'DOCX' })).toHaveLength(partial ? 1 : 2)
    expect(screen.getAllByRole('button', { name: 'PDF' })).toHaveLength(partial ? 1 : 2)
    await user.click(screen.getAllByRole('button', { name: 'DOCX' })[0])
    expect(download).toHaveBeenCalledWith(operation.transfers[0].return_documents[0].download_endpoint, operation.transfers[0].return_documents[0].filename)
    expect(done).toHaveBeenCalledTimes(1)
    expect(close).not.toHaveBeenCalled()
    expect(request.mock.calls.filter(([, init]) => init?.method === 'POST').map(([path]) => path)).toEqual([
      '/api/transfers/bulk-return', ...tasks.flatMap(task => [task.signing_endpoint, `${task.signing_endpoint}/confirm`]),
    ])
    expect(JSON.parse(String(request.mock.calls[0][1]?.body)).items.map((item: { transfer_id: number }) => item.transfer_id)).toEqual(partial ? [101] : [101, 102])
  })

  it('refreshes cancelled pending return progress while leaving the original issue active', async () => {
    const result = returnResult(tasks)
    const operation = canonicalReturnDetails(result, true)
    const original = canonicalIssueDetails(result, true)
    const pending = deferred<Response>()
    const request = setup(result, path => path === '/api/transfer-batches/12' ? response(operation) : pending.promise)
    const { user, done, close } = await begin(result)
    await cancel(user)
    expect(screen.getByText(t('common.loading'))).toBeVisible()
    expect(modal().querySelector('.batch-card')).toBeNull()
    expect(done).not.toHaveBeenCalled()
    await act(async () => pending.resolve(response(original)))
    expect(await screen.findByRole('heading', { name: t('bulk.cancelSuccess') })).toBeVisible()
    expectProgress(0, 2, 'batch.active')
    expect(screen.getByText(t('status.cancelled'))).toBeVisible()
    expect(operation.status).toBe('CANCELLED')
    expect(original.transfers.every(item => item.current_status === 'ISSUED' && item.is_active)).toBe(true)
    expect(screen.queryByRole('button', { name: 'DOCX' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: t('bulk.cancelPendingAction') })).not.toBeInTheDocument()
    expect(done).toHaveBeenCalledTimes(1)
    expect(close).not.toHaveBeenCalled()
    expect(request.mock.calls.filter(([, init]) => init?.method === 'POST').map(([path]) => path)).toEqual([
      '/api/transfers/bulk-return', `${tasks[0].signing_endpoint}/reject`, '/api/transfer-batches/12/cancel',
    ])
  })

  it.each(['signed', 'cancelled'] as const)('recovers a failed %s refresh without replaying mutations, clearing selection or accepting an older response', async outcome => {
    const result = returnResult(tasks)
    const cancelled = outcome === 'cancelled'
    let attempt = 0
    const stale = deferred<Response>()
    const retry = deferred<Response>()
    const request = setup(result, path => {
      if (path === '/api/transfer-batches/12') {
        attempt += 1
        return attempt === 1 ? response({ detail: { message: 'private refresh diagnostic' } }, 500) : response(canonicalReturnDetails(result, cancelled))
      }
      return attempt === 1 ? stale.promise : retry.promise
    })
    const { user, done } = await begin(result)
    if (cancelled) await cancel(user)
    else { await sign(user); await sign(user) }
    expect(await screen.findByRole('alert')).toHaveTextContent(t('bulk.returnRefreshError'))
    expect(screen.queryByText('private refresh diagnostic')).not.toBeInTheDocument()
    expect(screen.queryByText(t('bulk.returnSuccess'))).not.toBeInTheDocument()
    expect(screen.queryByText(t('bulk.cancelSuccess'))).not.toBeInTheDocument()
    expect(modal().querySelector('.batch-card')).toBeNull()
    expect(screen.queryByRole('button', { name: 'DOCX' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: t('bulk.confirmReturn') })).not.toBeInTheDocument()
    expect(screen.getByRole('region', { name: t('bulk.returnConfirmTitle') })).toHaveTextContent('№4')
    expect(done).not.toHaveBeenCalled()
    const mutations = request.mock.calls.filter(([, init]) => init?.method === 'POST')
    const submitted = String(mutations[0][1]?.body)
    expect(JSON.parse(submitted).items).toEqual([expect.objectContaining({ transfer_id: 101, machine_id: 1, next_status: 'REPAIR', notes: ' QA retained note 4 ', condition_text: ' QA condition 4 ', result_text: ' QA result 4 ' })])
    await user.dblClick(screen.getByRole('button', { name: t('bulk.refreshReturnProgress') }))
    expect(screen.getByRole('button', { name: t('bulk.refreshReturnProgress') })).toBeDisabled()
    expect(attempt).toBe(2)
    await act(async () => retry.resolve(response(canonicalIssueDetails(result, cancelled))))
    await waitFor(() => expect(done).toHaveBeenCalledTimes(1))
    expectProgress(cancelled ? 0 : 1, cancelled ? 2 : 1, cancelled ? 'batch.active' : 'batch.partiallyReturned')
    // A slower sibling read from the failed attempt must not replace the retry's snapshot.
    await act(async () => stale.resolve(response({ ...canonicalIssueDetails(result), ...result.batches[0] })))
    expectProgress(cancelled ? 0 : 1, cancelled ? 2 : 1, cancelled ? 'batch.active' : 'batch.partiallyReturned')
    expect(request.mock.calls.filter(([, init]) => init?.method === 'POST')).toEqual(mutations)
    expect(String(request.mock.calls[0][1]?.body)).toBe(submitted)
    expect(done).toHaveBeenCalledTimes(1)
  })
})
