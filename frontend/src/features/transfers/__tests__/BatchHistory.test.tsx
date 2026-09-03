import { cleanup, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { I18nProvider } from '../../../i18n'
import type { BatchDetails, ProtocolDocument } from '../../../types'
import { BatchDetailsPanel } from '../BatchHistory'

function protocolDocuments(number: string, stem: string): ProtocolDocument[] {
  return [
    { id: Number(`${number.length}1`), document_number: number, format: 'docx', filename: `${stem}.docx`, download_endpoint: `/${stem}.docx` },
    { id: Number(`${number.length}2`), document_number: number, format: 'pdf', filename: `${stem}.pdf`, download_endpoint: `/${stem}.pdf` },
  ]
}

function batchDetails(): BatchDetails {
  return {
    batch_id: 11,
    batch_reference: 'QA-BATCH-11',
    status: 'PARTIALLY_RETURNED',
    total_machines: 2,
    returned_machines: 1,
    still_issued_machines: 1,
    awaiting_signature_machines: 0,
    machine_numbers: ['4', '5'],
    created_at: '2026-08-01T09:00:00Z',
    operation: 'ISSUE',
    zip_download_endpoint: '/transfer-batches/11/documents.zip',
    transfers: [
      {
        transfer_id: 101,
        machine_id: 1,
        machine_number: '4',
        machine_name: 'QA machine 4',
        brand: 'CombiJet',
        pressure_bar: 500,
        protocol_number: 'QA-ISSUE-4',
        is_active: false,
        issue_status: 'COMPLETED',
        return_status: 'COMPLETED',
        current_status: 'READY',
        documents: protocolDocuments('QA-ISSUE-4', 'issue-4'),
        issue_documents: protocolDocuments('QA-ISSUE-4', 'issue-4'),
        return_documents: protocolDocuments('QA-RETURN-4', 'return-4'),
      },
      {
        transfer_id: 102,
        machine_id: 2,
        machine_number: '5',
        machine_name: 'QA machine 5',
        brand: 'CombiJet',
        pressure_bar: 500,
        protocol_number: 'QA-ISSUE-5',
        is_active: true,
        issue_status: 'COMPLETED',
        return_status: null,
        current_status: 'ISSUED',
        documents: protocolDocuments('QA-ISSUE-5', 'issue-5'),
        issue_documents: protocolDocuments('QA-ISSUE-5', 'issue-5'),
        return_documents: [],
      },
    ],
  }
}

function renderDetails(details = batchDetails(), onDownload = vi.fn(), onCancel?: (value: BatchDetails) => void) {
  const view = render(
    <I18nProvider initialLocale="bg">
      <BatchDetailsPanel details={details} onDownload={onDownload} onCancel={onCancel} />
    </I18nProvider>,
  )
  return { ...view, onDownload }
}

describe('BatchDetailsPanel protocol presentation', () => {
  beforeEach(() => {
    class TestURL extends URL {
      static createObjectURL = vi.fn(() => 'blob:authenticated-transfer-preview')
      static revokeObjectURL = vi.fn()
    }
    vi.stubGlobal('URL', TestURL)
  })

  afterEach(() => {
    cleanup()
    vi.unstubAllGlobals()
  })

  it('renders machine data left and completed issue then return protocols vertically on the right', () => {
    const { container } = renderDetails()
    const item = container.querySelector<HTMLElement>('[data-transfer-id="101"]')!
    expect(item.children[0]).toHaveClass('batch-transfer-machine')
    expect(item.children[1]).toHaveClass('batch-transfer-protocols')
    expect(within(item.children[0] as HTMLElement).getByRole('heading', { name: 'Машина №4' })).toBeVisible()
    expect(within(item.children[0] as HTMLElement).getByText('CombiJet')).toBeVisible()
    expect(within(item.children[0] as HTMLElement).getByText('Върната')).toBeVisible()

    const protocolArea = item.children[1] as HTMLElement
    const blocks = [...protocolArea.querySelectorAll<HTMLElement>('[data-protocol-kind]')]
    expect(blocks.map(block => block.dataset.protocolKind)).toEqual(['issue', 'return'])
    expect(within(blocks[0]).getByText('QA-ISSUE-4')).toBeVisible()
    expect(within(blocks[1]).getByText('QA-RETURN-4')).toBeVisible()
    for (const block of blocks) {
      expect(within(block).getByRole('button', { name: 'DOCX' })).toBeVisible()
      expect(within(block).getByRole('button', { name: 'PDF' })).toBeVisible()
      expect(within(block).getAllByRole('button', { name: 'Преглед' })).toHaveLength(1)
    }
  })

  it('keeps issue-only status without rendering a fake return protocol or leaking another machine documents', () => {
    const { container } = renderDetails()
    const item = container.querySelector<HTMLElement>('[data-transfer-id="102"]')!
    expect(within(item).getByText('QA-ISSUE-5')).toBeVisible()
    expect(item.querySelector('[data-protocol-kind="return"]')).toBeNull()
    expect(within(item).getByText('Машината все още не е приета')).toBeVisible()
    expect(within(item).getByText('Все още издадена')).toBeVisible()
    expect(within(item).queryByText('QA-ISSUE-4')).not.toBeInTheDocument()
    expect(within(item).queryByText('QA-RETURN-4')).not.toBeInTheDocument()
  })

  it('keeps awaiting-signature documents unavailable and preserves cancellation', async () => {
    const details = batchDetails()
    details.awaiting_signature_machines = 1
    details.transfers = [{
      ...details.transfers[0],
      is_active: true,
      issue_status: 'AWAITING_SIGNATURE',
      return_status: null,
      issue_documents: protocolDocuments('QA-DRAFT-4', 'draft-4'),
      return_documents: [],
    }]
    const onCancel = vi.fn()
    const { container } = renderDetails(details, vi.fn(), onCancel)
    const item = container.querySelector<HTMLElement>('[data-transfer-id="101"]')!
    expect(within(item).getAllByText('Очаква подпис').length).toBeGreaterThan(0)
    expect(within(item).queryByRole('button', { name: 'DOCX' })).not.toBeInTheDocument()
    expect(within(item).queryByRole('button', { name: 'PDF' })).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Очаква подпис' })).toBeDisabled()
    await userEvent.click(screen.getByRole('button', { name: 'Анулирай операцията' }))
    expect(onCancel).toHaveBeenCalledOnce()
    expect(onCancel).toHaveBeenCalledWith(details)
  })

  it('uses the shared authenticated PDF preview and keeps ZIP download behavior', async () => {
    const fetchMock = vi.fn(async () => new Response(new Blob(['transfer-pdf'], { type: 'application/pdf' }), {
      status: 200,
      headers: { 'Content-Type': 'application/pdf' },
    }))
    vi.stubGlobal('fetch', fetchMock)
    const onDownload = vi.fn()
    const { container } = renderDetails(batchDetails(), onDownload)
    const returned = container.querySelector<HTMLElement>('[data-transfer-id="101"] [data-protocol-kind="return"]')!

    await userEvent.click(within(returned).getByRole('button', { name: 'Преглед' }))

    const dialog = await screen.findByRole('dialog', { name: 'return-4.pdf' })
    expect(dialog.querySelector('object.generated-document-preview')).toHaveAttribute('data', 'blob:authenticated-transfer-preview')
    expect(fetchMock).toHaveBeenCalledWith('/api/return-4.pdf', expect.objectContaining({ credentials: 'same-origin' }))

    await userEvent.click(screen.getByRole('button', { name: 'ZIP протоколи' }))
    expect(onDownload).toHaveBeenCalledWith('/transfer-batches/11/documents.zip', 'QA-BATCH-11-protocols.zip')
  })
})
