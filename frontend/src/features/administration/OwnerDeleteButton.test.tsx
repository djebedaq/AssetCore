import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import styles from '../../styles.css?raw'
import { I18nProvider, bg, en, ru, translate } from '../../i18n'
import { setSessionUser } from '../../permissions'
import type { UserSession } from '../../types'
import UserAdministration from './UserAdministration'
import { CategoryAdministration } from './CategoryAdministration'
import { AdministrationPanel } from './AdministrationPanel'
import { OwnerDeleteButton, type DeletionPreview } from './OwnerDeleteButton'
import Machines from '../machines/Machines'

const owner: UserSession = { id: 1, email: 'owner@qa.invalid', full_name: 'QA Owner', role: 'administrator', preferred_language: 'bg', is_active: true, is_system_owner: true, must_change_password: false, permissions: ['settings.manage', 'assets.view', 'assets.edit', 'documents.view'], created_at: '', updated_at: '' }
const data: DeletionPreview = { identity: 'QA', can_delete: true, blockers: [], owned_records_to_delete: [{ code: 'auth_sessions', count: 2, label_key: 'ownerDeletion.references.sessions' }], confirmation_text: 'DELETE QA' }
const json = (value: unknown, status = 200) => new Response(JSON.stringify(value), { status, headers: { 'Content-Type': 'application/json' } })
const mount = (node: React.ReactNode) => render(<I18nProvider initialLocale="bg">{node}</I18nProvider>)
const button = (onDeleted = vi.fn()) => <OwnerDeleteButton resource="user" resourceId={2} identity="QA" onDeleted={onDeleted} />

beforeEach(() => { setSessionUser(owner); window.history.replaceState({}, '', '/') })
afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks(); window.history.replaceState({}, '', '/') })

async function completeDialog() {
  const dialog = within(await screen.findByRole('dialog', { name: 'Окончателно изтриване' }))
  await userEvent.type(await dialog.findByLabelText('Текуща парола на собственика'), 'QA-password')
  await userEvent.type(dialog.getByLabelText(/Въведете точно следната фраза/), 'DELETE QA')
  await userEvent.click(dialog.getByRole('button', { name: 'Изтрий окончателно' }))
}

it('hides permanent deletion from ordinary administrators and on a protected owner row', () => {
  setSessionUser({ ...owner, is_system_owner: false })
  const view = mount(button())
  expect(screen.queryByRole('button')).not.toBeInTheDocument()
  setSessionUser(owner)
  view.rerender(<I18nProvider><OwnerDeleteButton resource="user" resourceId={1} identity="QA Owner" protectedOwner onDeleted={vi.fn()} /></I18nProvider>)
  expect(screen.queryByRole('button')).not.toBeInTheDocument()
})

it('loads preview, requires password and exact phrase, and refreshes after success', async () => {
  const onDeleted = vi.fn()
  const fetchMock = vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => json(init?.method === 'POST' ? { deleted: true } : data))
  vi.stubGlobal('fetch', fetchMock)
  mount(button(onDeleted))
  await userEvent.click(screen.getByRole('button'))
  const dialog = within(screen.getByRole('dialog'))
  expect(await dialog.findByText(/Сесии за удостоверяване/)).toHaveTextContent('2')
  const submit = dialog.getByRole('button', { name: 'Изтрий окончателно' })
  expect(submit).toBeDisabled()
  await userEvent.type(dialog.getByLabelText('Текуща парола на собственика'), 'QA-password')
  expect(submit).toBeDisabled()
  const confirmation = dialog.getByLabelText(/Въведете точно следната фраза/)
  await userEvent.type(confirmation, 'DELETE QA ')
  expect(submit).toBeDisabled()
  await userEvent.clear(confirmation)
  await userEvent.type(confirmation, 'DELETE QA')
  expect(submit).toBeEnabled()
  await userEvent.click(submit)
  await waitFor(() => expect(onDeleted).toHaveBeenCalledOnce())
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  expect(fetchMock.mock.calls[1][1]?.body).toContain('"confirmation_text":"DELETE QA"')
  expect(localStorage.getItem('current_password')).toBeNull()
})

it('renders blockers and does not permit submitting a blocked target', async () => {
  const fetchMock = vi.fn(async () => json({ ...data, can_delete: false, blockers: [{ code: 'repairs', count: 4, label_key: 'ownerDeletion.references.repairs' }] }))
  vi.stubGlobal('fetch', fetchMock)
  mount(button())
  await userEvent.click(screen.getByRole('button'))
  const dialog = within(screen.getByRole('dialog'))
  expect(await dialog.findByText(/Ремонти и ремонтна история/)).toHaveTextContent('4')
  expect(dialog.queryByRole('button', { name: 'Изтрий окончателно' })).not.toBeInTheDocument()
  expect(dialog.queryByLabelText('Текуща парола на собственика')).not.toBeInTheDocument()
  expect(fetchMock).toHaveBeenCalledOnce()
})

it('shows recomputed blockers from execution and clears the password', async () => {
  vi.stubGlobal('fetch', vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => init?.method === 'POST'
    ? json({ detail: { code: 'deletion_blocked', blockers: [{ code: 'repairs', count: 1, label_key: 'ownerDeletion.references.repairs' }] } }, 409) : json(data)))
  mount(button())
  await userEvent.click(screen.getByRole('button'))
  await completeDialog()
  expect(await screen.findByRole('alert')).toHaveTextContent('Изтриването е блокирано')
  expect(screen.getByText(/Ремонти и ремонтна история/)).toHaveTextContent('1')
  expect(screen.queryByLabelText('Текуща парола на собственика')).not.toBeInTheDocument()
})

it('keeps rejected deletion open, translates errors, and clears rejected password', async () => {
  vi.stubGlobal('fetch', vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => init?.method === 'POST' ? json({ detail: { code: 'reauthentication_failed', message: 'RAW DATABASE DETAIL' } }, 403) : json(data)))
  mount(button())
  await userEvent.click(screen.getByRole('button'))
  await completeDialog()
  expect(await screen.findByRole('alert')).toHaveTextContent('Текущата парола е неправилна.')
  expect(screen.getByLabelText('Текуща парола на собственика')).toHaveValue('')
  expect(screen.queryByText('RAW DATABASE DETAIL')).not.toBeInTheDocument()
})

it('supports keyboard close, focus trapping and focus restoration', async () => {
  vi.stubGlobal('fetch', vi.fn(async () => json(data)))
  mount(button())
  const trigger = screen.getByRole('button')
  trigger.focus()
  await userEvent.keyboard('{Enter}')
  const close = within(screen.getByRole('dialog')).getByRole('button', { name: 'Затвори' })
  expect(close).toHaveFocus()
  await screen.findByLabelText('Текуща парола на собственика')
  await userEvent.keyboard('{Shift>}{Tab}{/Shift}')
  expect(within(screen.getByRole('dialog')).getByRole('button', { name: 'Отказ' })).toHaveFocus()
  await userEvent.keyboard('{Escape}')
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  expect(trigger).toHaveFocus()
  expect(document.body.style.overflow).not.toBe('hidden')
})

it.each(['bg', 'en', 'ru'] as const)('contains explicit complete deletion translations and renders %s', locale => {
  setSessionUser({ ...owner, preferred_language: locale })
  const keys = Object.keys(bg).filter(key => key.startsWith('ownerDeletion.')) as Array<keyof typeof bg>
  expect(keys.length).toBeGreaterThan(40)
  for (const key of keys) {
    expect(en[key]).toBeTruthy(); expect(ru[key]).toBeTruthy()
    if (!key.endsWith('confirmation')) { expect(en[key]).not.toBe(bg[key]); expect(ru[key]).not.toBe(bg[key]) }
  }
  render(<I18nProvider initialLocale={locale}>{button()}</I18nProvider>)
  expect(screen.getByRole('button')).toHaveTextContent(translate(locale, 'ownerDeletion.action'))
})

it('keeps the mobile dialog within viewport and scrollable', () => {
  const css = styles
  expect(css).toContain('width: min(560px, calc(100vw - 24px))')
  expect(css).toContain('max-height: calc(100dvh - 24px)')
  expect(css).toContain('overflow-y: auto')
  expect(css).toContain('.owner-deletion-dialog .actions > button { flex: 1 1 100%')
})

it('owner deletes nonowner administrator and the refreshed user row disappears', async () => {
  const other = { ...owner, id: 2, email: 'other@qa.invalid', full_name: 'QA Other', is_system_owner: false }
  let deleted = false
  vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
    const path = String(input)
    if (path.includes('/preview')) return json(data)
    if (path.includes('/execute')) { deleted = true; return json({ deleted: true }) }
    return json(path.includes('/departments') ? [] : deleted ? [owner] : [owner, other])
  }))
  mount(<UserAdministration />)
  const ownerRow = (await screen.findByText('QA Owner')).closest('tr')!
  expect(within(ownerRow).queryByRole('button')).not.toBeInTheDocument()
  await userEvent.click(screen.getByRole('button', { name: 'Изтрий окончателно: other@qa.invalid' }))
  await completeDialog()
  await waitFor(() => expect(screen.queryByText('QA Other')).not.toBeInTheDocument())
})

it.each(['asset_category', 'category_field'] as const)('refreshes %s after owner deletion', async resource => {
  const category = { id: 5, code: 'QA', name_bg: 'QA Category', capabilities: [], is_active: true, fields: [{ id: 9, category_id: 5, code: 'QA_FIELD', label_bg: 'QA Field', field_type: 'TEXT', is_active: true, sort_order: 0 }] }
  let deleted = false
  const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
    const path = String(input)
    if (path.includes('/preview')) return json(data)
    if (path.includes('/execute')) { deleted = true; return json({ deleted: true }) }
    if (path.includes('asset-capabilities')) return json([])
    return json(deleted ? resource === 'asset_category' ? [] : [{ ...category, fields: [] }] : [category])
  })
  vi.stubGlobal('fetch', fetchMock)
  mount(<CategoryAdministration />)
  const identity = resource === 'asset_category' ? 'QA' : 'QA_FIELD'
  await userEvent.click(await screen.findByRole('button', { name: `Изтрий окончателно: ${identity}` }))
  await completeDialog()
  await waitFor(() => expect(screen.queryByText(resource === 'asset_category' ? 'QA Category' : 'QA Field')).not.toBeInTheDocument())
  if (resource === 'category_field') expect(fetchMock.mock.calls.some(([path]) => String(path).includes('category_id=5'))).toBe(true)
})

it.each(['department', 'location'] as const)('refreshes %s reference data after deletion', async resource => {
  let deleted = false
  vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
    const path = String(input)
    if (path.includes('/preview')) return json(data)
    if (path.includes('/execute')) { deleted = true; return json({ deleted: true }) }
    if (path.includes('/admin/reference-data')) return json({ locations: deleted && resource === 'location' ? [] : [{ id: 3, name: 'QA Location', is_active: true }], departments: deleted && resource === 'department' ? [] : [{ id: 4, code: 'QA_DEPT', name_bg: 'QA Department', is_active: true }] })
    return json([])
  }))
  mount(<AdministrationPanel />)
  await userEvent.click(await screen.findByRole('button', { name: `Изтрий окончателно: ${resource === 'department' ? 'QA_DEPT' : 'QA Location'}` }))
  await completeDialog()
  await waitFor(() => expect(screen.queryByText(resource === 'department' ? 'QA Department' : 'QA Location')).not.toBeInTheDocument())
})

it('deletes from machine details and refreshes the empty registry and category count', async () => {
  let deleted = false
  window.history.replaceState({}, '', '/machines?category=QA')
  const category = { id: 5, code: 'QA', name_bg: 'QA Category', is_active: true, asset_count: 1, has_pressure: false }
  const machine = { id: 8, inventory_number: 'QA', name: 'QA Machine', brand: 'QA', category: 'QA', category_id: 5, status: 'READY', is_active: true }
  vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
    const path = String(input)
    if (path.includes('/preview')) return json(data)
    if (path.includes('/execute')) { deleted = true; return json({ deleted: true }) }
    if (path.includes('/machines/category-navigation')) return json([{ ...category, asset_count: deleted ? 0 : 1 }])
    if (path.includes('form-data')) return json({ category: { ...category, fields: [], capabilities: [] }, values: [] })
    if (path.includes('form-definition')) return json({ ...category, fields: [], capabilities: [] })
    if (path.includes('/machines?')) return json(deleted ? [] : [machine])
    return json([])
  }))
  mount(<Machines onOpenCatalog={vi.fn()} />)
  await screen.findByText('QA Machine')
  expect(screen.queryByRole('button', { name: 'Изтрий окончателно: QA' })).not.toBeInTheDocument()
  await userEvent.click(screen.getByRole('button', { name: 'Детайли' }))
  await userEvent.click(screen.getByRole('button', { name: 'Изтрий окончателно: QA' }))
  await completeDialog()
  await waitFor(() => expect(screen.queryByText('QA Machine')).not.toBeInTheDocument())
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  expect(screen.getByRole('button', { name: /QA Category.*0/ })).toBeVisible()
  expect(window.location.search).toBe('?category=QA')
})
