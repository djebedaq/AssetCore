import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { I18nProvider } from './i18n'
import { IndustrialCatalog } from './IndustrialPlatform'

function jsonResponse(value: unknown): Response {
  return new Response(JSON.stringify(value), {
    status: 200,
    headers: { 'Content-Type': 'application/json' },
  })
}

describe('индустриален каталог', () => {
  beforeEach(() => {
    localStorage.clear()
    localStorage.setItem('assetcore_user', JSON.stringify({
      role: 'mechanic',
      permissions: ['assets.view', 'transfers.view', 'transfers.create', 'transfers.return', 'repairs.view', 'repairs.create', 'repairs.edit', 'repairs.complete', 'requests.view', 'requests.create', 'parts.view', 'documents.view', 'documents.generate'],
    }))
  })

  afterEach(() => {
    cleanup()
    vi.unstubAllGlobals()
  })

  it('добавя точната проверена позиция с заявено количество 1 и отделно количество по схема', async () => {
    const machineId = 22
    const part = {
      id: 34,
      source_record_key: 'hydwin-plunger-34',
      source_id: 'HYDWIN_FUSSEN_500_PLUNGER_PUMP',
      source_row_index: 34,
      family: 'HYDWIN_FUSSEN_500',
      brand: 'HYDWIN/Fussen',
      model: 'FCE15/50',
      assembly: 'PLUNGER_PUMP',
      position: '34',
      part_number: '7.906-007.11',
      order_part_number: '7.906-007.11',
      description: 'Main water seal',
      original_name: 'Main water seal',
      description_2: '15*24*9.3',
      quantity: 3,
      quantity_raw: '3',
      valid_for_raw: null,
      repair_kit_code: null,
      source_document: 'ONLY_PLUNGER_PUMP.pdf',
      source_page: 22,
      source_figure: 'Exploded view of plunger pump',
      source_version: 'PARTS_CATALOG_V2',
      source_document_sha256: '5b5d89b5ebcd71dc8f203d7a6ef419e9f131eaf7f95a1cbe3221992d5c6b7056',
      verification_status: 'VERIFIED',
      source_anomaly_codes: [],
      is_verified: true,
    }
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
      const path = String(input)
      if (path.endsWith('/api/machines')) {
        return jsonResponse([{
          id: machineId,
          inventory_number: '22',
          name: 'FCE15/50',
          category: 'HPWJ',
          brand: 'HYDWIN/Fussen',
          model: 'FCE15/50',
          pressure_bar: 500,
          status: 'READY',
          created_at: '2026-07-31T00:00:00',
          updated_at: '2026-07-31T00:00:00',
        }])
      }
      if (path.endsWith(`/api/catalog/v2/machines/${machineId}`)) return jsonResponse({
        dataset_version: 'PARTS_CATALOG_V2', supported: true, message: '', machine_id: machineId,
        machine_number: '22', brand: 'HYDWIN/Fussen', model: 'FCE15/50', family: 'HYDWIN_FUSSEN_500',
        assemblies: [{ source_id: part.source_id, family: part.family, assembly: part.assembly, title: 'Plunger Pump', document_reference: null, part_count: 58, diagram_count: 1, verified_hotspot_count: 2, diagrams: [] }],
      })
      if (path.includes(`/api/catalog/v2/assemblies/${part.source_id}?machine_id=${machineId}`)) return jsonResponse({
        dataset_version: 'PARTS_CATALOG_V2', machine_id: machineId, machine_number: '22', family: part.family,
        source_id: part.source_id, assembly: part.assembly, title: 'Plunger Pump', parts: [part],
        diagrams: [{ id: 12, source_id: part.source_id, page_number: 21, title: 'Exploded view of plunger pump', source_pdf_sha256: part.source_document_sha256, render_version: 'v1', technical_document_id: 9, preview_endpoint: '/technical-library/9/preview?page=21', download_endpoint: '/technical-library/9/download' }],
      })
      if (path.includes('/api/catalog/v2/repair-kits?')) return jsonResponse([])
      if (path.includes('/api/catalog/v2/diagrams/12/hotspots?')) return jsonResponse([{
        id: 34, hotspot_key: 'hydwin-34', diagram_id: 12, page_number: 21, position: '34',
        x: 0.5, y: 0.5, width: 0.03, height: 0.03, is_verified: true,
        provenance: 'manual_visual_verification', confidence: 1, variants: [part],
      }])
      if (path.includes('/api/technical-library/9/preview?page=21')) return new Response(new Blob(['preview'], { type: 'image/png' }))
      throw new Error(`Unexpected request: ${path}`)
    }))
    const NativeURL = URL
    class MockURL extends NativeURL {
      static createObjectURL = vi.fn(() => 'blob:diagram')
      static revokeObjectURL = vi.fn()
    }
    vi.stubGlobal('URL', MockURL)

    render(
      <I18nProvider initialLocale="bg">
        <IndustrialCatalog defaultMachineId={machineId} />
      </I18nProvider>,
    )
    await userEvent.click(await screen.findByRole('button', { name: 'Поз. 34' }))

    expect((await screen.findAllByText('Main water seal')).length).toBeGreaterThan(0)
    expect(screen.getAllByText('Количество по схема').length).toBeGreaterThan(0)
    expect(screen.getAllByText('3').length).toBeGreaterThan(0)
    expect(screen.getByLabelText('Заявено количество 7.906-007.11')).toHaveValue(1)
  })
})
