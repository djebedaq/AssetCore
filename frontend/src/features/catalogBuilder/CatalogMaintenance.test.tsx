import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, expect, it, vi } from 'vitest'
import { I18nProvider } from '../../i18n'
import CatalogMaintenance from './CatalogMaintenance'

const category = { id: 1, code: 'QA', name_bg: 'QA категория', name_en: 'QA category', name_ru: 'QA категория', is_active: true, capabilities: ['HAS_PARTS_CATALOG'] }
const catalog = { id: 10, code: 'QA_STABLE_CODE', asset_category_id: 1, asset_category: category,
  name_bg: 'QA каталог', name_en: 'QA catalog', name_ru: 'QA каталог', description: null, manufacturer: null,
  model_reference: null, is_active: true, published_revision: null, draft_revision_count: 1 }
const versions = [{ id: 11, revision_code: 'A', status: 'DRAFT', change_note: 'QA draft', created_at: '2026-10-01' },
  { id: 12, revision_code: 'B', status: 'PUBLISHED', change_note: 'QA publication', created_at: '2026-10-02' }]
const json = (data: unknown) => new Response(JSON.stringify(data), { headers: { 'Content-Type': 'application/json' } })
afterEach(() => { cleanup(); vi.unstubAllGlobals(); vi.restoreAllMocks() })

function setup() {
  const writes: Array<{ path: string; method: string; body?: Record<string, unknown> }> = []
  vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const path = String(input)
    if (init?.method && init.method !== 'GET') {
      writes.push({ path, method: init.method, body: init.body ? JSON.parse(String(init.body)) : undefined }); return json({})
    }
    if (path === '/api/categories') return json([category])
    if (path.endsWith('/catalogs')) return json([catalog])
    if (path.endsWith('/revisions')) return json(versions)
    if (path.endsWith('/assets')) return json([{ id: 1, inventory_number: 'QA-ONLY', name: 'Synthetic QA asset' }])
    return json([])
  }))
  render(<I18nProvider><CatalogMaintenance catalogId={10} onChanged={vi.fn(async () => {})} onDirtyChange={vi.fn()} /></I18nProvider>)
  return writes
}

it('edits language-specific metadata without sending a replacement catalog code', async () => {
  const writes = setup(), user = userEvent.setup()
  await user.click(await screen.findByRole('button', { name: 'Коригирай основните данни' }))
  await user.clear(screen.getByLabelText('Име на английски'))
  await user.type(screen.getByLabelText('Име на английски'), 'QA English correction')
  await user.click(screen.getByRole('button', { name: 'Запази' }))
  await waitFor(() => expect(writes).toHaveLength(1))
  expect(writes[0]).toMatchObject({ path: '/api/admin/catalog-builder/catalogs/10', method: 'PATCH', body: { name_bg: catalog.name_bg, name_en: 'QA English correction', name_ru: catalog.name_ru, asset_category_id: 1 } })
  expect(writes[0].body).not.toHaveProperty('code')
})

it('retains explicit revision cloning and confirms machine unbinding without adding another publication flow', async () => {
  const writes = setup(), user = userEvent.setup()
  vi.spyOn(window, 'confirm').mockReturnValue(false)
  await user.click(await screen.findByText('История на версиите', { selector: 'summary' }))
  await user.click(screen.getByRole('button', { name: 'Създай следваща ревизия' }))
  await user.type(screen.getByLabelText('Код на ревизията'), 'C')
  await user.type(screen.getByLabelText('Бележка за промяната'), 'QA audited clone')
  await user.click(screen.getByRole('button', { name: 'Запази' }))
  await waitFor(() => expect(writes).toContainEqual({ path: '/api/admin/catalog-builder/revisions/12/clone', method: 'POST', body: { revision_code: 'C', change_note: 'QA audited clone' } }))
  await user.click(screen.getByText('Активи', { selector: 'summary' }))
  await user.click(screen.getByRole('button', { name: 'Премахни връзката' }))
  expect(writes.filter(row => row.method === 'DELETE')).toHaveLength(0)
  vi.mocked(window.confirm).mockReturnValue(true)
  await user.click(screen.getByRole('button', { name: 'Премахни връзката' }))
  await waitFor(() => expect(writes.filter(row => row.method === 'DELETE')).toEqual([{ path: '/api/admin/catalog-builder/catalogs/10/assets/1', method: 'DELETE', body: undefined }]))
  expect(screen.queryByRole('button', { name: /Публикувай/ })).not.toBeInTheDocument()
})
