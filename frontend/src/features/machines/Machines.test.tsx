import { render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import userEvent from '@testing-library/user-event'
import { I18nProvider } from '../../i18n'
import { setSessionUser } from '../../permissions'
import type { UserSession } from '../../types'
import Machines from './Machines'
import MachineModal from './MachineModal'
import type { AssetCategory } from '../../types'

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
        }, {
          id: 8, inventory_number: 'QA-8', name: 'Тестов общ актив',
          category: 'QA_GENERIC_ASSET', category_id: 2, brand: 'QA', pressure_bar: null,
          status: 'READY', location: null, created_at: '', updated_at: '',
        }])
      }
      if (path.endsWith('/api/categories')) {
        return json([{
          id: 1,
          code: 'HPWJ',
          capabilities: ['HAS_PRESSURE'],
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
        }, {
          id: 2, code: 'QA_GENERIC_ASSET', name_bg: 'Тестов актив',
          is_active: true, created_at: '', fields: [], capabilities: [],
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
    expect(screen.getByText('Тестов общ актив')).toBeVisible()
    expect(screen.queryByText('null bar')).not.toBeInTheDocument()
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
    expect(screen.queryByText('Няма машини, отговарящи на търсенето.')).not.toBeInTheDocument()
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(4))
    expect(fetchMock.mock.calls.map(([input]) => String(input))).toContain('/api/categories')
  })
})

describe('asset form capabilities', () => {
  const categories: AssetCategory[] = [
    { id: 2, code: 'QA_GENERIC_ASSET', name_bg: 'Тестов актив', is_active: true, created_at: '', fields: [], capabilities: [] },
    { id: 1, code: 'HPWJ', name_bg: 'Водоструйна машина', is_active: true, created_at: '', fields: [], capabilities: ['HAS_PRESSURE'] },
  ]

  afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks() })

  it('starts without an HPWJ category or pressure and submits a generic asset with null pressure', async () => {
    setSessionUser({ ...user, permissions: ['assets.create', 'assets.edit', 'documents.view'] })
    const fetchMock = vi.fn(async (_input: RequestInfo | URL, _init?: RequestInit) => json({ id: 99 }))
    vi.stubGlobal('fetch', fetchMock)
    render(<I18nProvider initialLocale="bg"><MachineModal locations={[]} departments={[]} categories={categories} onClose={vi.fn()} onSaved={vi.fn()} /></I18nProvider>)
    const actor = userEvent.setup()
    const category = screen.getByLabelText('Категория') as HTMLSelectElement
    expect(category.value).toBe('')
    expect(screen.queryByLabelText('Налягане (bar)')).not.toBeInTheDocument()
    await actor.selectOptions(category, '2')
    await actor.type(screen.getByLabelText('Инвентарен номер'), 'QA-UI-1')
    await actor.type(screen.getByLabelText('Наименование'), 'Тестов актив')
    await actor.type(screen.getByLabelText('Марка'), 'Тестов производител')
    await actor.click(screen.getByRole('button', { name: 'Запази' }))
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1))
    const body = JSON.parse(String(fetchMock.mock.calls[0][1]?.body))
    expect(body.category_id).toBe(2)
    expect(body.pressure_bar).toBeNull()
    expect(body).not.toHaveProperty('category')
  })

  it('shows existing pressure only for a category with HAS_PRESSURE', () => {
    setSessionUser({ ...user, permissions: ['assets.edit', 'documents.view'] })
    render(<I18nProvider initialLocale="bg"><MachineModal machine={{ id: 7, inventory_number: '7', name: 'QA HPWJ', category: 'HPWJ', category_id: 1, brand: 'QA', pressure_bar: 1000, status: 'READY', created_at: '', updated_at: '' }} locations={[]} departments={[]} categories={categories} onClose={vi.fn()} onSaved={vi.fn()} /></I18nProvider>)
    expect(screen.getByLabelText('Налягане (bar)')).toHaveValue(1000)
  })
})
