import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, expect, it, vi } from 'vitest'
import { I18nProvider } from '../../i18n'
import GuidedWorkspace from './GuidedWorkspace'
import GuidedParts from './GuidedParts'
import GuidedSources from './GuidedSources'
import { UploadTestTransport } from './uploadTestTransport'
import type { Preview, ReferencePage } from './guidedTypes'
import { guidedBg, guidedEn, guidedRu } from './guidedTranslations'

const json = (value: unknown) => new Response(JSON.stringify(value), { headers: { 'Content-Type': 'application/json' } })
const page: ReferencePage = { id: 7, assembly_id: 3, stable_key: 'qa-page', sort_order: 0, version: 1, title: null,
  sources: [{ id: 11, artifact_id: 20, page_number: 5, role: 'SPARE_PARTS_LIST', title: 'QA source', filename: 'qa.pdf' }],
  scheme_count: 0, spare_list_count: 1, part_count: 0, position_count: 0, mapped_position_count: 0, status: 'NEEDS_ATTENTION' }
const row = { payload: { position: '1', part_number: 'QA-1', description: 'Original description', quantity: 2 }, warnings: [], raw_text: '1 QA-1 Original description 2' }
const preview: Preview = { token: 'signed-qa-preview', source: { visual_page_id: 11, artifact_id: 20, page_number: 5, filename: 'qa.pdf' },
  warnings: [], method: 'NATIVE', rows: [row], tables: [] }
afterEach(() => { cleanup(); vi.unstubAllGlobals(); vi.restoreAllMocks() })

it('extracts only explicit lists, edits a preview and confirms in bulk with its signed source token', async () => {
  const requests: Array<{ path: string; body: Record<string, unknown> }> = []
  vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const path = String(input)
    if (init?.method === 'POST') requests.push({ path, body: JSON.parse(String(init.body)) })
    if (path.endsWith('/extract')) return json(preview)
    if (path.endsWith('/confirm')) return json({ created_count: 1, part_ids: [1] })
    return json([])
  }))
  const changed = vi.fn(async () => {})
  render(<I18nProvider><GuidedParts page={page} changed={changed} onDirtyChange={vi.fn()} /></I18nProvider>)
  const user = userEvent.setup()
  await user.click(screen.getByRole('button', { name: 'Извлечи резервните части' }))
  await screen.findByRole('button', { name: 'Потвърди избраните части' })
  expect(requests[0].body).toEqual({ visual_page_id: 11, continuation_token: null })
  expect(requests.some(item => item.path.includes('/analysis'))).toBe(false)
  await user.selectOptions(screen.getByLabelText('Покажи'), 'all')
  const description = screen.getByLabelText('Описание 1')
  await user.clear(description); await user.type(description, 'Human source correction')
  expect(requests.filter(item => item.path.endsWith('/confirm'))).toHaveLength(0)
  await user.click(screen.getByRole('button', { name: 'Потвърди избраните части' }))
  await waitFor(() => expect(changed).toHaveBeenCalled())
  const confirmation = requests.find(item => item.path.endsWith('/confirm'))!
  expect(confirmation.body.token).toBe('signed-qa-preview')
  expect(confirmation.body.rows).toEqual([{ index: 0, part: { ...row.payload, description: 'Human source correction' } }])
})

it('shows actual ambiguous column samples and rereads using one explicit mapping', async () => {
  let submitted: unknown
  const uncertain: Preview = { ...preview, rows: [], warnings: ['SCHEMA_AMBIGUOUS'], tables: [{
    headers: ['ID', 'Number', 'Type', 'Qty'], sample_cells: [['1', '51', 'Seal', '2'], ['4', '54', 'Pump', '1']],
    schema: { state: 'NEEDS_REVIEW', mapping: {} },
  }] }
  vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const path = String(input)
    if (path.endsWith('/extract')) return json(uncertain)
    if (path.endsWith('/mapping')) { submitted = JSON.parse(String(init?.body)); return json(preview) }
    return json([])
  }))
  render(<I18nProvider><GuidedParts page={page} changed={vi.fn(async () => {})} onDirtyChange={vi.fn()} /></I18nProvider>)
  const user = userEvent.setup()
  await user.click(screen.getByRole('button', { name: 'Извлечи резервните части' }))
  expect(await screen.findByText('Seal')).toBeVisible()
  await user.selectOptions(screen.getByRole('combobox', { name: /^ID/ }), 'position')
  await user.selectOptions(screen.getByRole('combobox', { name: /^Number/ }), 'part_number')
  await user.selectOptions(screen.getByRole('combobox', { name: /^Type/ }), 'description')
  await user.selectOptions(screen.getByRole('combobox', { name: /^Qty/ }), 'quantity')
  await user.click(screen.getByRole('button', { name: 'Прочети таблицата отново' }))
  await waitFor(() => expect(submitted).toEqual({ token: 'signed-qa-preview', table_index: 0,
    mapping: { '0': 'position', '1': 'part_number', '2': 'description', '3': 'quantity' } }))
  await user.selectOptions(screen.getByLabelText('Покажи'), 'all')
  expect(await screen.findByLabelText('Номер на част 1')).toHaveValue('QA-1')
})

it('keeps exact BG/EN/RU guided terminology parity without obsolete inference concepts', () => {
  expect(Object.keys(guidedEn).sort()).toEqual(Object.keys(guidedBg).sort())
  expect(Object.keys(guidedRu).sort()).toEqual(Object.keys(guidedBg).sort())
  expect(Object.keys(guidedEn).some(key => /candidate|group_key|extractor_version/.test(key))).toBe(false)
})

it('uploads a large PDF in Scheme mode and assigns the current readable page without role checkboxes', async () => {
  vi.stubGlobal('XMLHttpRequest', UploadTestTransport)
  vi.stubGlobal('ResizeObserver', class { observe() {} disconnect() {} })
  const NativeURL = URL
  vi.stubGlobal('URL', class extends NativeURL { static createObjectURL = vi.fn(() => 'blob:pdf-page'); static revokeObjectURL = vi.fn() })
  let assigned: Record<string, unknown> | undefined
  let uploaded: File | undefined
  const document = { id: 20, filename: 'qa-large.pdf', page_count: 16, assignments: [] }
  vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const path = String(input)
    if (path.endsWith('/pdf')) { uploaded = (init?.body as FormData).get('file') as File; return json(document) }
    if (path.includes('/preview')) return new Response(new Uint8Array([137]), { headers: { 'Content-Type': 'image/png' } })
    if (path.endsWith('/sources')) { assigned = JSON.parse(String(init?.body)); return json(page) }
    return json([document])
  }))
  const changed = vi.fn(async () => {})
  render(<I18nProvider><GuidedSources revisionId={2} page={page} changed={changed} onDirtyChange={vi.fn()} /></I18nProvider>)
  const user = userEvent.setup()
  await user.click(screen.getByRole('button', { name: '+ Добави схема' }))
  await user.upload(screen.getByLabelText('Качи PDF'), new File([new Uint8Array(16 * 1024 * 1024)], 'qa-large.pdf', { type: 'application/pdf' }))
  await waitFor(() => expect(uploaded?.size).toBe(16 * 1024 * 1024))
  expect(uploaded?.name).toBe('qa-large.pdf')
  await screen.findByRole('img', { name: 'PDF страница 1' })
  fireEvent.change(screen.getByRole('spinbutton'), { target: { value: '5' } })
  fireEvent.keyDown(screen.getByRole('spinbutton'), { key: 'Enter' })
  await screen.findByRole('img', { name: 'PDF страница 5' })
  expect(screen.queryByRole('checkbox')).toBeNull()
  await user.click(screen.getByRole('button', { name: 'Добави тази страница като схема' }))
  await waitFor(() => expect(assigned).toEqual({ expected_version: 1, artifact_id: 20, page_numbers: [5], roles: ['EXPLODED_SCHEME'] }))
  expect(changed).toHaveBeenCalled()
  expect(screen.getByLabelText('Избор на PDF страници')).toBeVisible()
})


it('creates and renames human references and sends one atomic reorder request', async () => {
  const groups = [1, 2].map(id => ({ id, code: `QA-${id}`, name_bg: `QA reference ${id}`, name_en: `QA reference ${id}`, name_ru: `QA reference ${id}`, part_count: 0, exploded_page_count: 0, spare_list_page_count: 0 }))
  const writes: Array<{ path: string; body: Record<string, unknown> }> = []
  vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const path = String(input)
    if (init?.method) writes.push({ path, body: init.body ? JSON.parse(String(init.body)) : {} })
    if (path.endsWith('/groups')) return json({ ...groups[0], id: 3 })
    return json([])
  }))
  const changed = vi.fn(async () => {})
  render(<I18nProvider><GuidedWorkspace revisionId={8} groups={groups} task="references" changed={changed} onDirtyChange={vi.fn()} /></I18nProvider>)
  const user = userEvent.setup()
  await user.type(screen.getByLabelText('Референция'), 'Human reference')
  await user.click(screen.getByRole('button', { name: 'Добави референция' }))
  await waitFor(() => expect(writes[0].body).toEqual({ name: 'Human reference' }))
  await user.click(screen.getAllByRole('button', { name: 'Редактиране' })[0])
  await user.clear(screen.getByLabelText('Референция')); await user.type(screen.getByLabelText('Референция'), 'Human rename')
  await user.click(screen.getByRole('button', { name: 'Запази' }))
  await waitFor(() => expect(writes.some(item => item.path.endsWith('/assemblies/1') && item.body.name_bg === 'Human rename')).toBe(true))
  await user.click(screen.getAllByRole('button', { name: 'Премести нагоре' })[1])
  await waitFor(() => expect(writes.find(item => item.path.endsWith('/references/reorder'))?.body).toEqual({ expected_ids: [1, 2], ordered_ids: [2, 1] }))
  expect(writes.filter(item => 'sort_order' in item.body)).toHaveLength(0)
})
