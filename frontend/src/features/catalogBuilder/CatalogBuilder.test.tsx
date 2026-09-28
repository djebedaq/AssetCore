import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, expect, it, vi } from 'vitest'
import { I18nProvider } from '../../i18n'
import { setSessionUser } from '../../permissions'
import type { UserSession } from '../../types'
import CatalogBuilder from './CatalogBuilder'

const user = {
  id: 100, email: 'qa-builder@example.invalid', full_name: 'QA Builder', role: 'administrator',
  preferred_language: 'bg', is_active: true, is_system_owner: false, must_change_password: false,
  permissions: ['parts.manage', 'parts.view'], created_at: '', updated_at: '',
} as UserSession

const category = { id: 1, code: 'QA_CAPABLE', name_bg: 'Тестова категория', name_en: 'Test category',
  name_ru: 'Тестовая категория', is_active: true, capabilities: ['HAS_PARTS_CATALOG'] }
const unsupported = { ...category, id: 2, code: 'QA_OTHER', capabilities: [] }
const json = (value: unknown, status = 200) => new Response(JSON.stringify(value), {
  status, headers: { 'Content-Type': 'application/json' },
})

afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks() })

it('creates a catalog only from dynamic capable categories and opens its draft workspace', async () => {
  setSessionUser(user)
  const created = { id: 10, code: 'QA_CATALOG', asset_category_id: 1, asset_category: category,
    name_bg: 'Каталог', name_en: 'Catalog', name_ru: 'Каталог', description: null,
    manufacturer: null, model_reference: null, is_active: true, bound_asset_count: 0,
    draft_revision_count: 0, latest_revision: null, published_revision: null }
  let catalogs: typeof created[] = []
  const requests: Array<{ path: string; method: string; body?: unknown }> = []
  vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const path = String(input)
    const method = init?.method || 'GET'
    requests.push({ path, method, body: init?.body ? JSON.parse(String(init.body)) : undefined })
    if (path === '/api/categories') return json([category, unsupported])
    if (path === '/api/admin/catalog-builder/catalogs' && method === 'GET') return json(catalogs)
    if (path === '/api/admin/catalog-builder/catalogs' && method === 'POST') { catalogs = [created]; return json(created, 201) }
    if (path === '/api/admin/catalog-builder/catalogs/10/assets') return json([])
    if (path === '/api/admin/catalog-builder/catalogs/10/revisions') return json([])
    if (path.includes('/eligible-assets')) return json([])
    throw Error(path)
  }))
  render(<I18nProvider initialLocale="bg"><CatalogBuilder /></I18nProvider>)
  await userEvent.click(await screen.findByRole('button', { name: 'Нов каталог' }))
  const dialog = screen.getByRole('dialog')
  const categorySelect = within(dialog).getByLabelText('Категория активи')
  expect(within(categorySelect).getByRole('option', { name: /Тестова категория/ })).toBeInTheDocument()
  expect(within(categorySelect).queryByRole('option', { name: /QA_OTHER/ })).not.toBeInTheDocument()
  await userEvent.type(within(dialog).getByLabelText('Код'), 'qa_catalog')
  await userEvent.selectOptions(categorySelect, '1')
  await userEvent.type(within(dialog).getByLabelText('Име на български'), 'Каталог')
  await userEvent.type(within(dialog).getByLabelText('Име на английски'), 'Catalog')
  await userEvent.type(within(dialog).getByLabelText('Име на руски'), 'Каталог')
  await userEvent.click(within(dialog).getByRole('button', { name: 'Запази' }))
  await waitFor(() => expect(requests.some(item => item.method === 'POST' &&
    item.path.endsWith('/catalogs') && (item.body as { asset_category_id: number }).asset_category_id === 1)).toBe(true))
  await userEvent.click(await screen.findByRole('button', { name: 'Отвори работното пространство' }))
  expect(await screen.findByText(/Източници, части, визуално съпоставяне/)).toBeVisible()
  expect(screen.queryByRole('button', { name: 'Публикувай' })).not.toBeInTheDocument()
})

it('opens a draft revision workspace with assemblies and no publish action', async () => {
  setSessionUser(user)
  const catalog = { id: 10, code: 'QA_CATALOG', asset_category_id: 1, asset_category: category,
    name_bg: 'Каталог', name_en: 'Catalog', name_ru: 'Каталог', description: null,
    manufacturer: null, model_reference: null, is_active: true, bound_asset_count: 0,
    draft_revision_count: 1, latest_revision: { id: 11, revision_code: 'A' }, published_revision: null }
  const requests: string[] = []
  vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
    const path = String(input)
    requests.push(path)
    if (path === '/api/categories') return json([category])
    if (path === '/api/admin/catalog-builder/catalogs') return json([catalog])
    if (path === '/api/admin/catalog-builder/catalogs/10/assets') return json([])
    if (path === '/api/admin/catalog-builder/catalogs/10/revisions') return json([
      { id: 11, revision_code: 'A', status: 'DRAFT', change_note: null, created_at: '2026-09-28T00:00:00' },
    ])
    if (path === '/api/admin/catalog-builder/revisions/11/assemblies') return json([])
    throw Error(path)
  }))
  render(<I18nProvider initialLocale="bg"><CatalogBuilder /></I18nProvider>)
  await userEvent.click(await screen.findByRole('button', { name: 'Отвори работното пространство' }))
  await userEvent.click(screen.getByRole('button', { name: 'Ревизии' }))
  await userEvent.click(await screen.findByRole('button', { name: 'Отвори ревизия' }))
  await userEvent.click(screen.getByRole('button', { name: 'Възли и източници' }))
  expect(await screen.findByRole('button', { name: 'Добави възел' })).toBeVisible()
  expect(requests).toContain('/api/admin/catalog-builder/revisions/11/assemblies')
  expect(screen.queryByRole('button', { name: /Публикувай/ })).not.toBeInTheDocument()
})
