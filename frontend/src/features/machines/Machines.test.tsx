import { render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { I18nProvider } from '../../i18n'
import { setSessionUser } from '../../permissions'
import type { UserSession } from '../../types'
import Machines from './Machines'

const user: UserSession = {
  id: 701,
  email: 'f01-qa@example.invalid',
  full_name: 'F01 QA User',
  role: 'administrator',
  preferred_language: 'bg',
  is_active: true,
  is_system_owner: false,
  must_change_password: false,
  permissions: ['assets.view', 'documents.view'],
  created_at: '2026-08-29T00:00:00Z',
  updated_at: '2026-08-29T00:00:00Z',
}

function json(value: unknown): Response {
  return new Response(JSON.stringify(value), {
    status: 200,
    headers: { 'Content-Type': 'application/json' },
  })
}

describe('machine-list category loading', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
    vi.restoreAllMocks()
  })

  it('keeps the machine list available when categories contain custom fields', async () => {
    setSessionUser(user)
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const path = String(input)
      if (path.endsWith('/api/machines')) {
        return json([{
          id: 7,
          inventory_number: '7',
          name: 'Falch 1000 bar №7',
          category: 'HPWJ',
          brand: 'Falch',
          pressure_bar: 1000,
          serial_number: 'G41200143',
          status: 'READY',
          location_id: null,
          location: null,
          created_at: '2026-08-29T00:00:00Z',
          updated_at: '2026-08-29T00:00:00Z',
        }])
      }
      if (path.endsWith('/api/categories')) {
        return json([{
          id: 1,
          code: 'HPWJ',
          name_bg: 'Водоструйни машини',
          name_en: 'High-pressure water jet machines',
          name_ru: 'Водоструйные машины',
          description: null,
          icon: null,
          validation_rules: null,
          document_types: null,
          checklists: null,
          status_codes: null,
          is_active: true,
          created_at: '2026-08-29T00:00:00Z',
          fields: [{
            id: 91,
            category_id: 1,
            code: 'PRESSURE_CLASS',
            label_bg: 'Клас налягане',
            label_en: 'Pressure class',
            label_ru: 'Класс давления',
            field_type: 'SELECT',
            is_required: true,
            options: ['500', '1000'],
            unit: 'bar',
            validation_rules: { allowed: ['500', '1000'] },
            sort_order: 10,
            is_active: true,
          }],
        }])
      }
      if (path.endsWith('/api/locations') || path.endsWith('/api/departments')) return json([])
      throw new Error(`Unexpected F01 request: ${path}`)
    })
    vi.stubGlobal('fetch', fetchMock)

    render(
      <I18nProvider initialLocale="bg">
        <Machines onOpenCatalog={vi.fn()} />
      </I18nProvider>,
    )

    expect(await screen.findByText('Falch 1000 bar №7')).toBeVisible()
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
    expect(screen.queryByText('Няма машини, отговарящи на търсенето.')).not.toBeInTheDocument()
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(4))
    expect(fetchMock.mock.calls.map(([input]) => String(input))).toContain('/api/categories')
  })
})
