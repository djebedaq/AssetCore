import { cleanup, render, screen, within } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'

import { I18nProvider } from '../../i18n'
import { CatalogPartsTable } from './CatalogPartsTable'
import type { CatalogPart } from './catalogTypes'

function part(overrides: Partial<CatalogPart>): CatalogPart {
  return {
    id: 1,
    source_record_key: 'test-source-row',
    source_id: 'TEST_SOURCE',
    source_row_index: 1,
    family: 'FALCH_500',
    brand: 'Falch',
    model: 'Wheel Jet 15-e',
    assembly: 'PUMP',
    position: '8',
    part_number: 'TEST-PART',
    order_part_number: 'TEST-PART',
    description: 'Test source part',
    source_description: 'Test source part',
    description_en: 'Test source part',
    description_bg: 'Тестова част',
    quantity: 1,
    quantity_raw: '1,00',
    source_document: 'TEST_SOURCE.pdf',
    source_page: 1,
    source_version: 'PARTS_CATALOG_V2',
    source_document_sha256: '0'.repeat(64),
    verification_status: 'VERIFIED',
    source_anomaly_codes: [],
    is_verified: true,
    translation_version: 'CATALOG_EN_BG_V1',
    translation_qa_status: 'VERIFIED',
    ...overrides,
  }
}

describe('catalog source quantity presentation', () => {
  afterEach(cleanup)

  it('shows integral numeric source quantities cleanly without mutating raw provenance', () => {
    const integral = part({})
    const ambiguous = part({
      id: 2,
      source_record_key: 'test-ambiguous-row',
      position: '22',
      part_number: 'TEST-AMBIGUOUS',
      quantity: null,
      quantity_raw: '1 each',
    })
    render(<I18nProvider initialLocale="bg"><CatalogPartsTable
      parts={[integral, ambiguous]}
      query=""
      selectedPart={null}
      diagramPositions={new Set()}
      onQueryChange={() => undefined}
      onSelect={() => undefined}
      onShowDiagram={() => undefined}
    /></I18nProvider>)

    const rows = screen.getAllByRole('row')
    expect(within(rows[1]).getByText('1')).toBeInTheDocument()
    expect(within(rows[1]).queryByText('1,00')).not.toBeInTheDocument()
    expect(within(rows[2]).getByText('1 each')).toBeInTheDocument()
    expect(integral.quantity_raw).toBe('1,00')
    expect(ambiguous.quantity_raw).toBe('1 each')
  })
})
