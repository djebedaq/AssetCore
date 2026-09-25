import { render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import userEvent from '@testing-library/user-event'
import { I18nProvider } from '../../i18n'
import { setSessionUser } from '../../permissions'
import type { AssetCategory, RegistryCategory, UserSession } from '../../types'
import Machines from './Machines'
import MachineModal from './MachineModal'

const user: UserSession = {
  id: 701, email: 'qa@example.invalid', full_name: 'QA User', role: 'administrator',
  preferred_language: 'bg', is_active: true, is_system_owner: false, must_change_password: false,
  permissions: ['assets.view', 'assets.create', 'assets.edit', 'documents.view'],
  created_at: '', updated_at: '',
}

const navigation: RegistryCategory[] = [
  { id: 1, code: 'HPWJ', name_bg: 'Водоструйни машини', name_en: 'Water jets', name_ru: 'Водоструйные машины', is_active: true, asset_count: 1, has_pressure: true },
  { id: 2, code: 'QA_PAINT', name_bg: 'Бояджийски машини', name_en: 'Paint machines', name_ru: 'Окрасочные машины', is_active: true, asset_count: 1, has_pressure: false },
  { id: 3, code: 'QA_ROBOT', name_bg: 'Роботи', is_active: true, asset_count: 0, has_pressure: false },
  { id: 4, code: 'QA_OLD', name_bg: 'Стара категория', is_active: false, asset_count: 1, has_pressure: false },
]
const machines = [
  { id: 1, inventory_number: 'QA-1', name: 'QA water jet', brand: 'QA', category: 'HPWJ', category_id: 1, pressure_bar: 500, status: 'READY', location: null, created_at: '', updated_at: '' },
  { id: 2, inventory_number: 'QA-2', name: 'QA paint machine', brand: 'QA', category: 'QA_PAINT', category_id: 2, pressure_bar: null, status: 'READY', location: null, created_at: '', updated_at: '' },
  { id: 4, inventory_number: 'QA-4', name: 'QA inactive asset', brand: 'QA', category: 'QA_OLD', category_id: 4, pressure_bar: null, status: 'READY', location: null, created_at: '', updated_at: '' },
]
const json = (value: unknown) => new Response(JSON.stringify(value), { status: 200, headers: { 'Content-Type': 'application/json' } })

function mockRegistry(categories = navigation) {
  const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
    const path = String(input)
    if (path.endsWith('/api/machines/category-navigation')) return json(categories)
    if (path.endsWith('/api/locations') || path.endsWith('/api/departments')) return json([])
    if (path === '/api/machines') return json(machines)
    const match = /^\/api\/machines\?category_id=(\d+)$/.exec(path)
    if (match) return json(machines.filter((machine) => machine.category_id === Number(match[1])))
    throw new Error(`Unexpected registry request: ${path}`)
  })
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

const mount = () => render(<I18nProvider initialLocale="bg"><Machines onOpenCatalog={vi.fn()} /></I18nProvider>)

beforeEach(() => { window.history.replaceState({}, '', '/machines'); setSessionUser(user) })
afterEach(() => { window.history.replaceState({}, '', '/'); vi.unstubAllGlobals(); vi.restoreAllMocks() })

describe('category-driven machine registry', () => {
  it('chooses a category before loading assets, filters on the server, and keeps search scoped', async () => {
    const fetchMock = mockRegistry()
    const actor = userEvent.setup()
    mount()
    expect(await screen.findByRole('button', { name: /Бояджийски машини.*1/ })).toBeVisible()
    expect(screen.queryByText('QA water jet')).not.toBeInTheDocument()
    expect(fetchMock.mock.calls.some(([url]) => String(url) === '/api/machines')).toBe(false)
    await actor.click(screen.getByRole('button', { name: /Бояджийски машини.*1/ }))
    expect(await screen.findByText('QA paint machine')).toBeVisible()
    expect(screen.queryByText('QA water jet')).not.toBeInTheDocument()
    expect(screen.queryByRole('columnheader', { name: 'Налягане' })).not.toBeInTheDocument()
    expect(fetchMock.mock.calls.some(([url]) => String(url) === '/api/machines?category_id=2')).toBe(true)
    expect(window.location.pathname + window.location.search).toBe('/machines?category=QA_PAINT')
    await actor.type(screen.getByRole('textbox'), 'water')
    expect(screen.queryByText('QA water jet')).not.toBeInTheDocument()
    expect(screen.queryByText('QA paint machine')).not.toBeInTheDocument()
    await actor.clear(screen.getByRole('textbox'))
    await actor.click(screen.getByRole('button', { name: 'Нова машина' }))
    expect(screen.getByRole('dialog')).toBeVisible()
    expect(within(screen.getByRole('dialog')).getByLabelText('Категория')).toHaveValue('2')
  })

  it('shows pressure for a capable category, and category identity in explicit All', async () => {
    const fetchMock = mockRegistry()
    const actor = userEvent.setup()
    mount()
    await actor.click(await screen.findByRole('button', { name: /Водоструйни машини.*1/ }))
    expect(await screen.findByText('QA water jet')).toBeVisible()
    expect(screen.getByRole('columnheader', { name: 'Налягане' })).toBeVisible()
    await actor.click(screen.getByRole('button', { name: 'Всички' }))
    expect(await screen.findByText('QA paint machine')).toBeVisible()
    expect(screen.getByRole('columnheader', { name: 'Категория' })).toBeVisible()
    expect(screen.queryByRole('columnheader', { name: 'Налягане' })).not.toBeInTheDocument()
    expect(fetchMock.mock.calls.some(([url]) => String(url) === '/api/machines')).toBe(true)
    await actor.click(screen.getByRole('button', { name: 'Нова машина' }))
    expect(within(screen.getByRole('dialog')).getByLabelText('Категория')).toHaveValue('')
  })

  it('restores a valid URL and follows Back/Forward selection changes', async () => {
    window.history.replaceState({}, '', '/machines?category=QA_PAINT')
    mockRegistry()
    const actor = userEvent.setup()
    mount()
    expect(await screen.findByText('QA paint machine')).toBeVisible()
    await actor.click(screen.getByRole('button', { name: /Водоструйни машини.*1/ }))
    expect(await screen.findByText('QA water jet')).toBeVisible()
    window.history.replaceState({}, '', '/machines?category=QA_PAINT')
    window.dispatchEvent(new PopStateEvent('popstate'))
    expect(await screen.findByText('QA paint machine')).toBeVisible()
  })

  it('handles invalid URLs, empty active and populated inactive categories', async () => {
    window.history.replaceState({}, '', '/machines?category=REMOVED')
    mockRegistry()
    const actor = userEvent.setup()
    mount()
    expect((await screen.findAllByText('Изберете категория')).length).toBeGreaterThan(0)
    expect(window.location.search).toBe('')
    await actor.click(screen.getByRole('button', { name: /Роботи.*0/ }))
    expect(await screen.findByText('В тази категория няма активи.')).toBeVisible()
    await actor.click(screen.getByRole('button', { name: /Стара категория.*1/ }))
    expect(await screen.findByText('QA inactive asset')).toBeVisible()
    expect(screen.getByRole('button', { name: /Стара категория.*1/ })).toHaveAttribute('aria-pressed', 'true')
    await actor.click(screen.getByRole('button', { name: 'Нова машина' }))
    expect(within(screen.getByRole('dialog')).getByLabelText('Категория')).toHaveValue('')
  })

  it('auto-selects the sole browseable category', async () => {
    const fetchMock = mockRegistry([navigation[0]])
    mount()
    expect(await screen.findByText('QA water jet')).toBeVisible()
    expect(fetchMock.mock.calls.some(([url]) => String(url) === '/api/machines?category_id=1')).toBe(true)
  })

  it('keeps the compact selector usable with more than thirty dynamic categories', async () => {
    const many = Array.from({ length: 32 }, (_, index): RegistryCategory => ({
      id: index + 1, code: `QA_CAT_${index}`, name_bg: `Тестова категория ${index}`,
      is_active: true, asset_count: 0, has_pressure: false,
    }))
    const fetchMock = mockRegistry(many)
    const actor = userEvent.setup()
    mount()
    const selector = await screen.findByRole('combobox', { name: 'Категории активи' })
    expect(within(selector).getAllByRole('option')).toHaveLength(34)
    await actor.selectOptions(selector, 'QA_CAT_31')
    expect(await screen.findByText('В тази категория няма активи.')).toBeVisible()
    expect(window.location.search).toBe('?category=QA_CAT_31')
    expect(fetchMock.mock.calls.some(([url]) => String(url) === '/api/machines?category_id=32')).toBe(true)
  })

  it('lets an asset-only observer navigate without loading administrative metadata', async () => {
    setSessionUser({ ...user, role: 'observer', permissions: ['assets.view'] })
    const fetchMock = mockRegistry()
    const actor = userEvent.setup()
    mount()
    await actor.click(await screen.findByRole('button', { name: /Бояджийски машини.*1/ }))
    expect(await screen.findByText('QA paint machine')).toBeVisible()
    expect(fetchMock.mock.calls.map(([url]) => String(url))).not.toContain('/api/categories')
    expect(fetchMock.mock.calls.map(([url]) => String(url))).not.toContain('/api/locations')
  })
})

describe('asset form capabilities', () => {
  const categories: AssetCategory[] = [
    { id: 2, code: 'QA_GENERIC_ASSET', name_bg: 'Тестов актив', is_active: true, created_at: '', fields: [], capabilities: [] },
    { id: 1, code: 'HPWJ', name_bg: 'Водоструйна машина', is_active: true, created_at: '', fields: [], capabilities: ['HAS_PRESSURE'] },
  ]

  it('starts unselected and submits a generic asset with null pressure', async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL, _init?: RequestInit) =>
      String(input).includes('/form-definition')
        ? json({ id: 2, capabilities: [], fields: [] }) : json({ id: 99 }))
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
    await waitFor(() => expect(fetchMock.mock.calls.some(([, init]) => init?.method === 'POST')).toBe(true))
    const body = JSON.parse(String(fetchMock.mock.calls.find(([, init]) => init?.method === 'POST')?.[1]?.body))
    expect(body.category_id).toBe(2)
    expect(body.pressure_bar).toBeNull()
    expect(body.custom_fields).toEqual([])
    expect(body).not.toHaveProperty('category')
  })

  it('shows existing pressure only for a category with HAS_PRESSURE', () => {
    render(<I18nProvider initialLocale="bg"><MachineModal machine={{ id: 7, inventory_number: '7', name: 'QA HPWJ', category: 'HPWJ', category_id: 1, brand: 'QA', pressure_bar: 1000, status: 'READY', created_at: '', updated_at: '' }} locations={[]} departments={[]} categories={categories} onClose={vi.fn()} onSaved={vi.fn()} /></I18nProvider>)
    expect(screen.getByLabelText('Налягане (bar)')).toHaveValue(1000)
  })

  it('renders and submits configured technical fields in the same create request', async () => {
    const fields = [
      { id: 11, category_id: 2, code: 'QA_TEXT', label_bg: 'Текст', label_en: 'Text', label_ru: 'Текст', field_type: 'TEXT', is_required: true, sort_order: 1, is_active: true, validation_rules: { min_length: 2, max_length: 8 } },
      { id: 12, category_id: 2, code: 'QA_INTEGER', label_bg: 'Брой', field_type: 'INTEGER', is_required: false, sort_order: 2, is_active: true, unit: 'бр.', validation_rules: { min: 1, max: 10 } },
      { id: 13, category_id: 2, code: 'QA_DECIMAL', label_bg: 'Размер', field_type: 'DECIMAL', is_required: false, sort_order: 3, is_active: true },
      { id: 14, category_id: 2, code: 'QA_BOOLEAN', label_bg: 'Флаг', field_type: 'BOOLEAN', is_required: false, sort_order: 4, is_active: true },
      { id: 15, category_id: 2, code: 'QA_DATE', label_bg: 'Дата', field_type: 'DATE', is_required: false, sort_order: 5, is_active: true },
      { id: 16, category_id: 2, code: 'QA_SELECT', label_bg: 'Избор', field_type: 'SELECT', is_required: false, sort_order: 6, is_active: true, options: ['A', 'B'] },
    ]
    const fetchMock = vi.fn(async (input: RequestInfo | URL, _init?: RequestInit) => String(input).includes('/form-definition')
      ? json({ id: 2, capabilities: [], fields }) : json({ id: 100 }))
    vi.stubGlobal('fetch', fetchMock)
    render(<I18nProvider initialLocale="bg"><MachineModal initialCategoryId={2} locations={[]} departments={[]} categories={categories} onClose={vi.fn()} onSaved={vi.fn()} /></I18nProvider>)
    const actor = userEvent.setup()
    await actor.type(await screen.findByRole('textbox', { name: 'Текст' }), 'AB')
    await actor.type(screen.getByLabelText('Брой (бр.)'), '5')
    await actor.type(screen.getByLabelText('Размер'), '1.5')
    await actor.selectOptions(screen.getByLabelText('Флаг'), 'true')
    await actor.type(screen.getByLabelText('Дата'), '2026-09-24')
    await actor.selectOptions(screen.getByLabelText('Избор'), 'B')
    await actor.type(screen.getByLabelText('Инвентарен номер'), 'QA-DYNAMIC-UI')
    await actor.type(screen.getByLabelText('Наименование'), 'Тестов актив')
    await actor.type(screen.getByLabelText('Марка'), 'QA')
    await actor.click(screen.getByRole('button', { name: 'Запази' }))
    await waitFor(() => expect(fetchMock.mock.calls.some(([, init]) => init?.method === 'POST')).toBe(true))
    const body = JSON.parse(String(fetchMock.mock.calls.find(([, init]) => init?.method === 'POST')?.[1]?.body))
    expect(body.custom_fields).toEqual([
      { field_id: 11, value: 'AB' }, { field_id: 12, value: '5' },
      { field_id: 13, value: '1.5' }, { field_id: 14, value: 'true' },
      { field_id: 15, value: '2026-09-24' }, { field_id: 16, value: 'B' },
    ])
  })

  it('loads target-category values and submits category transition with its fields together', async () => {
    const field = { id: 21, category_id: 2, code: 'QA_TARGET', label_bg: 'Параметър',
      field_type: 'TEXT', is_required: true, sort_order: 1, is_active: true }
    const fetchMock = vi.fn(async (input: RequestInfo | URL, _init?: RequestInit) => {
      const path = String(input)
      if (path.includes('form-data?category_id=1')) return json({ category: { id: 1, capabilities: ['HAS_PRESSURE'], fields: [] }, values: [] })
      if (path.includes('form-data?category_id=2')) return json({ category: { id: 2, capabilities: [], fields: [field] }, values: [{ field_id: 21, value: 'Earlier' }] })
      return json({ id: 7 })
    })
    vi.stubGlobal('fetch', fetchMock)
    render(<I18nProvider initialLocale="bg"><MachineModal machine={{ id: 7, inventory_number: '7', name: 'QA HPWJ', category: 'HPWJ', category_id: 1, brand: 'QA', pressure_bar: 1000, status: 'READY', created_at: '', updated_at: '' }} locations={[]} departments={[]} categories={categories} onClose={vi.fn()} onSaved={vi.fn()} /></I18nProvider>)
    const actor = userEvent.setup()
    await actor.selectOptions(screen.getByLabelText('Категория'), '2')
    const target = await screen.findByRole('textbox', { name: 'Параметър' })
    expect(target).toHaveValue('Earlier')
    await actor.clear(target)
    await actor.type(target, 'Updated')
    await actor.click(screen.getByRole('button', { name: 'Запази' }))
    await waitFor(() => expect(fetchMock.mock.calls.some(([, init]) => init?.method === 'PATCH')).toBe(true))
    const body = JSON.parse(String(fetchMock.mock.calls.find(([, init]) => init?.method === 'PATCH')?.[1]?.body))
    expect(body.category_id).toBe(2)
    expect(body.pressure_bar).toBeNull()
    expect(body.custom_fields).toEqual([{ field_id: 21, value: 'Updated' }])
  })
})
