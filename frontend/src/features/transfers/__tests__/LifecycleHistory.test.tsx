import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { clearSessionUser, setSessionUser } from '../../../permissions'
import type { BatchDetails, BatchProgress, ReturnOperation, UserSession } from '../../../types'
import BulkTransfers from '../BulkTransfers'
import { BatchProgressCard } from '../BatchHistory'
import { canonicalIssueDetails, canonicalReturnDetails, mockApi, response, returnResult, t } from './fixtures'

const listPath = '/api/transfer-batches?view=lifecycles'

function lifecycle(returned = 2): BatchDetails {
  const result = returnResult()
  result.returned = [0, 1].slice(0, returned).map(index => ({
    ...result.returned[0], transfer_id: 101 + index, machine_id: 1 + index,
    machine_number: String(4 + index),
    documents: result.returned[0].documents.map(document => ({ ...document, document_number: `QA-RETURN-${index + 1}` })),
  }))
  return { ...canonicalIssueDetails(result), cancellable_batch_ids: [], return_operations: [] }
}

function operation(status = 'COMPLETED'): ReturnOperation {
  return {
    batch_id: 12, batch_reference: 'QA-RETURN-12', created_at: '2026-08-01T10:00:00Z',
    status: status === 'COMPLETED' ? 'RETURNED' : 'ACTIVE', signing_status: status,
    transfer_ids: [101], issue_batch_ids: [11], machine_numbers: ['4'],
    signing_document_id: 91, batch_manifest_sha256: 'b'.repeat(64),
  }
}

beforeEach(() => setSessionUser({ permissions: ['transfers.view', 'transfers.create', 'transfers.return'], preferred_language: 'bg' } as UserSession))
afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.unstubAllGlobals(); clearSessionUser() })

describe('authoritative lifecycle presentation', () => {
  it.each([[2, 0], [1, 1]])('renders a lifecycle once with returned=%i, still issued=%i', async (returned, stillIssued) => {
    const detail = lifecycle(returned)
    detail.return_operations = [operation()]
    const request = mockApi(path => {
      if (path === listPath) return response([detail])
      if (path === '/api/transfer-batches/11') return response(detail)
      return response([])
    })
    const { container } = render(<BulkTransfers onChanged={vi.fn()} />)
    await screen.findByRole('heading', { name: '№4, №5' })
    expect(container.querySelectorAll('.batch-card')).toHaveLength(1)
    expect(screen.getByText(`Върнати: ${returned} · Все още издадени: ${stillIssued} · Общо: 2`)).toBeVisible()
    expect(screen.getByText(/Техническа референция.*QA-BATCH/)).toBeVisible()
    expect(request.mock.calls.some(([path]) => path === '/api/transfer-batches')).toBe(false)
    await userEvent.click(screen.getByRole('button', { name: t('common.details') }))
    const transfers = await waitFor(() => {
      const elements = container.querySelectorAll<HTMLElement>('[data-transfer-id]')
      expect(elements).toHaveLength(2)
      return elements
    })
    const first = within(transfers[0])
    expect(first.getByText(t('bulk.issueProtocol'))).toBeVisible()
    expect(first.getByText(t('bulk.returnProtocol'))).toBeVisible()
    expect(first.getAllByRole('button', { name: 'DOCX' })).toHaveLength(2)
    expect(first.getAllByRole('button', { name: 'PDF' })).toHaveLength(2)
    expect(screen.getByRole('region', { name: t('bulk.returnOperations') })).toHaveTextContent('QA-RETURN-12')
    expect(container.querySelectorAll('.batch-card')).toHaveLength(1)
  })

  it('updates the same authoritative card after a second return without discarding its DOM identity', () => {
    const onOpen = vi.fn()
    const { container, rerender } = render(<BatchProgressCard key={11} batch={lifecycle(1)} onOpen={onOpen} />)
    const card = container.querySelector('.batch-card')
    expect(card).toHaveTextContent('Върнати: 1 · Все още издадени: 1 · Общо: 2')
    rerender(<BatchProgressCard key={11} batch={lifecycle(2)} onOpen={onOpen} />)
    expect(container.querySelectorAll('.batch-card')).toHaveLength(1)
    expect(container.querySelector('.batch-card')).toBe(card)
    expect(card).toHaveTextContent('Върнати: 2 · Все още издадени: 0 · Общо: 2')
  })

  it('preserves server order and distinct IDs even for identical references, counts, dates and machines', async () => {
    const original = lifecycle()
    const rows: BatchProgress[] = [31, 21, 11].map(batch_id => ({ ...original, batch_id }))
    const opened: number[] = []
    mockApi(path => {
      if (path === listPath) return response(rows)
      const match = path.match(/^\/api\/transfer-batches\/(\d+)$/)
      if (match) {
        const id = Number(match[1]); opened.push(id)
        return response({ ...original, batch_id: id })
      }
      return response([])
    })
    const { container } = render(<BulkTransfers onChanged={vi.fn()} />)
    await waitFor(() => expect(container.querySelectorAll('.batch-card')).toHaveLength(3))
    const cards = [...container.querySelectorAll<HTMLElement>('.batch-card')]
    for (const card of cards) await userEvent.click(within(card).getByRole('button', { name: t('common.details') }))
    await waitFor(() => expect(opened).toEqual([31, 21, 11]))
    // A later issue of the same machine remains its own lifecycle; no fuzzy deduplication.
    expect(container.querySelectorAll('.batch-card')).toHaveLength(3)
    expect(new Set([...container.querySelectorAll('.batch-list > div')])).toHaveProperty('size', 3)
  })

  it('opens the exact pending return and cancels it, never the issue lifecycle', async () => {
    const detail = lifecycle(0)
    detail.awaiting_signature_machines = 1
    detail.cancellable_batch_ids = [12]
    detail.return_operations = [operation('AWAITING_SIGNATURE')]
    const opDetail: BatchDetails = {
      ...canonicalReturnDetails(returnResult()), batch_reference: 'QA-RETURN-12',
      status: 'ACTIVE', awaiting_signature_machines: 1, cancellable_batch_ids: [12],
      transfers: canonicalReturnDetails(returnResult()).transfers.map(item => ({ ...item, return_status: 'AWAITING_SIGNATURE', return_documents: [] })),
    }
    let cancelled = false
    const request = mockApi((path, init) => {
      if (path === listPath) return response([{ ...detail, cancellable_batch_ids: cancelled ? [] : [12] }])
      if (path === '/api/transfer-batches/11') return response(detail)
      if (path === '/api/transfer-batches/12') return response(opDetail)
      if (path === '/api/transfer-batches/12/cancel' && init.method === 'POST') {
        cancelled = true
        return response({ batch_id: 12, batch_reference: 'QA-RETURN-12', status: 'CANCELLED', cancelled_transfers: 1, invalidated_signing_sessions: 2, message: 'QA' })
      }
      return response([])
    })
    render(<BulkTransfers onChanged={vi.fn()} />)
    await screen.findByRole('heading', { name: '№4, №5' })
    expect(screen.queryByRole('button', { name: t('bulk.cancelPendingAction') })).not.toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: t('common.details') }))
    const returns = await screen.findByRole('region', { name: t('bulk.returnOperations') })
    expect(screen.queryByRole('button', { name: t('bulk.cancelPendingAction') })).not.toBeInTheDocument()
    await userEvent.click(within(returns).getByRole('button', { name: t('common.details') }))
    const dialog = await screen.findByRole('dialog', { name: `${t('bulk.returnOperation')}: QA-RETURN-12` })
    await userEvent.click(within(dialog).getByRole('button', { name: t('bulk.cancelPendingAction') }))
    await screen.findByText(t('bulk.cancelReturnEffect'))
    fireEvent.change(screen.getByLabelText(t('bulk.cancelReason')), { target: { value: 'QA exact operation' } })
    await userEvent.click(screen.getByRole('button', { name: t('bulk.cancelConfirm') }))
    await screen.findByText(t('bulk.cancelSuccess'))
    expect(request.mock.calls.filter(([, init]) => init?.method === 'POST').map(([path]) => path)).toEqual(['/api/transfer-batches/12/cancel'])
    expect(request.mock.calls.filter(([path]) => path === listPath)).toHaveLength(2)
  })

  it('does not expose cancellation on completed or cancelled return history with shared pending transfers', () => {
    const batch = { ...lifecycle(), operation: 'RETURN', status: 'CANCELLED', awaiting_signature_machines: 2, cancellable_batch_ids: [] }
    render(<BatchProgressCard batch={batch} onCancel={vi.fn()} />)
    expect(screen.queryByRole('button', { name: t('bulk.cancelPendingAction') })).not.toBeInTheDocument()
  })
})
