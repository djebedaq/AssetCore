import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { I18nProvider, type TranslationKey } from '../../i18n'
import OfficialDocumentSection from './OfficialDocumentSection'
import type { OfficialRegistryDocument, OfficialRegistrySection } from './types'

const issueDocument: OfficialRegistryDocument = {
  document_type: 'TRANSFER_ISSUE',
  document_number: 'QA-TRANSFER-17',
  official_document_id: 17,
  version: 1,
  version_status: 'SIGNED',
  files: [
    { format: 'docx', download_endpoint: '/issue-17.docx' },
    { format: 'pdf', download_endpoint: '/issue-17.pdf', preview_endpoint: '/issue-17-preview.pdf' },
  ],
}

function section(document: OfficialRegistryDocument): OfficialRegistrySection {
  return {
    count: 1,
    items: [{
      registry_key: 'transfer:17',
      domain_id: 17,
      machine_number: '17',
      status: 'INCOMPLETE',
      signature_status: 'SIGNED',
      created_at: '2026-08-22T11:00:00Z',
      started_at: '2026-08-21T09:00:00Z',
      documents: [document],
    }],
  }
}

function renderSection(document = issueDocument, domain: 'transfer' | 'repair' | 'part' = 'transfer') {
  const keys: Record<typeof domain, { titleKey: TranslationKey; emptyKey: TranslationKey }> = {
    transfer: { titleKey: 'official.sectionTransfers', emptyKey: 'official.emptyTransfers' },
    repair: { titleKey: 'official.sectionRepairs', emptyKey: 'official.emptyRepairs' },
    part: { titleKey: 'official.sectionParts', emptyKey: 'official.emptyParts' },
  }
  return render(
    <I18nProvider initialLocale="bg">
      <OfficialDocumentSection section={section(document)} statusDomain={domain} {...keys[domain]} />
    </I18nProvider>,
  )
}

describe('official-document registry restoration', () => {
  beforeEach(() => {
    class TestURL extends URL {
      static createObjectURL = vi.fn(() => 'blob:authenticated-official-preview')
      static revokeObjectURL = vi.fn()
    }
    vi.stubGlobal('URL', TestURL)
  })

  afterEach(() => {
    cleanup()
    vi.unstubAllGlobals()
  })

  it('uses the shared category result table for transfers, repairs, and parts', () => {
    const transferView = renderSection()
    expect(transferView.container.querySelector('.official-registry-table')).not.toBeNull()
    expect(transferView.container.querySelector('.official-transfer-registry')).toBeNull()
    expect(screen.getByRole('table')).toBeVisible()
    transferView.unmount()

    const repairView = renderSection({ ...issueDocument, document_type: 'REPAIR_PROTOCOL', document_number: 'QA-REPAIR-17' }, 'repair')
    expect(repairView.container.querySelector('.official-registry-table')).not.toBeNull()
    expect(screen.getByText('Ремонтен протокол')).toBeVisible()
    repairView.unmount()

    renderSection({ ...issueDocument, document_type: 'PART_REQUEST', document_number: 'QA-PARTS-17' }, 'part')
    expect(screen.getByRole('table')).toBeVisible()
    expect(screen.getByText('Протокол за заявка за части')).toBeVisible()
  })

  it('retains the shared authenticated PDF preview in the restored transfer table', async () => {
    const fetchMock = vi.fn(async () => new Response(new Blob(['official-pdf'], { type: 'application/pdf' }), {
      status: 200,
      headers: { 'Content-Type': 'application/pdf' },
    }))
    vi.stubGlobal('fetch', fetchMock)
    renderSection()

    await userEvent.click(screen.getByRole('button', { name: 'Преглед' }))

    const dialog = await screen.findByRole('dialog', { name: 'QA-TRANSFER-17-v1.pdf' })
    expect(dialog.querySelector('object.generated-document-preview')).toHaveAttribute('data', 'blob:authenticated-official-preview')
    expect(fetchMock).toHaveBeenCalledWith('/api/issue-17-preview.pdf', expect.objectContaining({ credentials: 'same-origin' }))
  })
})
