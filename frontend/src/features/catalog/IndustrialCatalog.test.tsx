import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { I18nProvider } from '../../i18n'
import { setSessionUser } from '../../permissions'
import { IndustrialCatalog } from './IndustrialCatalog'
import { catalogDisplayName } from './catalogNames'
import type {
  CatalogDiagram,
  CatalogPart,
  CatalogRepairKit,
  PositionHotspot,
} from './catalogTypes'
import type { UserSession } from '../../types'

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
    source_description: 'Falch test-only seal',
    description_en: 'Falch test-only seal',
    description_bg: 'Тестово уплътнение Falch',
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
    translation_version: 'CATALOG_EN_BG_V1',
    translation_qa_status: 'VERIFIED',
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
  source_description: 'HYDWIN test-only seal',
  description_en: 'HYDWIN test-only seal',
  description_bg: 'Тестово уплътнение HYDWIN',
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
  repairKits?: CatalogRepairKit[]
} = {}) {
  const falchDiagrams = options.falchDiagrams || []
  const falchParts = options.falchParts || [falchPart]
  const hotspots = options.hotspots || []
  const repairKits = options.repairKits || []
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
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
    if (path.includes('/api/catalog/v2/repair-kits?')) return jsonResponse(repairKits)
    if (path.includes('/api/catalog/v2/diagrams/991/hotspots?')) return jsonResponse(hotspots)
    if (path.endsWith('/api/catalog/v2/hotspots/991') && init?.method === 'PATCH') return jsonResponse({ id: 991, x: 0.5, y: 0.5, width: 0.03, height: 0.03, is_verified: true, provenance: 'MANUALLY_CONFIRMED', confidence: 1 })
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
  await user.click(await screen.findByText(catalogDisplayName(falchPart)))
  await user.click(await screen.findByRole('button', { name: 'Добави към заявка' }))
  expect(screen.getByText('Избрани части: 1')).toBeInTheDocument()
}

function pointerTap(
  element: HTMLElement,
  pointerType: 'mouse' | 'touch',
  pointerId = 1,
  x = 100,
  y = 100,
) {
  fireEvent.pointerDown(element, { pointerId, pointerType, clientX: x, clientY: y })
  fireEvent.pointerUp(element, { pointerId, pointerType, clientX: x, clientY: y })
}

describe('machine-bound catalog request cart', () => {
  beforeEach(() => {
    localStorage.clear()
    class TestPointerEvent extends MouseEvent {
      readonly pointerId: number
      readonly pointerType: string

      constructor(type: string, init: PointerEventInit = {}) {
        super(type, init)
        this.pointerId = init.pointerId ?? 0
        this.pointerType = init.pointerType ?? ''
      }
    }
    vi.stubGlobal('PointerEvent', TestPointerEvent)
    setSessionUser({
      role: 'mechanic',
      permissions: ['assets.view', 'requests.view', 'requests.create', 'parts.view'],
    } as UserSession)
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
    await screen.findByText(catalogDisplayName(hydwinPart))
    expect(machineSelect).toHaveValue(String(HYDWIN_MACHINE_ID))
    expect(screen.getByText('Избрани части: 0')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Отмени добавянето на комплекта' })).not.toBeInTheDocument()
    expect(screen.queryByText(catalogDisplayName(falchPart))).not.toBeInTheDocument()
  })

  it('switches immediately without confirmation when the cart is empty', async () => {
    setupFetch()
    const user = userEvent.setup()
    render(<CatalogHarness />)
    const machineSelect = await screen.findByLabelText('Избери машина')

    await user.selectOptions(machineSelect, String(FALCH_MACHINE_ID))
    await screen.findByText(catalogDisplayName(falchPart))
    await user.selectOptions(machineSelect, String(HYDWIN_MACHINE_ID))

    await screen.findByText(catalogDisplayName(hydwinPart))
    expect(machineSelect).toHaveValue(String(HYDWIN_MACHINE_ID))
    expect(screen.queryByRole('dialog', { name: 'Смяна на машината' })).not.toBeInTheDocument()
  })

  it('clears a populated cart when defaultMachineId changes programmatically', async () => {
    setupFetch()
    const user = userEvent.setup()
    const view = render(<CatalogHarness defaultMachineId={FALCH_MACHINE_ID} />)
    await addFalchPart(user)

    view.rerender(<CatalogHarness defaultMachineId={HYDWIN_MACHINE_ID} />)

    await screen.findByText(catalogDisplayName(hydwinPart))
    expect(screen.getByLabelText('Избери машина')).toHaveValue(String(HYDWIN_MACHINE_ID))
    expect(screen.getByText('Избрани части: 0')).toBeInTheDocument()
    expect(screen.queryByRole('dialog', { name: 'Смяна на машината' })).not.toBeInTheDocument()
    expect(screen.queryByText(catalogDisplayName(falchPart))).not.toBeInTheDocument()
  })

  it('selects the exact source variant without adding it until the explicit action', async () => {
    const variantA = part({ source_record_key: 'test-only-variant-a', position: '0', part_number: 'TEST-VARIANT-A', order_part_number: 'TEST-VARIANT-A', description: 'Test-only variant A', valid_for_raw: 'Variant A' })
    const variantB = part({ id: 903, source_record_key: 'test-only-variant-b', position: '0', part_number: 'TEST-VARIANT-B', order_part_number: 'TEST-VARIANT-B', description: 'Test-only variant B', valid_for_raw: 'Variant B' })
    const testDiagram = diagram()
    setupFetch({
      falchDiagrams: [testDiagram],
      falchParts: [variantA, variantB],
      hotspots: [{ id: 991, hotspot_key: 'test-only-position-0', diagram_id: 991, page_number: 1, position: '0', x: 0.5, y: 0.5, width: 0.03, height: 0.03, is_verified: true, provenance: 'AUTO_MATCHED', confidence: null, variants: [variantA, variantB] }],
    })
    const user = userEvent.setup()
    render(<CatalogHarness defaultMachineId={FALCH_MACHINE_ID} />)

    await user.click(await screen.findByRole('button', { name: /Поз. 0:/ }))
    expect(screen.getByText('Избрани части: 0')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: /TEST-VARIANT-B/ }))

    expect(screen.getByText('Избрани части: 0')).toBeInTheDocument()
    expect(screen.queryByLabelText('Заявено количество TEST-VARIANT-B')).not.toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Добави към заявка' }))
    expect(screen.getByText('Избрани части: 1')).toBeInTheDocument()
    expect(screen.getByLabelText('Заявено количество TEST-VARIANT-B')).toHaveValue(1)
    expect(screen.queryByLabelText('Заявено количество TEST-VARIANT-A')).not.toBeInTheDocument()
  })

  it('keeps the official table usable when a diagram has no interactive positions', async () => {
    setupFetch({ falchDiagrams: [diagram()], hotspots: [] })
    const user = userEvent.setup()
    render(<CatalogHarness defaultMachineId={FALCH_MACHINE_ID} />)

    expect(await screen.findByText('Номерата в оригиналната схема са интерактивни. Областите се показват само при посочване, фокус или избор.')).toBeInTheDocument()
    await user.click(screen.getByText(catalogDisplayName(falchPart)))
    expect(await screen.findByRole('button', { name: 'Добави към заявка' })).toBeInTheDocument()
  })

  it('opens the desktop part-details modal with one hotspot click and restores focus after Escape', async () => {
    const testDiagram = diagram()
    setupFetch({
      falchDiagrams: [testDiagram],
      hotspots: [{ id: 991, hotspot_key: 'test-only-position-3', diagram_id: 991, page_number: 1, position: '3', x: 0.5, y: 0.5, width: 0.03, height: 0.03, is_verified: true, provenance: 'AUTO_MATCHED', confidence: null, variants: [falchPart] }],
    })
    render(<CatalogHarness defaultMachineId={FALCH_MACHINE_ID} />)

    const hotspot = await screen.findByRole('button', { name: /Поз. 3:/ })
    pointerTap(hotspot, 'mouse')

    expect(await screen.findByRole('dialog', { name: /Поз. 3 · TEST-FALCH-3/ })).toBeInTheDocument()
    const close = screen.getByRole('button', { name: 'Затвори' })
    const add = screen.getByRole('button', { name: 'Добави към заявка' })
    expect(close).toHaveFocus()
    fireEvent.keyDown(document, { key: 'Tab', shiftKey: true })
    expect(add).toHaveFocus()
    fireEvent.keyDown(document, { key: 'Tab' })
    expect(close).toHaveFocus()
    fireEvent.keyDown(document, { key: 'Escape' })
    await waitFor(() => expect(screen.queryByRole('dialog', { name: /Поз. 3/ })).not.toBeInTheDocument())
    expect(hotspot).toHaveFocus()
  })

  it('shows English / Bulgarian and keeps the manufacturer description separate', async () => {
    const translatedPart = part({
      description: 'hose',
      source_description: 'schlauch',
      original_name: 'schlauch',
      description_en: 'Hose',
      description_bg: 'Шланг',
    })
    setupFetch({ falchParts: [translatedPart] })
    const user = userEvent.setup()
    render(<CatalogHarness defaultMachineId={FALCH_MACHINE_ID} />)

    await user.click(await screen.findByText('Hose / Шланг'))
    const dialog = await screen.findByRole('dialog', { name: /Поз. 3/ })

    expect(dialog).toHaveTextContent('Наименование')
    expect(dialog).toHaveTextContent('Hose / Шланг')
    expect(dialog).toHaveTextContent('Оригинално описание от производителя')
    expect(dialog).toHaveTextContent('schlauch')
  })

  it('uses stateful first-touch select and second-touch open behavior', async () => {
    const testDiagram = diagram()
    setupFetch({
      falchDiagrams: [testDiagram],
      hotspots: [{ id: 991, hotspot_key: 'test-only-position-3', diagram_id: 991, page_number: 1, position: '3', x: 0.5, y: 0.5, width: 0.03, height: 0.03, is_verified: true, provenance: 'AUTO_MATCHED', confidence: null, variants: [falchPart] }],
    })
    render(<CatalogHarness defaultMachineId={FALCH_MACHINE_ID} />)

    const hotspot = await screen.findByRole('button', { name: /Поз. 3:/ })
    pointerTap(hotspot, 'touch')
    expect(hotspot).toHaveClass('selected')
    expect(screen.queryByRole('dialog', { name: /Поз. 3/ })).not.toBeInTheDocument()

    pointerTap(hotspot, 'touch', 2)
    expect(await screen.findByRole('dialog', { name: /Поз. 3 · TEST-FALCH-3/ })).toBeInTheDocument()
    expect(screen.getByText('Избрани части: 0')).toBeInTheDocument()
  })

  it('changes the touch selection without opening when a different position is tapped', async () => {
    const otherPart = part({ id: 904, source_record_key: 'test-only-position-4', position: '4', part_number: 'TEST-FALCH-4', order_part_number: 'TEST-FALCH-4', description: 'Falch test-only valve' })
    setupFetch({
      falchDiagrams: [diagram()],
      falchParts: [falchPart, otherPart],
      hotspots: [
        { id: 991, hotspot_key: 'test-only-position-3', diagram_id: 991, page_number: 1, position: '3', x: 0.5, y: 0.5, width: 0.03, height: 0.03, is_verified: true, provenance: 'AUTO_MATCHED', confidence: null, variants: [falchPart] },
        { id: 992, hotspot_key: 'test-only-position-4', diagram_id: 991, page_number: 1, position: '4', x: 0.6, y: 0.5, width: 0.03, height: 0.03, is_verified: true, provenance: 'AUTO_MATCHED', confidence: null, variants: [otherPart] },
      ],
    })
    render(<CatalogHarness defaultMachineId={FALCH_MACHINE_ID} />)

    const position3 = await screen.findByRole('button', { name: /Поз. 3:/ })
    const position4 = screen.getByRole('button', { name: /Поз. 4:/ })
    pointerTap(position3, 'touch')
    pointerTap(position4, 'touch', 2)

    expect(position3).not.toHaveClass('selected')
    expect(position4).toHaveClass('selected')
    expect(screen.queryByRole('dialog', { name: /Поз. 4/ })).not.toBeInTheDocument()
    pointerTap(position4, 'touch', 3)
    expect(await screen.findByRole('dialog', { name: /Поз. 4 · TEST-FALCH-4/ })).toBeInTheDocument()
  })

  it('does not open details after touch drag or pan movement', async () => {
    setupFetch({
      falchDiagrams: [diagram()],
      hotspots: [{ id: 991, hotspot_key: 'test-only-position-3', diagram_id: 991, page_number: 1, position: '3', x: 0.5, y: 0.5, width: 0.03, height: 0.03, is_verified: true, provenance: 'AUTO_MATCHED', confidence: null, variants: [falchPart] }],
    })
    render(<CatalogHarness defaultMachineId={FALCH_MACHINE_ID} />)

    const hotspot = await screen.findByRole('button', { name: /Поз. 3:/ })
    const viewport = document.querySelector<HTMLElement>('.catalog-v2-diagram-viewport') as HTMLElement
    fireEvent.pointerDown(hotspot, { pointerId: 1, pointerType: 'touch', clientX: 100, clientY: 100 })
    fireEvent.pointerMove(viewport, { pointerId: 1, pointerType: 'touch', clientX: 120, clientY: 100 })
    fireEvent.pointerUp(viewport, { pointerId: 1, pointerType: 'touch', clientX: 120, clientY: 100 })

    expect(screen.queryByRole('dialog', { name: /Поз. 3/ })).not.toBeInTheDocument()
    expect(hotspot).not.toHaveClass('selected')
  })

  it('does not open details after a pinch gesture', async () => {
    setupFetch({
      falchDiagrams: [diagram()],
      hotspots: [{ id: 991, hotspot_key: 'test-only-position-3', diagram_id: 991, page_number: 1, position: '3', x: 0.5, y: 0.5, width: 0.03, height: 0.03, is_verified: true, provenance: 'AUTO_MATCHED', confidence: null, variants: [falchPart] }],
    })
    render(<CatalogHarness defaultMachineId={FALCH_MACHINE_ID} />)

    const hotspot = await screen.findByRole('button', { name: /Поз. 3:/ })
    const viewport = document.querySelector<HTMLElement>('.catalog-v2-diagram-viewport') as HTMLElement
    fireEvent.pointerDown(hotspot, { pointerId: 1, pointerType: 'touch', clientX: 100, clientY: 100 })
    fireEvent.pointerDown(viewport, { pointerId: 2, pointerType: 'touch', clientX: 160, clientY: 100 })
    fireEvent.pointerMove(viewport, { pointerId: 2, pointerType: 'touch', clientX: 180, clientY: 100 })
    fireEvent.pointerUp(viewport, { pointerId: 2, pointerType: 'touch', clientX: 180, clientY: 100 })
    fireEvent.pointerUp(viewport, { pointerId: 1, pointerType: 'touch', clientX: 100, clientY: 100 })

    expect(screen.queryByRole('dialog', { name: /Поз. 3/ })).not.toBeInTheDocument()
  })

  it('keeps the mobile sheet close action in a dedicated header and requires explicit Add', async () => {
    setupFetch({
      falchDiagrams: [diagram()],
      hotspots: [{ id: 991, hotspot_key: 'test-only-position-3', diagram_id: 991, page_number: 1, position: '3', x: 0.5, y: 0.5, width: 0.03, height: 0.03, is_verified: true, provenance: 'AUTO_MATCHED', confidence: null, variants: [falchPart] }],
    })
    const user = userEvent.setup()
    render(<CatalogHarness defaultMachineId={FALCH_MACHINE_ID} />)

    const hotspot = await screen.findByRole('button', { name: /Поз. 3:/ })
    pointerTap(hotspot, 'touch')
    pointerTap(hotspot, 'touch', 2)
    const dialog = await screen.findByRole('dialog', { name: /Поз. 3/ })
    const close = screen.getByRole('button', { name: 'Затвори' })

    expect(close).toHaveClass('catalog-v2-part-dialog-close')
    expect(close.closest('.catalog-v2-part-dialog-header')).not.toBeNull()
    expect(dialog.querySelector('.catalog-v2-part-dialog-content')).not.toBeNull()
    expect(screen.getByText('Избрани части: 0')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Добави към заявка' }))
    expect(screen.getByText('Избрани части: 1')).toBeInTheDocument()
  })

  it('shows repair-kit positions without adding them to the request', async () => {
    const testDiagram = diagram()
    const hotspot: PositionHotspot = { id: 991, hotspot_key: 'test-only-position-3', diagram_id: 991, page_number: 1, position: '3', x: 0.5, y: 0.5, width: 0.03, height: 0.03, is_verified: true, provenance: 'AUTO_MATCHED', confidence: null, variants: [falchPart] }
    const kit: CatalogRepairKit = {
      id: 81, code: 'TEST-KIT', name: 'Test-only kit', family: 'FALCH_500', source_id: FALCH_SOURCE_ID,
      brand: 'Falch', model: 'Test fixture', assembly: 'TEST_ASSEMBLY', source_document: 'TEST_ONLY.pdf',
      source_page: 1, source_document_sha256: 'a'.repeat(64), source_version: 'PARTS_CATALOG_V2', is_approved: true, is_active: true,
      components: [{ id: 82, part_id: falchPart.id, source_record_key: falchPart.source_record_key, position: '3', part_number: falchPart.part_number, description: falchPart.description, source_description: falchPart.source_description, description_en: falchPart.description_en, description_bg: falchPart.description_bg, quantity: 1, quantity_raw: '1', source_document: 'TEST_ONLY.pdf', source_page: 1, translation_version: falchPart.translation_version, translation_qa_status: falchPart.translation_qa_status }],
    }
    setupFetch({ falchDiagrams: [testDiagram], hotspots: [hotspot], repairKits: [kit] })
    const user = userEvent.setup()
    render(<CatalogHarness defaultMachineId={FALCH_MACHINE_ID} />)

    await user.click(await screen.findByRole('button', { name: /TEST-KIT/ }))
    await user.click(screen.getByRole('button', { name: 'Покажи позициите от комплекта' }))
    expect(screen.getByRole('button', { name: /Поз. 3:/ })).toHaveClass('kit-position')
    expect(screen.getByText('Избрани части: 0')).toBeInTheDocument()
  })

  it('allows only an administrator UI session to save an audited QA correction', async () => {
    setSessionUser({ role: 'administrator', permissions: ['parts.view', 'parts.manage'] } as UserSession)
    const testDiagram = diagram()
    const hotspot: PositionHotspot = { id: 991, hotspot_key: 'test-only-position-3', diagram_id: 991, page_number: 1, position: '3', x: 0.5, y: 0.5, width: 0.03, height: 0.03, is_verified: true, provenance: 'AUTO_MATCHED', confidence: null, variants: [falchPart] }
    const fetchMock = setupFetch({ falchDiagrams: [testDiagram], hotspots: [hotspot] })
    const user = userEvent.setup()
    render(<CatalogHarness defaultMachineId={FALCH_MACHINE_ID} />)

    await user.click(await screen.findByRole('button', { name: 'QA на областите' }))
    await user.click(await screen.findByRole('button', { name: /Поз. 3:/ }))
    expect(screen.getByText('Автоматично съпоставена')).toBeInTheDocument()
    await user.type(screen.getByLabelText('Основание за корекцията'), 'Проверена тестова корекция')
    await user.click(screen.getByRole('button', { name: 'Запази' }))

    expect(fetchMock.mock.calls.some(([input, init]) => String(input).endsWith('/api/catalog/v2/hotspots/991') && init?.method === 'PATCH')).toBe(true)
    expect(await screen.findByText('Ръчно потвърдена')).toBeInTheDocument()
  })
})
