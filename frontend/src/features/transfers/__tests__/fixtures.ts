// Synthetic HTTP fixtures only; never seed or write these records to a database.
import { fireEvent, screen, within } from '@testing-library/react'
import { vi } from 'vitest'
import { translate, type TranslationKey } from '../../../i18n'
import type { BatchDetails, BulkIssueResult, BulkReturnResult, SigningTask, TransferAvailability } from '../../../types'

export const t = (key: TranslationKey) => translate('bg', key)
export const machines: TransferAvailability[] = [
  { machine_id: 1, machine_number: '4', brand: 'CombiJet', pressure_bar: 500, status: 'READY', location: 'Цех', available: true, returnable: false },
  { machine_id: 2, machine_number: '5', brand: 'CombiJet', pressure_bar: 500, status: 'READY', location: 'Цех', available: true, returnable: false },
  { machine_id: 3, machine_number: '7', brand: 'Falch', pressure_bar: 1000, status: 'READY', available: false, returnable: false, active_transfer_id: 103, unavailable_reason: 'Тестов pending transfer от API.' },
]
export const issued: TransferAvailability[] = machines.slice(0, 2).map((item, index) => ({
  ...item, available: false, returnable: true, status: 'ISSUED', active_transfer_id: 101 + index,
  protocol_number: `QA-ISSUE-${index + 1}`, batch_reference: 'QA-BATCH', current_recipient_or_location: 'Тестов Външен Получател',
}))
export const locations = [{ id: 1, name: 'Цех', is_active: true }, { id: 2, name: 'QA inactive', is_active: false }]
export const checklist = () => ['pump', 'supply_hose', 'hp_hose', 'gun', 'nozzle', 'tips', 'cable', 'plug', 'chassis', 'body']
  .map(code => ({ code, condition: 'GOOD', note: null as string | null, length_m: null as number | null }))
export const tasks: SigningTask[] = ['ACCEPTANCE', 'HANDOVER'].map((slot_code, index) => ({
  participant_id: index + 1, slot_code, operation_role: `QA role ${index + 1}`, signer_name: `QA signer ${index + 1}`,
  signing_token: `test-signature-${index + 1}`, signing_endpoint: `/api/signing/test-signature-${index + 1}`, expires_at: '2099-01-01T00:00:00Z',
}))
const documents = (id: number) => ['docx', 'pdf'].map((format, index) => ({
  id: id * 10 + index, format, filename: `QA-${id}.${format}`, download_endpoint: `/api/protocol-documents/${id * 10 + index}/download`,
}))
export const issueResult = (signing: SigningTask[] = []): BulkIssueResult => ({
  message: 'QA', batch_id: 11, batch_reference: 'QA-BATCH', batch_manifest_sha256: 'a'.repeat(64), signing_document_id: 90,
  signing_tasks: signing, zip_download_endpoint: '/api/transfer-batches/11/documents.zip',
  transfers: machines.slice(0, 2).map((item, index) => ({
    machine_id: item.machine_id, machine_number: item.machine_number, transfer_id: 101 + index, protocol_number: `QA-ISSUE-${index + 1}`,
    workflow_status: signing.length ? 'AWAITING_SIGNATURE' : 'COMPLETED', official_document_id: 201 + index,
    signing_tasks: index === 0 ? signing : [], documents: documents(101 + index),
  })),
})
export const returnResult = (signing: SigningTask[] = []): BulkReturnResult => ({
  message: 'QA', batch_id: 12, batch_reference: 'QA-RETURN', batch_manifest_sha256: 'b'.repeat(64), signing_document_id: 91,
  signing_tasks: signing,
  returned: [{ transfer_id: 101, machine_id: 1, machine_number: '4', new_status: 'REPAIR', workflow_status: signing.length ? 'AWAITING_SIGNATURE' : 'COMPLETED', official_document_id: 301, signing_tasks: signing, documents: documents(301).map(document => ({ ...document, download_endpoint: `/api/generated-documents/${document.id}/download` })) }],
  batches: [{ batch_id: 11, batch_reference: 'QA-BATCH', status: signing.length ? 'ACTIVE' : 'PARTIALLY_RETURNED', total_machines: 2, returned_machines: signing.length ? 0 : 1, still_issued_machines: signing.length ? 2 : 1, awaiting_signature_machines: signing.length ? 1 : 0, machine_numbers: ['4', '5'] }],
})
// GET /transfer-batches/{id}: the return operation and the original issue batch
// have independent progress, but reference the same individual transfers.
export function canonicalReturnDetails(result: BulkReturnResult, cancelled = false): BatchDetails {
  return {
    batch_id: result.batch_id, batch_reference: result.batch_reference, operation: 'RETURN',
    status: cancelled ? 'CANCELLED' : 'RETURNED', total_machines: result.returned.length,
    returned_machines: cancelled ? 0 : result.returned.length, still_issued_machines: cancelled ? result.returned.length : 0,
    awaiting_signature_machines: 0, machine_numbers: result.returned.map(item => item.machine_number),
    created_at: '2026-08-01T09:00:00Z', zip_download_endpoint: `/api/transfer-batches/${result.batch_id}/documents.zip`,
    batch_manifest_sha256: result.batch_manifest_sha256, signing_document_id: result.signing_document_id,
    transfers: result.returned.map(item => ({
      transfer_id: item.transfer_id, machine_id: item.machine_id, machine_number: item.machine_number,
      machine_name: `QA ${item.machine_number}`, brand: 'CombiJet', pressure_bar: 500,
      protocol_number: `QA-ISSUE-${item.machine_id}`, is_active: cancelled, issue_status: 'COMPLETED',
      return_status: cancelled ? 'CANCELLED' : 'COMPLETED', current_status: cancelled ? 'ISSUED' : item.new_status,
      returned_at: cancelled ? null : '2026-08-01T10:00:00Z', location: cancelled ? 'QA site' : 'Цех',
      documents: documents(item.transfer_id), issue_documents: documents(item.transfer_id), return_documents: cancelled ? [] : item.documents,
    })),
  }
}
export function canonicalIssueDetails(result: BulkReturnResult, cancelled = false): BatchDetails {
  const operation = canonicalReturnDetails(result, cancelled)
  const returned = cancelled ? 0 : result.returned.length
  return {
    ...operation, batch_id: 11, batch_reference: 'QA-BATCH', operation: 'ISSUE',
    status: cancelled ? 'ACTIVE' : returned === 2 ? 'RETURNED' : 'PARTIALLY_RETURNED',
    total_machines: 2, returned_machines: returned, still_issued_machines: 2 - returned, machine_numbers: ['4', '5'],
    zip_download_endpoint: '/api/transfer-batches/11/documents.zip',
    transfers: issued.map(item => operation.transfers.find(transfer => transfer.machine_id === item.machine_id) || {
      transfer_id: item.active_transfer_id!, machine_id: item.machine_id, machine_number: item.machine_number,
      machine_name: `QA ${item.machine_number}`, brand: item.brand, pressure_bar: item.pressure_bar,
      protocol_number: item.protocol_number!, is_active: true, issue_status: 'COMPLETED', return_status: null,
      current_status: 'ISSUED', returned_at: null, location: 'QA site',
      documents: documents(item.active_transfer_id!), issue_documents: documents(item.active_transfer_id!), return_documents: [],
    }),
  }
}
export const details = (): BatchDetails => ({
  ...returnResult().batches[0], status: 'ACTIVE', returned_machines: 0, still_issued_machines: 0, awaiting_signature_machines: 2,
  operation: 'ISSUE', created_at: '2026-08-01T09:00:00Z', zip_download_endpoint: '/api/transfer-batches/11/documents.zip',
  transfers: issueResult(tasks).transfers.map(item => ({ ...item, machine_name: `QA ${item.machine_number}`, brand: 'CombiJet', pressure_bar: 500, is_active: true, issue_status: 'AWAITING_SIGNATURE', return_status: null, current_status: 'READY', issue_documents: item.documents, return_documents: [] })),
})
export const response = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
export function mockApi(handler: (path: string, init: RequestInit) => Response | Promise<Response>) {
  const fetchMock = vi.fn((input: RequestInfo | URL, init: RequestInit = {}) => Promise.resolve(handler(String(input), init)))
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}
export function change(label: string, value: string) { fireEvent.change(screen.getByLabelText(label), { target: { value } }) }
export function fillIssue() {
  change(t('bulk.systemLocation'), '1')
  change(t('bulk.usageText'), '  QA usage  ')
  change(t('profile.firstName'), 'Тестов')
  change(t('profile.middleName'), 'Външен')
  change(t('profile.lastName'), 'Получател')
  change(t('bulk.issueCondition'), '  QA condition  ')
}
export function returnFields(number: string) {
  const section = screen.getByLabelText(`Връщане на машина №${number}`).closest('section')!
  return within(section)
}
export function fillReturn(number: string) {
  const fields = returnFields(number)
  fireEvent.change(fields.getByLabelText(t('bulk.returnCondition')), { target: { value: ` QA condition ${number} ` } })
  fireEvent.change(fields.getByLabelText(t('bulk.returnResult')), { target: { value: ` QA result ${number} ` } })
}
export function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>(done => { resolve = done })
  return { promise, resolve }
}
