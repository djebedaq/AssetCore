import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, expect, it, vi } from 'vitest'
import { I18nProvider } from '../../i18n'
import { setSessionUser } from '../../permissions'
import type { UserSession } from '../../types'
import CatalogBuilder from './CatalogBuilder'
import { catalogUxBg } from './catalogUxTranslations'

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

const definition = { id: 10, code: 'QA_CATALOG', asset_category_id: 1, asset_category: category,
  name_bg: 'QA каталог', name_en: 'QA catalog', name_ru: 'QA каталог', description: null,
  manufacturer: null, model_reference: null, is_active: true, draft_revision_count: 1, published_revision: null }
const version = { id: 11, revision_code: 'A', status: 'DRAFT', created_at: '2026-10-01' }
const workflow = (ready: boolean, digest = 'a'.repeat(64)) => ({ ready, publication_digest: digest,
  current_published_revision_id: null, errors: ready ? [] : [{ code: 'catalog_publication_part_incomplete', step: 'parts' }], warnings: [],
  summary: { part_count: 1, assembly_count: 1, exploded_page_count: 1, spare_list_page_count: 1, reviewed_source_count: 0 },
  progress: { position_count: 1, completed_positions: 0 }, resume_step: 'references' })

it('preserves explicit catalog codes and all language names inside contextual creation', async () => {
  setSessionUser(user)
  let created = false
  const writes: Array<{ path: string; body: Record<string, unknown> }> = []
  vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const path = String(input)
    if (init?.method === 'POST') {
      writes.push({ path, body: init.body ? JSON.parse(String(init.body)) : {} })
      if (path.endsWith('/catalogs')) { created = true; return json(definition, 201) }
      if (path.endsWith('/edit')) return json(version)
    }
    if (path === '/api/categories') return json([category, unsupported])
    if (path.endsWith('/catalogs')) return json(created ? [definition] : [])
    if (path.endsWith('/revisions')) return json([version])
    if (path.endsWith('/workflow')) return json(workflow(false))
    return json([])
  }))
  render(<I18nProvider><CatalogBuilder /></I18nProvider>)
  const actor = userEvent.setup()
  await actor.click(await screen.findByRole('button', { name: 'Нов каталог' }))
  const dialog = screen.getByRole('dialog')
  expect(within(dialog).queryByRole('option', { name: /QA_OTHER/ })).not.toBeInTheDocument()
  await actor.type(within(dialog).getByLabelText('Име на каталога'), 'QA каталог')
  await actor.selectOptions(within(dialog).getByLabelText('Категория активи'), '1')
  await actor.click(within(dialog).getByText(catalogUxBg['catalogUx.catalogFields']))
  await actor.type(within(dialog).getByLabelText('Код'), 'qa_catalog')
  await actor.type(within(dialog).getByLabelText('Име на английски'), 'QA catalog')
  await actor.type(within(dialog).getByLabelText('Име на руски'), 'QA каталог')
  await actor.click(within(dialog).getByRole('button', { name: 'Продължи' }))
  await waitFor(() => expect(writes).toHaveLength(2))
  expect(writes[0]).toEqual({ path: '/api/admin/catalog-builder/catalogs', body: {
    code: 'QA_CATALOG', name_bg: 'QA каталог', name_en: 'QA catalog', name_ru: 'QA каталог', description: null,
    asset_category_id: 1, manufacturer: null, model_reference: null,
  } })
  expect(writes[1].path).toBe('/api/admin/catalog-builder/catalogs/10/edit')
  await waitFor(() => expect(screen.getByLabelText('Възел')).toBeVisible())
  expect(screen.queryByRole('button', { name: 'Разширен режим' })).not.toBeInTheDocument()
})

it('waits for the server workflow before enabling navigation on resume', async () => {
  setSessionUser(user)
  let resolve!: (value: Response) => void
  vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
    const path = String(input)
    if (path === '/api/categories') return json([category])
    if (path.endsWith('/catalogs')) return json([definition])
    if (path.endsWith('/revisions')) return json([version])
    if (path.endsWith('/workflow')) return new Promise<Response>(done => { resolve = done })
    return json([])
  }))
  render(<I18nProvider><CatalogBuilder /></I18nProvider>)
  await userEvent.click(await screen.findByRole('button', { name: 'Продължи черновата' }))
  const next = await screen.findByRole('button', { name: /2 Части и маркери/ })
  expect(next).toBeDisabled()
  await waitFor(() => expect(resolve).toBeTypeOf('function'))
  resolve(json(workflow(false)))
  await waitFor(() => expect(next).toBeEnabled())
  await userEvent.click(next)
  expect(next).toHaveAttribute('aria-current', 'step')
})

it('publishes only the server-reviewed digest and refreshes a stale publication response', async () => {
  setSessionUser(user)
  let ready = false, stale = true, digest = 'b'.repeat(64), published = false
  const requests: Record<string, unknown>[] = []
  vi.spyOn(window, 'confirm').mockReturnValue(true)
  vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const path = String(input)
    if (path === '/api/categories') return json([category])
    if (path.endsWith('/catalogs')) return json([definition])
    if (path.endsWith('/revisions')) return json([{ ...version, status: published ? 'PUBLISHED' : 'DRAFT' }])
    if (path.endsWith('/workflow')) return json(workflow(ready, digest))
    if (path.endsWith('/publish')) {
      requests.push(JSON.parse(String(init?.body)))
      if (stale) { stale = false; digest = 'c'.repeat(64); return json({ detail: { code: 'catalog_publication_stale' } }, 409) }
      published = true; return json({ ...version, status: 'PUBLISHED' })
    }
    return json([])
  }))
  render(<I18nProvider><CatalogBuilder /></I18nProvider>)
  const actor = userEvent.setup()
  await actor.click(await screen.findByRole('button', { name: 'Продължи черновата' }))
  const review = screen.getByRole('button', { name: /3 Публикуване/ })
  await waitFor(() => expect(review).toBeEnabled()); await actor.click(review)
  expect(await screen.findByRole('button', { name: 'Публикувай каталог' })).toBeDisabled()
  ready = true
  await actor.click(screen.getByRole('button', { name: /1 Каталог и PDF/ })); await actor.click(review)
  await waitFor(() => expect(screen.getByRole('button', { name: 'Публикувай каталог' })).toBeEnabled())
  await actor.click(screen.getByRole('button', { name: 'Публикувай каталог' }))
  await screen.findByRole('alert')
  expect(requests[0]).toEqual({ expected_publication_digest: 'b'.repeat(64), expected_current_published_revision_id: null, confirmed: true })
  await actor.click(screen.getByRole('button', { name: 'Публикувай каталог' }))
  await waitFor(() => expect(requests).toHaveLength(2))
  expect(requests[1]).toEqual({ expected_publication_digest: 'c'.repeat(64), expected_current_published_revision_id: null, confirmed: true })
})
