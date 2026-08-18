import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { I18nProvider } from '../../i18n'
import { IndustrialCatalog } from './IndustrialCatalog'
import type {
  CatalogDiagram,
  CatalogPart,
  PositionHotspot,
} from './catalogTypes'

const FALCH_MACHINE_ID = 9
const HYDWIN_MACHINE_ID = 20
const FALCH_SOURCE_ID = 'test-only-falch-source'
const HYDWIN_SOURCE_ID = 'test-only-hydwin-source'

function jsonResponse(value: unknown): Response {
  return new Response(JSON.stringify(value), {
    status: 200,
    headers: { 'Content-Type': 'application/json' },
  })
}

function part(overrides: Partial<CatalogPart> = {}): CatalogPart {
  return {
    id: 901,
    source_record_key: 'test-only-falch-part',
    source_id: FALCH_SOURCE_ID,
    source_row_index: 1,
    family: 'FALCH_500',
    brand: 'Falch',
    model: 'Test fixture',
    assembly: 'TEST_ASSEMBLY',
    position: '3',
    part_number: 'TEST-FALCH-3',
    order_part_number: 'TEST-FALCH-3',
    description: 'Falch test-only seal',
    original_name: 'Falch test-only seal',
    quantity: 1,
    quantity_raw: '1',
    valid_for_raw: null,
    repair_kit_code: null,
    source_document: 'TEST_ONLY.pdf',
    source_page: 1,
    source_version: 'PARTS_CATALOG_V2',
    source_document_sha256: 'a'.repeat(64),
    verification_status: 'VERIFIED',
    source_anomaly_codes: [],
    is_verified: true,
    ...overrides,
  }
}

const falchPart = part()
const hydwinPart = part({
  id: 902,
  source_record_key: 'test-only-hydwin-part',
  source_id: HYDWIN_SOURCE_ID,
  family: 'HYDWIN_FUSSEN_500',
  brand: 'HYDWIN/Fussen',
  position: '34',
  part_number: 'TEST-HY-34',
  order_part_number: 'TEST-HY-34',
  description: 'HYDWIN test-only seal',
})

function diagram(id = 991): CatalogDiagram {
  return {
    id,
    source_id: FALCH_SOURCE_ID,
    page_number: 1,
    title: 'Test-only diagram',
    source_pdf_sha256: 'b'.repeat(64),
    render_version: 'TEST_ONLY',
    technical_document_id: 991,
    preview_endpoint: '/technical-library/991/preview?page=1',
    download_endpoint: '/technical-library/991/download',
  }
}

function setupFetch(options: {
  falchDiagrams?: CatalogDiagram[]
  falchParts?: CatalogPart[]
  hotspots?: PositionHotspot[]
} = {}) {
  const falchDiagrams = options.falchDiagrams || []
  const falchParts = options.falchParts || [falchPart]
  const hotspots = options.hotspots || []
  const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
    const path = String(input)
    if (path.endsWith('/api/machines')) return jsonResponse([
      { id: FALCH_MACHINE_ID, inventory_number: '9', name: 'Test fixture Falch', brand: 'Falch', model: 'Test fixture', pressure_bar: 500, status: 'READY', created_at: '2026-01-01T00:00:00', updated_at: '2026-01-01T00:00:00' },
      { id: HYDWIN_MACHINE_ID, inventory_number: '20', name: 'Test fixture HYDWIN', brand: 'HYDWIN/Fussen', model: 'Test fixture', pressure_bar: 500, status: 'READY', created_at: '2026-01-01T00:00:00', updated_at: '2026-01-01T00:00:00' },
    ])
    if (path.endsWith(`/api/catalog/v2/machines/${FALCH_MACHINE_ID}`)) return jsonResponse({
      dataset_version: 'PARTS_CATALOG_V2', supported: true, message: '', machine_id: FALCH_MACHINE_ID,
      machine_number: '9', brand: 'Falch', model: 'Test fixture', family: 'FALCH_500',
      assemblies: [{ source_id: FALCH_SOURCE_ID, family: 'FALCH_500', assembly: 'TEST_ASSEMBLY', title: 'Test-only Falch assembly', part_count: falchParts.length, diagram_count: falchDiagrams.length, verified_hotspot_count: hotspots.length, diagrams: falchDiagrams }],
    })
    if (path.endsWith(`/api/catalog/v2/machines/${HYDWIN_MACHINE_ID}`)) return jsonResponse({
      dataset_version: 'PARTS_CATALOG_V2', supported: true, message: '', machine_id: HYDWIN_MACHINE_ID,
      machine_number: '20', brand: 'HYDWIN/Fussen', model: 'Test fixture', family: 'HYDWIN_FUSSEN_500',
      assemblies: [{ source_id: HYDWIN_SOURCE_ID, family: 'HYDWIN_FUSSEN_500', assembly: 'TEST_ASSEMBLY', title: 'Test-only HYDWIN assembly', part_count: 1, diagram_count: 0, verified_hotspot_count: 0, diagrams: [] }],
    })
    if (path.includes(`/api/catalog/v2/assemblies/${FALCH_SOURCE_ID}?machine_id=${FALCH_MACHINE_ID}`)) return jsonResponse({
      dataset_version: 'PARTS_CATALOG_V2', machine_id: FALCH_MACHINE_ID, machine_number: '9', family: 'FALCH_500',
      source_id: FALCH_SOURCE_ID, assembly: 'TEST_ASSEMBLY', title: 'Test-only Falch assembly', diagrams: falchDiagrams, parts: falchParts,
    })
    if (path.includes(`/api/catalog/v2/assemblies/${HYDWIN_SOURCE_ID}?machine_id=${HYDWIN_MACHINE_ID}`)) return jsonResponse({
      dataset_version: 'PARTS_CATALOG_V2', machine_id: HYDWIN_MACHINE_ID, machine_number: '20', family: 'HYDWIN_FUSSEN_500',
      source_id: HYDWIN_SOURCE_ID, assembly: 'TEST_ASSEMBLY', title: 'Test-only HYDWIN assembly', diagrams: [], parts: [hydwinPart],
    })
    if (path.includes('/api/catalog/v2/repair-kits?')) return jsonResponse([])
    if (path.includes('/api/catalog/v2/diagrams/991/hotspots?')) return jsonResponse(hotspots)
    if (path.includes('/api/technical-library/991/preview?page=1')) {
      return new Response(new Blob(['test-only-preview'], { type: 'image/png' }))
    }
    throw new Error(`Unexpected test request: ${path}`)
  })
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

function CatalogHarness({ defaultMachineId }: { defaultMachineId?: number }) {
  return <I18nProvider initialLocale="bg">
    <IndustrialCatalog defaultMachineId={defaultMachineId} />
  </I18nProvider>
}

async function addFalchPart(user: ReturnType<typeof userEvent.setup>) {
  await user.click(await screen.findByText(falchPart.description))
  await user.click(await screen.findByRole('button', { name: 'Добави към заявка' }))
  expect(screen.getByText('Избрани части: 1')).toBeInTheDocument()
}

describe('machine-bound catalog request cart', () => {
  beforeEach(() => {
    localStorage.clear()
    localStorage.setItem('assetcore_user', JSON.stringify({
      role: 'mechanic',
      permissions: ['assets.view', 'requests.view', 'requests.create', 'parts.view'],
    }))
    const NativeURL = URL
    class MockURL extends NativeURL {
      static createObjectURL = vi.fn(() => 'blob:test-only-diagram')
      static revokeObjectURL = vi.fn()
    }
    vi.stubGlobal('URL', MockURL)
  })

  it('preserves machine, quantities and cart on cancel, then clears all request state on confirmation', async () => {
    setupFetch()
    const user = userEvent.setup()
    render(<CatalogHarness defaultMachineId={FALCH_MACHINE_ID} />)
    await addFalchPart(user)

    const machineSelect = screen.getByLabelText('Избери машина')
    await user.selectOptions(machineSelect, String(HYDWIN_MACHINE_ID))
    expect(await screen.findByRole('dialog', { name: 'Смяна на машината' })).toBeInTheDocument()
    expect(machineSelect).toHaveValue(String(FALCH_MACHINE_ID))
    expect(screen.getByText('Избрани части: 1')).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Отказ' }))
    expect(screen.queryByRole('dialog', { name: 'Смяна на машината' })).not.toBeInTheDocument()
    expect(machineSelect).toHaveValue(String(FALCH_MACHINE_ID))
    expect(screen.getByLabelText(`Заявено количество ${falchPart.part_number}`)).toHaveValue(1)

    await user.selectOptions(machineSelect, String(HYDWIN_MACHINE_ID))
    await user.click(await screen.findByRole('button', { name: 'Смени машината и изчисти заявката' }))
    await screen.findByText(hydwinPart.description)
    expect(machineSelect).toHaveValue(String(HYDWIN_MACHINE_ID))
    expect(screen.getByText('Избрани части: 0')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Отмени добавянето на комплекта' })).not.toBeInTheDocument()
    expect(screen.queryByText(falchPart.description)).not.toBeInTheDocument()
  })

  it('switches immediately without confirmation when the cart is empty', async () => {
    setupFetch()
    const user = userEvent.setup()
    render(<CatalogHarness />)
    const machineSelect = await screen.findByLabelText('Избери машина')

    await user.selectOptions(machineSelect, String(FALCH_MACHINE_ID))
    await screen.findByText(falchPart.description)
    await user.selectOptions(machineSelect, String(HYDWIN_MACHINE_ID))

    await screen.findByText(hydwinPart.description)
    expect(machineSelect).toHaveValue(String(HYDWIN_MACHINE_ID))
    expect(screen.queryByRole('dialog', { name: 'Смяна на машината' })).not.toBeInTheDocument()
  })

  it('clears a populated cart when defaultMachineId changes programmatically', async () => {
    setupFetch()
    const user = userEvent.setup()
    const view = render(<CatalogHarness defaultMachineId={FALCH_MACHINE_ID} />)
    await addFalchPart(user)

    view.rerender(<CatalogHarness defaultMachineId={HYDWIN_MACHINE_ID} />)

    await screen.findByText(hydwinPart.description)
    expect(screen.getByLabelText('Избери машина')).toHaveValue(String(HYDWIN_MACHINE_ID))
    expect(screen.getByText('Избрани части: 0')).toBeInTheDocument()
    expect(screen.queryByRole('dialog', { name: 'Смяна на машината' })).not.toBeInTheDocument()
    expect(screen.queryByText(falchPart.description)).not.toBeInTheDocument()
  })

  it('adds the exact chosen source variant after a multi-variant position click', async () => {
    const variantA = part({ source_record_key: 'test-only-variant-a', position: '0', part_number: 'TEST-VARIANT-A', order_part_number: 'TEST-VARIANT-A', description: 'Test-only variant A', valid_for_raw: 'Variant A' })
    const variantB = part({ id: 903, source_record_key: 'test-only-variant-b', position: '0', part_number: 'TEST-VARIANT-B', order_part_number: 'TEST-VARIANT-B', description: 'Test-only variant B', valid_for_raw: 'Variant B' })
    const testDiagram = diagram()
    setupFetch({
      falchDiagrams: [testDiagram],
      falchParts: [variantA, variantB],
      hotspots: [{ id: 991, hotspot_key: 'test-only-position-0', diagram_id: 991, page_number: 1, position: '0', x: 0.5, y: 0.5, width: 0.03, height: 0.03, is_verified: true, provenance: 'test-only-manual-verification', confidence: 1, variants: [variantA, variantB] }],
    })
    const user = userEvent.setup()
    render(<CatalogHarness defaultMachineId={FALCH_MACHINE_ID} />)

    await user.click(await screen.findByRole('button', { name: 'Поз. 0' }))
    expect(screen.getByText('Избрани части: 0')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: /TEST-VARIANT-B/ }))

    expect(screen.getByText('Избрани части: 1')).toBeInTheDocument()
    expect(screen.getByLabelText('Заявено количество TEST-VARIANT-B')).toHaveValue(1)
    expect(screen.queryByLabelText('Заявено количество TEST-VARIANT-A')).not.toBeInTheDocument()
  })

  it('explains diagrams without verified clickable positions and keeps the official table usable', async () => {
    setupFetch({ falchDiagrams: [diagram()], hotspots: [] })
    const user = userEvent.setup()
    render(<CatalogHarness defaultMachineId={FALCH_MACHINE_ID} />)

    expect(await screen.findByText('За тази схема все още няма визуално проверени кликаеми позиции. Изберете частта от официалния списък под схемата.')).toBeInTheDocument()
    await user.click(screen.getByText(falchPart.description))
    expect(await screen.findByRole('button', { name: 'Добави към заявка' })).toBeInTheDocument()
  })
})
