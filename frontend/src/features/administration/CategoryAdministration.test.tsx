import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, expect, it, vi } from 'vitest'
import { I18nProvider } from '../../i18n'
import { setSessionUser } from '../../permissions'
import type { UserSession } from '../../types'
import { CategoryAdministration } from './CategoryAdministration'
import MachineModal from '../machines/MachineModal'
import Machines from '../machines/Machines'

const admin: UserSession = {
  id: 900, email: 'qa@example.invalid', full_name: 'QA Admin', role: 'administrator',
  preferred_language: 'bg', is_active: true, is_system_owner: false, must_change_password: false,
  permissions: ['settings.manage', 'assets.create', 'assets.edit'], created_at: '', updated_at: '',
}
const capabilities = [
  { code: 'HAS_PRESSURE', name_bg: 'Работно налягане', name_en: 'Working pressure', name_ru: 'Рабочее давление', description_bg: 'Налягане', description_en: 'Pressure', description_ru: 'Давление' },
  { code: 'HAS_REPAIR_WORKFLOW', name_bg: 'Ремонти', name_en: 'Repairs', name_ru: 'Ремонт', description_bg: 'Ремонт', description_en: 'Repair', description_ru: 'Ремонт' },
]
const category = { id: 5, code: 'QA_ADMIN', name_bg: 'Тестова категория', name_en: 'Test category', name_ru: 'Тестовая категория', capabilities: ['HAS_PRESSURE', 'HAS_REPAIR_WORKFLOW'], is_active: true, asset_count: 1, created_at: '', fields: [
  { id: 21, category_id: 5, code: 'QA_LATER', label_bg: 'Второ поле', field_type: 'TEXT', is_required: false, sort_order: 2, is_active: false },
  { id: 22, category_id: 5, code: 'QA_FIRST', label_bg: 'Първо поле', field_type: 'TEXT', is_required: true, sort_order: 1, is_active: true },
] }
const json = (value: unknown, status = 200) => new Response(JSON.stringify(value), { status, headers: { 'Content-Type': 'application/json' } })
const mount = (node: React.ReactNode) => render(<I18nProvider initialLocale="bg">{node}</I18nProvider>)
afterEach(() => { window.history.replaceState({}, '', '/'); vi.unstubAllGlobals(); vi.restoreAllMocks() })

it.each([
  ['en', 'Test category', 'Edit', 'Working pressure'],
  ['ru', 'Тестовая категория', 'Редактирование', 'Рабочее давление'],
] as const)('uses localized category and capability labels in %s', async (locale, name, edit, pressure) => {
  setSessionUser({ ...admin, preferred_language: locale })
  vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => String(input) === '/api/categories' ? json([category]) : json(capabilities)))
  render(<I18nProvider initialLocale={locale}><CategoryAdministration /></I18nProvider>)
  const card = (await screen.findByText(name)).closest('article')!
  expect(within(card).getByText(pressure)).toBeVisible()
  await userEvent.click(within(card).getAllByRole('button', { name: edit })[0])
  const dialog = await screen.findByRole('dialog')
  expect(within(dialog).getByRole('checkbox', { name: new RegExp(pressure) })).toBeChecked()
})

it('deactivates and reactivates a category while keeping its asset count and fields', async () => {
  setSessionUser(admin)
  vi.spyOn(window, 'confirm').mockReturnValue(true)
  let current = structuredClone(category)
  const mutations: unknown[] = []
  vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const path = String(input)
    if (path === '/api/categories') return json([current])
    if (path === '/api/admin/asset-capabilities') return json(capabilities)
    if (path === '/api/categories/5' && init?.method === 'PATCH') {
      const change = JSON.parse(String(init.body))
      mutations.push(change)
      current = { ...current, ...change }
      return json(current)
    }
    throw Error(path)
  }))
  mount(<CategoryAdministration />)
  const card = (await screen.findByText('Тестова категория')).closest('article')!
  await userEvent.click(within(card).getAllByRole('button', { name: 'Деактивирай' })[0])
  const activate = (await within(card).findAllByRole('button', { name: 'Активирай' }))[0]
  expect(within(card).getByText(/Активи: 1/)).toBeVisible()
  expect(within(card).getByText('Първо поле')).toBeVisible()
  await userEvent.click(activate)
  await waitFor(() => expect(mutations).toEqual([{ is_active: false }, { is_active: true }]))
})

it('shows an incompatible field error and keeps the definition editor open', async () => {
  setSessionUser(admin)
  vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const path = String(input)
    if (path === '/api/categories') return json([category])
    if (path === '/api/admin/asset-capabilities') return json(capabilities)
    if (path === '/api/categories/5/fields/22' && init?.method === 'PATCH') return json({ detail: { code: 'category_field_values_incompatible' } }, 409)
    throw Error(path)
  }))
  mount(<CategoryAdministration />)
  const card = (await screen.findByText('Тестова категория')).closest('article')!
  await userEvent.click(within(card.querySelector('.category-field-row') as HTMLElement).getByRole('button', { name: 'Редактиране' }))
  const dialog = await screen.findByRole('dialog', { name: 'Редактиране на поле' })
  await userEvent.type(within(dialog).getByLabelText('Шаблон за проверка'), '^NEW$')
  await userEvent.click(within(dialog).getByRole('button', { name: 'Запази' }))
  expect(await within(dialog).findByRole('alert')).toHaveTextContent(/Съществуващи стойности/)
  expect(dialog).toBeVisible()
  expect(within(dialog).getByLabelText('Шаблон за проверка')).toHaveValue('^NEW$')
})

it('cancels inline creation and returns to the unchanged machine draft', async () => {
  setSessionUser(admin)
  vi.stubGlobal('fetch', vi.fn(async () => json(capabilities)))
  mount(<MachineModal locations={[]} departments={[]} categories={[]} onClose={vi.fn()} onSaved={vi.fn()} />)
  const machineDialog = screen.getByRole('dialog', { name: 'Нова машина' })
  await userEvent.type(within(machineDialog).getByLabelText('Инвентарен номер'), 'QA-CANCEL-DRAFT')
  await userEvent.click(within(machineDialog).getByRole('button', { name: 'Добави категория' }))
  const inline = await screen.findByRole('dialog', { name: 'Добави категория' })
  await userEvent.type(within(inline).getByLabelText('Системен код'), 'QA_UNSAVED')
  await userEvent.click(within(inline).getByRole('button', { name: 'Отказ' }))
  expect(screen.queryByRole('dialog', { name: 'Добави категория' })).not.toBeInTheDocument()
  expect(within(machineDialog).getByLabelText('Инвентарен номер')).toHaveValue('QA-CANCEL-DRAFT')
})

it('shows category counts, localized capabilities and sorted fields, then patches only changed capabilities', async () => {
  setSessionUser(admin)
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const path = String(input)
    if (path === '/api/categories' && !init?.method) return json([category])
    if (path === '/api/admin/asset-capabilities') return json(capabilities)
    if (path === '/api/categories/5' && init?.method === 'PATCH') return json({ ...category, capabilities: ['HAS_PRESSURE'] })
    throw Error(path)
  })
  vi.stubGlobal('fetch', fetchMock)
  mount(<CategoryAdministration />)
  const card = (await screen.findByText('Тестова категория')).closest('article')!
  expect(within(card).getByText('QA_ADMIN')).toBeVisible()
  expect(within(card).getByText(/Активи: 1/)).toBeVisible()
  expect(within(card).getByText('Работно налягане')).toBeVisible()
  expect(within(card).getByText('Неактивен запис')).toBeVisible()
  const rows = card.querySelectorAll('.category-field-row')
  expect(rows[0]).toHaveTextContent('Първо поле')
  expect(rows[1]).toHaveTextContent('Второ поле')
  await userEvent.click(within(card).getAllByRole('button', { name: 'Редактиране' })[0])
  const dialog = await screen.findByRole('dialog', { name: 'Редактиране на категория' })
  expect(within(dialog).getByLabelText('Системен код')).toHaveAttribute('readonly')
  await userEvent.click(within(dialog).getByRole('checkbox', { name: /Ремонти/ }))
  await userEvent.click(within(dialog).getByRole('button', { name: 'Запази' }))
  await waitFor(() => expect(fetchMock.mock.calls.some(([path, init]) => String(path) === '/api/categories/5' && init?.method === 'PATCH')).toBe(true))
  const mutation = fetchMock.mock.calls.find(([path, init]) => String(path) === '/api/categories/5' && init?.method === 'PATCH')
  expect(JSON.parse(mutation?.[1]?.body as string)).toEqual({ capabilities: ['HAS_PRESSURE'] })
})

it('keeps the machine draft while an admin creates and selects a basic category inline', async () => {
  setSessionUser(admin)
  const onCreated = vi.fn()
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const path = String(input)
    if (path === '/api/admin/asset-capabilities') return json(capabilities)
    if (path === '/api/categories' && init?.method === 'POST') return json({ id: 9, code: 'QA_NEW', name_bg: 'Нова категория', is_active: true, capabilities: [], fields: [] }, 201)
    if (path === '/api/asset-categories/9/form-definition') return json({ id: 9, capabilities: [], fields: [] })
    throw Error(path)
  })
  vi.stubGlobal('fetch', fetchMock)
  mount(<MachineModal locations={[]} departments={[]} categories={[]} onClose={vi.fn()} onSaved={vi.fn()} onCategoryCreated={onCreated} />)
  const machineDialog = screen.getByRole('dialog', { name: 'Нова машина' })
  await userEvent.type(within(machineDialog).getByLabelText('Инвентарен номер'), 'QA-DRAFT')
  await userEvent.click(within(machineDialog).getByRole('button', { name: 'Добави категория' }))
  const categoryDialog = await screen.findByRole('dialog', { name: 'Добави категория' })
  expect(within(categoryDialog).queryByText('Разширени настройки')).not.toBeInTheDocument()
  await userEvent.type(within(categoryDialog).getByLabelText('Системен код'), 'QA_NEW')
  await userEvent.type(within(categoryDialog).getByLabelText('Български'), 'Нова категория')
  await userEvent.click(within(categoryDialog).getByRole('button', { name: 'Запази' }))
  await waitFor(() => expect(within(machineDialog).getByLabelText('Категория')).toHaveValue('9'))
  expect(within(machineDialog).getByLabelText('Инвентарен номер')).toHaveValue('QA-DRAFT')
  expect(within(machineDialog).queryByLabelText('Налягане (bar)')).not.toBeInTheDocument()
  expect(onCreated).toHaveBeenCalledWith(expect.objectContaining({ code: 'QA_NEW' }))
  expect(fetchMock.mock.calls.some(([path]) => String(path) === '/api/asset-categories/9/form-definition')).toBe(true)
})

it('does not offer inline category creation without settings permission', () => {
  setSessionUser({ ...admin, permissions: ['assets.create'] })
  mount(<MachineModal locations={[]} departments={[]} categories={[]} onClose={vi.fn()} onSaved={vi.fn()} />)
  expect(screen.queryByRole('button', { name: 'Добави категория' })).not.toBeInTheDocument()
})

it('edits a stable field code and toggles field activation', async () => {
  setSessionUser(admin)
  let current = structuredClone(category)
  const mutations: Array<Record<string, unknown>> = []
  vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const path = String(input)
    if (path === '/api/categories') return json([current])
    if (path === '/api/admin/asset-capabilities') return json(capabilities)
    if (path === '/api/categories/5/fields/22' && init?.method === 'PATCH') {
      const body = JSON.parse(String(init.body)) as Record<string, unknown>
      mutations.push(body)
      current = { ...current, fields: current.fields.map(field => field.id === 22 ? { ...field, ...body } : field) }
      return json(current.fields.find(field => field.id === 22))
    }
    throw Error(path)
  }))
  mount(<CategoryAdministration />)
  const card = (await screen.findByText('Тестова категория')).closest('article')!
  const firstRow = card.querySelector('.category-field-row')!
  await userEvent.click(within(firstRow as HTMLElement).getByRole('button', { name: 'Редактиране' }))
  const dialog = await screen.findByRole('dialog', { name: 'Редактиране на поле' })
  expect(within(dialog).getByLabelText('Системен код')).toHaveAttribute('readonly')
  const label = within(dialog).getByLabelText('Български')
  await userEvent.clear(label)
  await userEvent.type(label, 'Нов етикет')
  await userEvent.click(within(dialog).getByRole('button', { name: 'Запази' }))
  await waitFor(() => expect(mutations).toEqual([{ label_bg: 'Нов етикет' }]))
  await userEvent.click(within(card.querySelector('.category-field-row') as HTMLElement).getByRole('button', { name: 'Деактивирай' }))
  await waitFor(() => expect(mutations[1]).toEqual({ is_active: false }))
  expect(await screen.findByText('Нов етикет')).toBeVisible()
})

it('keeps an inline machine draft after duplicate category error and then enables pressure', async () => {
  setSessionUser(admin)
  let attempts = 0
  vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const path = String(input)
    if (path === '/api/admin/asset-capabilities') return json(capabilities)
    if (path === '/api/categories' && init?.method === 'POST') {
      attempts++
      return attempts === 1
        ? json({ detail: { code: 'category_code_duplicate' } }, 409)
        : json({ id: 10, code: 'QA_PRESSURE_NEW', name_bg: 'Нова категория', is_active: true, capabilities: ['HAS_PRESSURE'], fields: [] }, 201)
    }
    if (path === '/api/asset-categories/10/form-definition') return json({ id: 10, capabilities: ['HAS_PRESSURE'], fields: [] })
    throw Error(path)
  }))
  mount(<MachineModal locations={[]} departments={[]} categories={[]} onClose={vi.fn()} onSaved={vi.fn()} />)
  const machineDialog = screen.getByRole('dialog', { name: 'Нова машина' })
  await userEvent.type(within(machineDialog).getByLabelText('Инвентарен номер'), 'QA-KEEP-DRAFT')
  await userEvent.click(within(machineDialog).getByRole('button', { name: 'Добави категория' }))
  const dialog = await screen.findByRole('dialog', { name: 'Добави категория' })
  const code = within(dialog).getByLabelText('Системен код')
  await userEvent.type(code, 'QA_DUPLICATE')
  await userEvent.type(within(dialog).getByLabelText('Български'), 'Нова категория')
  await userEvent.click(within(dialog).getByRole('checkbox', { name: /Работно налягане/ }))
  await userEvent.click(within(dialog).getByRole('button', { name: 'Запази' }))
  expect(await within(dialog).findByRole('alert')).toHaveTextContent('вече съществува')
  expect(within(machineDialog).getByLabelText('Инвентарен номер')).toHaveValue('QA-KEEP-DRAFT')
  await userEvent.clear(code)
  await userEvent.type(code, 'QA_PRESSURE_NEW')
  await userEvent.click(within(dialog).getByRole('button', { name: 'Запази' }))
  expect(await within(machineDialog).findByLabelText('Налягане (bar)')).toBeVisible()
  expect(within(machineDialog).getByLabelText('Категория')).toHaveValue('10')
})

it('refreshes registry navigation after inline creation without closing Add Machine', async () => {
  setSessionUser(admin)
  window.history.replaceState({}, '', '/machines')
  let created = false
  const navigation = [{ id: 30, code: 'QA_NAV_NEW', name_bg: 'Нова категория', is_active: true, asset_count: 0, has_pressure: false }]
  vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const path = String(input)
    if (path === '/api/machines/category-navigation') return json(created ? navigation : [])
    if (path === '/api/admin/asset-capabilities') return json(capabilities)
    if (path === '/api/categories' && init?.method === 'POST') {
      created = true
      return json({ ...navigation[0], capabilities: [], fields: [] }, 201)
    }
    if (path === '/api/asset-categories/30/form-definition') return json({ id: 30, capabilities: [], fields: [] })
    if (path === '/api/machines?category_id=30') return json([])
    throw Error(path)
  }))
  mount(<Machines onOpenCatalog={vi.fn()} />)
  await userEvent.click(await screen.findByRole('button', { name: 'Нова машина' }))
  const machineDialog = screen.getByRole('dialog', { name: 'Нова машина' })
  await userEvent.click(within(machineDialog).getByRole('button', { name: 'Добави категория' }))
  const dialog = await screen.findByRole('dialog', { name: 'Добави категория' })
  await userEvent.type(within(dialog).getByLabelText('Системен код'), 'QA_NAV_NEW')
  await userEvent.type(within(dialog).getByLabelText('Български'), 'Нова категория')
  await userEvent.click(within(dialog).getByRole('button', { name: 'Запази' }))
  expect(await screen.findByRole('button', { name: /Нова категория.*0/ })).toBeVisible()
  expect(within(machineDialog).getByLabelText('Категория')).toHaveValue('30')
  expect(window.location.search).toBe('?category=QA_NAV_NEW')
})
