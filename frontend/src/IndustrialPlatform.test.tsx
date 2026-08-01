import { render, screen } from '@testing-library/react'
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
    localStorage.setItem('assetcore_user', JSON.stringify({ role: 'mechanic' }))
  })

  afterEach(() => vi.unstubAllGlobals())

  it('пренася избраната машина от паспорта към заявката за част', async () => {
    const machineId = 22
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
      const path = String(input)
      if (path.endsWith('/api/catalog/parts')) {
        return jsonResponse([{
          id: 1,
          brand: 'test-only brand',
          part_number: 'TEST-PART',
          description: 'test-only verified part',
          is_verified: true,
        }])
      }
      if (path.endsWith('/api/repair-kits')) return jsonResponse([])
      if (path.endsWith('/api/machines')) {
        return jsonResponse([{
          id: machineId,
          inventory_number: 'TEST-ASSET',
          name: 'test-only asset',
          category: 'TEST',
          brand: 'test-only brand',
          pressure_bar: 0,
          status: 'READY',
          created_at: '2026-07-31T00:00:00',
          updated_at: '2026-07-31T00:00:00',
        }])
      }
      throw new Error(`Unexpected request: ${path}`)
    }))

    render(
      <I18nProvider initialLocale="bg">
        <IndustrialCatalog defaultMachineId={machineId} />
      </I18nProvider>,
    )
    await userEvent.click(await screen.findByRole('button', { name: 'Добави към заявка' }))
    expect(await screen.findByLabelText('Машина')).toHaveValue(String(machineId))
  })
})
