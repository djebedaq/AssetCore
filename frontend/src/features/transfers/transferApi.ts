import { api } from '../../api'
import type { BatchDetails, BatchProgress, BulkIssueResult, BulkReturnResult, CancelTransferBatchResponse, Location, TransferAvailability } from '../../types'
import type { buildIssuePayload, buildReturnPayload } from './transferState'

// The existing authenticated client owns headers, CSRF, cookies and structured errors.
export const transferApi = {
  availability: () => api<TransferAvailability[]>('/transfers/availability'),
  locations: () => api<Location[]>('/locations'),
  batches: () => api<BatchProgress[]>('/transfer-batches'),
  batch: (batchId: number) => api<BatchDetails>(`/transfer-batches/${batchId}`),
  issue: (payload: ReturnType<typeof buildIssuePayload>) =>
    api<BulkIssueResult>('/transfers/bulk-issue', { method: 'POST', body: JSON.stringify(payload) }),
  return: (payload: ReturnType<typeof buildReturnPayload>) =>
    api<BulkReturnResult>('/transfers/bulk-return', { method: 'POST', body: JSON.stringify(payload) }),
  cancel: (batchId: number, reason: string) =>
    api<CancelTransferBatchResponse>(`/transfer-batches/${batchId}/cancel`, { method: 'POST', body: JSON.stringify({ reason }) }),
}
