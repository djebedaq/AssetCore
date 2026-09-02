import { cleanup, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { I18nProvider, type TranslationKey } from '../../i18n'
import OfficialDocumentSection from './OfficialDocumentSection'
import type { OfficialRegistryDocument, OfficialRegistryItem, OfficialRegistrySection } from './types'

const issueDocument: OfficialRegistryDocument = {
  document_type: 'TRANSFER_ISSUE',
  document_number: 'TR-REG-017',
  official_document_id: 17,
  version: 1,
  version_status: 'SIGNED',
  files: [
    { format: 'docx', download_endpoint: '/issue-17.docx' },
    { format: 'pdf', download_endpoint: '/issue-17.pdf', preview_endpoint: '/issue-17-preview.pdf' },
  ],
}

const returnDocument: OfficialRegistryDocument = {
  document_type: 'TRANSFER_RETURN',
  document_number: 'TR-REG-017-R',
  official_document_id: 18,
  version: 1,
  version_status: 'SIGNED',
  files: [
    { format: 'docx', download_endpoint: '/return-17.docx' },
    { format: 'pdf', download_endpoint: '/return-17.pdf', preview_endpoint: '/return-17-preview.pdf' },
  ],
}

function transferItem(documents: OfficialRegistryDocument[], key = 'transfer:17'): OfficialRegistryItem {
  return {
    registry_key: key,
    domain_id: 17,
    machine_number: '17',
    status: documents.some(document => document.document_type === 'TRANSFER_RETURN') ? 'COMPLETE' : 'INCOMPLETE',
    signature_status: 'SIGNED',
    created_at: '2026-08-22T11:00:00Z',
    started_at: '2026-08-21T09:00:00Z',
    documents,
  }
}

function renderSection(section: OfficialRegistrySection, statusDomain: 'transfer' | 'repair' | 'part' = 'transfer') {
  const keys: { titleKey: TranslationKey; emptyKey: TranslationKey; typeKey: TranslationKey } = statusDomain === 'transfer'
    ? { titleKey: 'official.sectionTransfers', emptyKey: 'official.emptyTransfers', typeKey: 'official.typeTransferLifecycle' }
    : statusDomain === 'repair'
      ? { titleKey: 'official.sectionRepairs', emptyKey: 'official.emptyRepairs', typeKey: 'official.typeRepair' }
      : { titleKey: 'official.sectionParts', emptyKey: 'official.emptyParts', typeKey: 'official.typeParts' }
  return render(
    <I18nProvider initialLocale="bg">
      <OfficialDocumentSection section={section} statusDomain={statusDomain} {...keys} />
    </I18nProvider>,
  )
}

function protocol(number: string): HTMLElement {
  const element = screen.getByText(number).closest<HTMLElement>('[data-document-type]')
  expect(element).not.toBeNull()
  return element!
}

describe('official transfer protocol layout', () => {
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

  it('keeps machine metadata left and orders every real protocol vertically on the right', () => {
    const unknownDocument: OfficialRegistryDocument = {
      document_type: 'TRANSFER_ARCHIVE_NOTE',
      document_number: 'TR-REG-017-X',
      files: [{ format: 'docx', download_endpoint: '/extra-17.docx' }],
    }
    renderSection({
      count: 1,
      items: [transferItem([unknownDocument, returnDocument, issueDocument])],
    })

    const item = screen.getByRole('listitem')
    expect(item.children[0]).toHaveClass('official-transfer-info')
    expect(item.children[1]).toHaveClass('official-transfer-protocols')
    expect(within(item.children[0] as HTMLElement).getByRole('heading', { name: 'Машина №17' })).toBeVisible()

    const blocks = within(item.children[1] as HTMLElement).getAllByText(/Протокол|Друг документ/)
      .map(label => label.closest<HTMLElement>('[data-document-type]'))
      .filter((element): element is HTMLElement => element !== null)
    expect(blocks.map(block => block.dataset.documentType)).toEqual([
      'TRANSFER_ISSUE',
      'TRANSFER_RETURN',
      'TRANSFER_ARCHIVE_NOTE',
    ])

    for (const number of ['TR-REG-017', 'TR-REG-017-R']) {
      const documentBlock = protocol(number)
      expect(within(documentBlock).getByRole('button', { name: 'DOCX' })).toBeVisible()
      expect(within(documentBlock).getByRole('button', { name: 'PDF' })).toBeVisible()
      expect(within(documentBlock).getAllByRole('button', { name: 'Преглед' })).toHaveLength(1)
    }
    expect(screen.getByText('TR-REG-017-X')).toBeVisible()
  })

  it('renders issue-only and return-only lifecycles without invented placeholders', () => {
    renderSection({
      count: 2,
      items: [
        transferItem([issueDocument], 'transfer:issue-only'),
        { ...transferItem([returnDocument], 'transfer:return-only'), machine_number: '18' },
      ],
    })

    const items = screen.getAllByRole('listitem')
    expect(within(items[0]).getByText('Протокол предаване')).toBeVisible()
    expect(within(items[0]).queryByText('Протокол приемане')).not.toBeInTheDocument()
    expect(within(items[1]).getByText('Протокол приемане')).toBeVisible()
    expect(within(items[1]).queryByText('Протокол предаване')).not.toBeInTheDocument()
  })

  it('leaves repair and part sections on the existing generic registry table', () => {
    const repair: OfficialRegistryDocument = {
      document_type: 'REPAIR_PROTOCOL',
      document_number: 'REP-REG-011',
      files: [{ format: 'pdf', download_endpoint: '/repair.pdf' }],
    }
    const parts: OfficialRegistryDocument = {
      document_type: 'PART_REQUEST',
      document_number: 'PR-REG-013',
      files: [{ format: 'docx', download_endpoint: '/parts.docx' }],
    }
    const repairView = renderSection({ count: 1, items: [{ ...transferItem([repair], 'repair:11'), machine_number: '11' }] }, 'repair')
    expect(repairView.container.querySelector('.official-registry-table')).not.toBeNull()
    expect(repairView.container.querySelector('.official-transfer-registry')).toBeNull()
    expect(screen.getByText('Ремонтен протокол')).toBeVisible()
    expect(screen.getByRole('button', { name: 'PDF' })).toBeVisible()
    repairView.unmount()

    renderSection({ count: 1, items: [{ ...transferItem([parts], 'part-request:13'), machine_number: '13' }] }, 'part')
    expect(screen.getByRole('table')).toBeVisible()
    expect(screen.getByText('Протокол за заявка за части')).toBeVisible()
    expect(screen.getByRole('button', { name: 'Word' })).toBeVisible()
  })

  it('uses the shared authenticated object-url preview for a transfer PDF', async () => {
    const fetchMock = vi.fn(async () => new Response(new Blob(['transfer-pdf'], { type: 'application/pdf' }), {
      status: 200,
      headers: { 'Content-Type': 'application/pdf' },
    }))
    vi.stubGlobal('fetch', fetchMock)
    renderSection({ count: 1, items: [transferItem([issueDocument])] })

    await userEvent.click(within(protocol('TR-REG-017')).getByRole('button', { name: 'Преглед' }))

    const dialog = await screen.findByRole('dialog', { name: 'TR-REG-017-v1.pdf' })
    expect(dialog.querySelector('object.generated-document-preview')).toHaveAttribute('data', 'blob:authenticated-transfer-preview')
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/issue-17-preview.pdf',
      expect.objectContaining({ credentials: 'same-origin' }),
    )
  })
})
