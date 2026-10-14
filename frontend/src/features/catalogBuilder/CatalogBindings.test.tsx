import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, expect, it, vi } from 'vitest'
import { I18nProvider } from '../../i18n'
import { setSessionUser } from '../../permissions'
import type { UserSession } from '../../types'
import CatalogBindings from './CatalogBindings'
import { ux06Bg, ux06En, ux06Ru } from './ux06Translations'

const category = { id: 1, code: 'QA', name_bg: 'QA category', name_en: 'QA category', name_ru: 'QA category', is_active: true, capabilities: ['HAS_PARTS_CATALOG'] }
const catalog = { id: 10, code: 'QA', name_bg: 'QA published', name_en: 'QA published', name_ru: 'QA published', asset_category_id: 1,
  asset_category: category, manufacturer: 'QA', model_reference: 'QA', is_active: true, published_revision: { id: 11, revision_code: 'REV-1' }, draft_revision_count: 1, active_asset_count: 0 }
const draft = { ...catalog, id: 20, name_bg: 'QA draft', published_revision: null }
const machine = (id: number, extra = {}) => ({ id, inventory_number: `QA-${id}`, name: `Synthetic QA ${id}`, brand: 'QA', model: 'QA', serial_number: `QA-S-${id}`, is_active: true, bound: false, compatibility: 'EXACT', ...extra })
const binding = (id: number, machineId = 1) => ({ id, catalog_id: id === 1 ? 10 : 30, machine_id: machineId, category_id: 1, machine: machine(machineId), catalog: id === 1 ? catalog : { ...catalog, id: 30, code: 'QA_SECOND', name_bg: 'QA second' },
  status: 'ACTIVE', published_revision: catalog.published_revision, expected_digest: String(id).repeat(64).slice(0, 64) })
const json = (data: unknown, status = 200) => new Response(JSON.stringify(data), { status, headers: { 'Content-Type': 'application/json' } })
afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks() })

function setup({ ambiguous = false, incompatible = false, failure = false } = {}) {
  setSessionUser({ id: 1, role: 'administrator', permissions: ['parts.manage'] } as UserSession)
  const writes: Array<{ path: string; body: Record<string, unknown> }> = []
  const onChanged = vi.fn(async () => {}), onClose = vi.fn()
  vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const path = String(input), body = init?.body ? JSON.parse(String(init.body)) : {}
    if (init?.method === 'POST') {
      if (path.endsWith('/preview')) {
        const machines = body.machine_ids.map((id: number) => machine(id, { compatibility: incompatible && id === 2 ? 'INCOMPATIBLE' : ambiguous ? 'AMBIGUOUS' : 'EXACT',
          code: incompatible && id === 2 ? 'catalog_asset_model_mismatch' : ambiguous && !body.confirmed_machine_ids.includes(id) ? 'catalog_asset_compatibility_confirmation_required' : null }))
        return json({ machines, ready: machines.every((row: { code: string | null }) => !row.code), digest: 'a'.repeat(64), published_revision: catalog.published_revision })
      }
      writes.push({ path, body })
      return failure ? json({ detail: { code: 'catalog_bindings_stale' } }, 409) : json({ count: body.bindings?.length || body.machine_ids?.length || 2, machines: [machine(1), machine(2)] })
    }
    if (path.includes('/bindings/machines?')) return json({ items: path.includes('offset=50') ? [machine(51)] : [machine(1), machine(2), machine(3, { bound: true })], total: 51, offset: path.includes('offset=50') ? 50 : 0, limit: 50 })
    if (path.includes('/bindings?')) return json({ items: [binding(1), binding(2)], total: 2, offset: 0, limit: 50 })
    if (path.includes('/workspace/machines?')) return json({ items: [], total: 0, has_next: false })
    return json([])
  }))
  render(<I18nProvider><CatalogBindings catalogs={[catalog, draft]} categories={[category]} catalogId={10} onChanged={onChanged} onClose={onClose} /></I18nProvider>)
  return { writes, onChanged, onClose, user: userEvent.setup() }
}

it('keeps BG/EN/RU keys and disables unpublished catalogs even beside a published catalog with a new draft', async () => {
  expect(Object.keys(ux06En).sort()).toEqual(Object.keys(ux06Bg).sort())
  expect(Object.keys(ux06Ru).sort()).toEqual(Object.keys(ux06Bg).sort())
  setup()
  expect(screen.getByRole('combobox', { name: 'Категория активи' })).toHaveValue('1')
  expect(screen.getByRole('combobox', { name: 'Каталог' })).toHaveValue('10')
  expect(await screen.findByRole('option', { name: /QA draft/ })).toBeDisabled()
  expect(screen.getByRole('option', { name: /QA published/ })).toBeEnabled()
  const existing = await screen.findByText('Вече свързан')
  expect(within(existing.closest('article')!).getByRole('checkbox')).toBeDisabled()
})

it('preserves exact selections across pages, and select all is explicitly limited to the current page', async () => {
  const { user, onClose } = setup()
  await user.click(await screen.findByLabelText('Избери всички допустими на тази страница (2)'))
  await user.click(screen.getByRole('button', { name: 'Следваща страница' }))
  await user.click(await screen.findByLabelText('Избери всички допустими на тази страница (1)'))
  expect(screen.getByText(/Избрани машини: 3/)).toBeInTheDocument()
  await user.click(screen.getByRole('button', { name: 'Премахни QA-1 от избора' }))
  expect(screen.getByText(/Избрани машини: 2/)).toBeInTheDocument()
  fireEvent.keyDown(document, { key: 'Escape' })
  expect(screen.getByText(ux06Bg['ux06.discard'])).toBeInTheDocument()
  expect(onClose).not.toHaveBeenCalled()
  await user.click(screen.getByRole('button', { name: 'Отказ' }))
  expect(screen.getByText(/Избрани машини: 2/)).toBeInTheDocument()
})

it('requires each ambiguous confirmation and sends a single atomic request with all IDs and preview digest', async () => {
  const { user, writes, onChanged } = setup({ ambiguous: true })
  await user.click(await screen.findByLabelText('Избери всички допустими на тази страница (2)'))
  await user.click(await screen.findByRole('button', { name: 'Преглед преди свързване' }))
  const save = screen.getByRole('button', { name: 'Потвърди свързването' })
  expect(save).toBeDisabled()
  await user.click(await screen.findByLabelText('Потвърждавам съвместимостта за QA-1'))
  expect(save).toBeDisabled()
  await user.click(await screen.findByLabelText('Потвърждавам съвместимостта за QA-2'))
  await waitFor(() => expect(save).toBeEnabled())
  await user.click(save)
  await waitFor(() => expect(onChanged).toHaveBeenCalledOnce())
  expect(writes).toEqual([{ path: '/api/admin/catalog-builder/bindings/batch', body: { catalog_id: 10, machine_ids: [1, 2], confirmed_machine_ids: [1, 2], expected_digest: 'a'.repeat(64) } }])
  expect(screen.getByText(/Успешно записани връзки: 2/)).toBeInTheDocument()
})

it('shows incompatible machines and blocks the whole selection', async () => {
  const { user, writes } = setup({ incompatible: true })
  await user.click(await screen.findByLabelText('Избери всички допустими на тази страница (2)'))
  await user.click(await screen.findByRole('button', { name: 'Преглед преди свързване' }))
  expect(screen.getByRole('button', { name: 'Потвърди свързването' })).toBeDisabled()
  expect(screen.getByText(/Избрани машини: 2/)).toHaveTextContent('Несъвместим производител или модел: 1')
  expect(writes).toHaveLength(0)
})

it('removes concrete bindings on the same machine with one confirmation and retains stale failures', async () => {
  const { user, writes, onChanged } = setup({ failure: true })
  await user.click(screen.getByRole('button', { name: 'Активни връзки' }))
  await user.selectOptions(screen.getByRole('combobox', { name: 'Каталог' }), '')
  await user.click(await screen.findByLabelText('Избери всички допустими на тази страница (2)'))
  await user.click(screen.getByRole('button', { name: 'Премахни избраните' }))
  expect(screen.getByText('Избрани връзки: 2')).toBeInTheDocument()
  await user.click(screen.getByRole('button', { name: 'Потвърди премахването' }))
  expect(writes).toEqual([{ path: '/api/admin/catalog-builder/bindings/batch-deactivate', body: { bindings: [1, 2].map(id => ({ binding_id: id, catalog_id: id === 1 ? 10 : 30, machine_id: 1, expected_digest: String(id).repeat(64) })) } }])
  expect(await screen.findByRole('alert')).toHaveTextContent('Данните са променени')
  expect(onChanged).not.toHaveBeenCalled()
  expect(screen.queryByText(/Успешно премахнати/)).not.toBeInTheDocument()
})

it('keeps a bulk selection when a single removal is cancelled and clears only the successfully removed pair', async () => {
  const { user, writes } = setup()
  await user.click(screen.getByRole('button', { name: 'Активни връзки' }))
  await user.selectOptions(screen.getByRole('combobox', { name: 'Каталог' }), '')
  await user.click(await screen.findByLabelText('Избери всички допустими на тази страница (2)'))
  await user.click(screen.getAllByRole('button', { name: 'Премахни връзката' })[0])
  expect(screen.getByText('Избрани връзки: 1')).toBeInTheDocument()
  await user.click(screen.getByRole('button', { name: 'Отказ' }))
  expect(screen.getByText(/Избрани връзки: 2/)).toBeInTheDocument()
  await user.click(screen.getAllByRole('button', { name: 'Премахни връзката' })[0])
  await user.click(screen.getByRole('button', { name: 'Потвърди премахването' }))
  await waitFor(() => expect(screen.getByText(/Избрани връзки: 1/)).toBeInTheDocument())
  expect(writes).toEqual([{ path: '/api/admin/catalog-builder/bindings/batch-deactivate', body: { bindings: [{ binding_id: 1, catalog_id: 10, machine_id: 1, expected_digest: '1'.repeat(64) }] } }])
})
