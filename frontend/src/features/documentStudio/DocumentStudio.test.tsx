import { act, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, expect, it, vi } from 'vitest'
import { I18nProvider } from '../../i18n'
import { setSessionUser } from '../../permissions'
import type { UserSession } from '../../types'
import DocumentStudio from './DocumentStudio'
import { studioBg, studioEn, studioRu } from './translations'
import { defaultStyle } from './editorModel'

const identity = { legal_name: 'Synthetic QA', short_name: '', registration_number: '', vat_number: '', address: '', city: '', country: '', phone: '', email: '', website: '', primary_color: '#183153', secondary_color: '#64748b', default_language: 'bg', timezone: 'UTC', primary_logo_id: null, secondary_logo_id: null, identity_image_ids: [] }
const user: UserSession = { id: 1, email: 'qa@example.invalid', full_name: 'QA', role: 'administrator', preferred_language: 'bg', is_active: true, is_system_owner: false, must_change_password: false, permissions: ['studio.view', 'templates.manage', 'company.manage'], created_at: '', updated_at: '' }
const json = (value: unknown, status = 200) => new Response(JSON.stringify(value), { status, headers: { 'Content-Type': 'application/json' } })
const template = { id: 1, code: 'QA', document_type: 'PART_REQUEST', name_bg: 'Тестов шаблон', name_en: 'QA template', name_ru: 'Тестовый шаблон', authoring_supported: true, versions: [] }
const draft = { id: 10, template_id: 1, base_version_id: null, language: 'bg', title: 'QA draft', revision: 1, layout: { schema_version: 1, positioning: 'flow', page: { format: 'A4', orientation: 'portrait', margin_mm: 15 }, blocks: [{ id: 'number', type: 'field', field: 'DOCUMENT_NUMBER' }] } }

afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks() })

function mount(role: UserSession = user, locale: 'bg' | 'en' | 'ru' = 'bg') {
  setSessionUser({ ...role, preferred_language: locale })
  return render(<I18nProvider initialLocale={locale}><DocumentStudio onDirty={vi.fn()} /></I18nProvider>)
}

it.each([['bg', 'Фирмено наименование'], ['en', 'Company legal name'], ['ru', 'Наименование компании']] as const)('localizes profile controls in %s', async (locale, name) => {
  vi.stubGlobal('fetch', vi.fn(async (path: string) => json(path.endsWith('/company') ? { revision: 0, identity } : [])))
  mount(user, locale)
  expect(await screen.findByLabelText(name)).toHaveValue('Synthetic QA')
  expect(Object.keys(studioEn).sort()).toEqual(Object.keys(studioBg).sort())
  expect(Object.keys(studioRu).sort()).toEqual(Object.keys(studioBg).sort())
})

it('waits for server confirmation and sends the loaded revision', async () => {
  let finish!: (response: Response) => void
  const fetch = vi.fn(async (path: string, init?: RequestInit) => {
    if (init?.method === 'PUT') return new Promise<Response>(resolve => { finish = resolve })
    return json(path.endsWith('/company') ? { revision: 3, identity } : [])
  })
  vi.stubGlobal('fetch', fetch); mount()
  await userEvent.clear(await screen.findByLabelText('Фирмено наименование'))
  await userEvent.type(screen.getByLabelText('Фирмено наименование'), 'QA changed')
  await userEvent.click(screen.getByRole('button', { name: 'Запази промените' }))
  expect(screen.getByRole('status')).toHaveTextContent('Запазване…')
  expect(screen.queryByText('Потвърдено от сървъра')).not.toBeInTheDocument()
  const call = fetch.mock.calls.find(([, init]) => init?.method === 'PUT')!
  expect(JSON.parse(String(call[1]!.body)).expected_revision).toBe(3)
  await act(async () => finish(json({ revision: 4, identity: { ...identity, legal_name: 'QA changed' } })))
  await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent('Потвърдено от сървъра'))
})

it.each([409, 503])('retains unsaved company edits after status %s', async status => {
  vi.stubGlobal('fetch', vi.fn(async (path: string, init?: RequestInit) => init?.method === 'PUT' ? json({ detail: { code: 'studio_conflict' } }, status) : json(path.endsWith('/company') ? { revision: 1, identity } : [])))
  mount()
  await userEvent.type(await screen.findByLabelText('Кратко име'), 'QA local edit')
  await userEvent.click(screen.getByRole('button', { name: 'Запази промените' }))
  expect(await screen.findByRole('alert')).toBeVisible()
  expect(screen.getByLabelText('Кратко име')).toHaveValue('QA local edit')
  expect(screen.getByRole('status')).toHaveTextContent('Незапазени промени')
})

it('gives directors view access without management controls', async () => {
  vi.stubGlobal('fetch', vi.fn(async (path: string) => json(path.endsWith('/company') ? { revision: 0, identity } : [])))
  mount({ ...user, role: 'director', permissions: ['studio.view'] })
  expect(await screen.findByLabelText('Фирмено наименование')).toBeDisabled()
  expect(screen.queryByRole('button', { name: 'Запази промените' })).not.toBeInTheDocument()
  expect(screen.queryByRole('button', { name: 'Качи изображение' })).not.toBeInTheDocument()
  await userEvent.click(screen.getByRole('button', { name: 'Библиотека с шаблони' }))
  expect(screen.queryByRole('button', { name: 'Нов шаблон' })).not.toBeInTheDocument()
})

it('warns before discarding profile changes when switching sections', async () => {
  vi.stubGlobal('fetch', vi.fn(async (path: string) => json(path.endsWith('/company') ? { revision: 0, identity } : [])))
  vi.spyOn(window, 'confirm').mockReturnValue(false)
  mount()
  await userEvent.type(await screen.findByLabelText('Кратко име'), 'QA')
  await userEvent.click(screen.getByRole('button', { name: 'Библиотека с шаблони' }))
  expect(window.confirm).toHaveBeenCalled()
  expect(screen.getByLabelText('Кратко име')).toHaveValue('QA')
  const event = new Event('beforeunload', { cancelable: true })
  window.dispatchEvent(event)
  expect(event.defaultPrevented).toBe(true)
})

it('creates and reopens a real draft and preserves edits on revision conflicts', async () => {
  const requests: string[] = []
  vi.stubGlobal('fetch', vi.fn(async (path: string, init?: RequestInit) => {
    requests.push(path)
    if (path.endsWith('/company')) return json({ revision: 0, identity })
    if (path.endsWith('/templates')) return json([template])
    if (path.endsWith('/schema')) return json({ fields: [{ code: 'DOCUMENT_NUMBER', group: 'operation' }] })
    if (path.endsWith('/drafts')) return json(init?.method === 'POST' ? draft : [])
    if (init?.method === 'PUT') return json({ detail: { code: 'studio_conflict' } }, 409)
    return json([])
  }))
  mount()
  await screen.findByLabelText('Фирмено наименование')
  await userEvent.click(screen.getByRole('button', { name: 'Библиотека с шаблони' }))
  await userEvent.type(await screen.findByLabelText('Име на черновата'), 'QA draft')
  await userEvent.click(screen.getByRole('button', { name: 'Създай' }))
  const form = await screen.findByRole('region', { name: 'Визуален редактор' })
  await userEvent.click(within(form).getByLabelText('Автозапис'))
  expect(form.querySelector('.editor-paper .editor-field-token')).toHaveTextContent('Номер на документа')
  await userEvent.selectOptions(within(form).getByLabelText('Ориентация'), 'landscape')
  await userEvent.click(within(form).getByRole('button', { name: 'Запази промените' }))
  expect(await within(form).findByRole('alert')).toHaveTextContent('Има по-нова версия')
  expect(within(form).getByLabelText('Ориентация')).toHaveValue('landscape')
  expect(requests.some(path => path.includes('publish'))).toBe(false)
  expect(screen.queryByRole('textbox', { name: /JSON/ })).not.toBeInTheDocument()
})

it('adopts normalized server block defaults after a successful save and becomes clean', async () => {
  vi.stubGlobal('fetch', vi.fn(async (path: string, init?: RequestInit) => {
    if (path.endsWith('/company')) return json({ revision: 0, identity })
    if (path.endsWith('/templates')) return json([template])
    if (path.endsWith('/schema')) return json({ fields: [{ code: 'DOCUMENT_NUMBER', group: 'operation' }] })
    if (path.endsWith('/drafts')) return json(init?.method === 'POST' ? draft : [])
    if (init?.method === 'PUT') {
      const payload = JSON.parse(String(init.body))
      return json({ ...draft, title: payload.title, revision: 2, layout: { ...payload.layout,
        blocks: payload.layout.blocks.map((block: Record<string, unknown>) => ({ region: 'body', style: defaultStyle, ...block })) } })
    }
    return json([])
  }))
  mount(); await screen.findByLabelText('Фирмено наименование')
  await userEvent.click(screen.getByRole('button', { name: 'Библиотека с шаблони' }))
  await userEvent.type(await screen.findByLabelText('Име на черновата'), 'QA draft')
  await userEvent.click(screen.getByRole('button', { name: 'Създай' }))
  const editor = await screen.findByRole('region', { name: 'Визуален редактор' })
  await userEvent.click(within(editor).getByLabelText('Автозапис'))
  await userEvent.click(within(editor).getByRole('button', { name: 'Текст' }))
  await userEvent.click(within(editor).getByRole('button', { name: 'Запази промените' }))
  await waitFor(() => expect(within(editor).getByRole('status')).toHaveTextContent('Потвърдено от сървъра'))
  expect(within(editor).getByRole('button', { name: 'Запази промените' })).toBeDisabled()
  expect(within(editor).getByRole('button', { name: 'Провери и виж PDF' })).toBeEnabled()
})
