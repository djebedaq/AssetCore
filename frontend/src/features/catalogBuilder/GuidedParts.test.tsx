import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, expect, it, vi } from 'vitest'
import { I18nProvider } from '../../i18n'
import GuidedParts from './GuidedParts'
import type { Preview, ReferencePage, Source } from './guidedTypes'
import { ReviewTestTransport } from './reviewTestTransport'

const json = (value: unknown, status = 200) => new Response(JSON.stringify(value), { status, headers: { 'Content-Type': 'application/json' } })
const source = (id: number, sort_order: number, artifact_id = 20): Source => ({ id, sort_order, artifact_id, page_number: id - 8, role: 'SPARE_PARTS_LIST', filename: `qa-${artifact_id}.pdf`, title: 'Synthetic QA' })
const makePage = (sources: Source[]): ReferencePage => ({ id: 7, assembly_id: 3, version: 1, stable_key: 'qa', sort_order: 0, title: null,
  sources, scheme_count: 1, spare_list_count: sources.filter(item => item.role === 'SPARE_PARTS_LIST').length,
  part_count: 0, position_count: 0, mapped_position_count: 0, status: 'NEEDS_ATTENTION' })
const preview = (item: Source, start: number): Preview => ({ token: `signed-${item.id}`, source: { visual_page_id: item.id, artifact_id: item.artifact_id, page_number: item.page_number, filename: item.filename },
  warnings: [], method: 'NATIVE', tables: [], rows: Array.from({ length: 5 }, (_, index) => ({
    payload: { position: String(start + index), part_number: `QA-${start + index}`, description: 'Synthetic component', quantity: 2 },
    raw_text: `QA row ${start + index}`, warnings: [], bbox: [0, index * 10, 100, index * 10 + 8],
  })) })
afterEach(() => { cleanup(); vi.unstubAllGlobals(); vi.restoreAllMocks() })

it('one action retries an earlier unresolved list after the later sources and preserves a failed source', async () => {
  const sources = [source(10, 0), source(11, 1), source(12, 2)]
  const requests: Record<string, unknown>[] = [], durable = new ReviewTestTransport()
  vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const resumed = durable.handle(String(input), init); if (resumed) return resumed
    if (String(input).endsWith('/extract')) {
      const body = JSON.parse(String(init?.body)); requests.push(body)
      if (body.visual_page_id === 11) return json({ detail: { code: 'catalog_extraction_page_failed' } }, 422)
      const item = sources.find(s => s.id === body.visual_page_id)!
      const result = preview(item, item.id === 10 ? 1 : 6)
      if (item.id === 10 && !body.group_context) {
        result.rows = []
        result.quality = { state: 'NEEDS_REVIEW', observed_rows: 5, candidate_rows: 0, missing_rows: 5, partial_rows: 0, needs_context: true }
      }
      return json(durable.record(result))
    }
    return json([])
  }))
  render(<I18nProvider><GuidedParts page={makePage(sources)} changed={vi.fn(async () => {})} onDirtyChange={vi.fn()} /></I18nProvider>)
  await userEvent.setup().click(screen.getByRole('button', { name: 'Разпознай частите' }))
  await waitFor(() => expect(requests).toHaveLength(4))
  expect(requests.map(body => body.visual_page_id)).toEqual([10, 11, 12, 10])
  expect(requests[3]).toEqual({ visual_page_id: 10, continuation_token: null, expected_version: 1, group_context: true, context_only: true })
  await screen.findByText('Общо части: 10 · Обработени източници: 3 / 3')
  expect(within(screen.getByLabelText('Списъци с резервни части')).getByRole('button', { name: 'Грешка — опитайте отново' })).toBeEnabled()
  expect(screen.getAllByRole('checkbox')).toHaveLength(10)
})

it('saves technical corrections on both rows when focus changes before the debounce', async () => {
  const item = source(10, 0), durable = new ReviewTestTransport()
  durable.record(preview(item, 1))
  vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) =>
    durable.handle(String(input), init) || json([])))
  render(<I18nProvider><GuidedParts page={makePage([item])} changed={vi.fn(async () => {})} onDirtyChange={vi.fn()} /></I18nProvider>)
  const user = userEvent.setup()
  await user.click(await screen.findByText('Допълнителни данни и решение за реда'))
  const first = screen.getByLabelText('Бележки')
  fireEvent.change(first, { target: { value: 'Human note on first row' } }); fireEvent.blur(first)
  await user.click(screen.getByRole('button', { name: /^Провери позиция 2,/ }))
  const second = screen.getByLabelText('Бележки')
  fireEvent.change(second, { target: { value: 'Human note on second row' } }); fireEvent.blur(second)
  await waitFor(() => expect(durable.previews.get(item.id)?.rows.map(row => row.payload.technical_notes).slice(0, 2))
    .toEqual(['Human note on first row', 'Human note on second row']))
  cleanup()
  render(<I18nProvider><GuidedParts page={makePage([item])} changed={vi.fn(async () => {})} onDirtyChange={vi.fn()} /></I18nProvider>)
  await user.click(await screen.findByText('Допълнителни данни и решение за реда'))
  expect(screen.getByLabelText('Бележки')).toHaveValue('Human note on first row')
  await user.click(screen.getByRole('button', { name: /^Провери позиция 2,/ }))
  expect(screen.getByLabelText('Бележки')).toHaveValue('Human note on second row')
})

it.each([1, 2, 3, 4, 7])('one click processes %i ordered sources and confirms every source with its own token', async count => {
  const sources = Array.from({ length: count }, (_, i) => source(10 + i, i, i === 2 ? 30 : 20))
  const requests: Record<string, unknown>[] = []
  const confirmations: Record<string, unknown>[] = []
  const changed = vi.fn(async () => {})
  const durable = new ReviewTestTransport()
  vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const path = String(input)
    const resumed = durable.handle(path, init); if (resumed) return resumed
    if (path.endsWith('/extract')) {
      const body = JSON.parse(String(init?.body)); requests.push(body)
      const index = sources.findIndex(item => item.id === body.visual_page_id)
      return json(durable.record(preview(sources[index], index * 5 + 1)))
    }
    if (path.endsWith('/confirm')) { confirmations.push(JSON.parse(String(init?.body))); return json({ created_count: 5 }) }
    return json([])
  }))
  render(<I18nProvider><GuidedParts page={makePage([{ ...source(99, -1), role: 'EXPLODED_SCHEME' }, ...[...sources].reverse()])} changed={changed} onDirtyChange={vi.fn()} /></I18nProvider>)
  const user = userEvent.setup()
  await user.click(screen.getByRole('button', { name: 'Разпознай частите' }))
  await waitFor(() => expect(screen.getAllByRole('checkbox')).toHaveLength(count * 5))
  expect(requests).toEqual(sources.map((item, index) => ({ visual_page_id: item.id, continuation_token: index ? `signed-${sources[index - 1].id}` : null,
    expected_version: 1, group_context: false, context_only: false })))
  expect(screen.getByText(`Общо части: ${count * 5} · Обработени източници: ${count} / ${count}`)).toBeVisible()
  for (let i = 1; i <= count * 5; i++) expect(screen.getByRole('checkbox', { name: new RegExp(`^Позиция ${i} ·`) })).toBeVisible()
  await user.click(screen.getByRole('button', { name: 'Потвърди избраните части' }))
  await waitFor(() => expect(changed).toHaveBeenCalled())
  expect(confirmations.map(item => item.token)).toEqual(sources.map(item => `signed-${item.id}`))
  expect(confirmations.map(item => (item.rows as unknown[]).length)).toEqual(sources.map(() => 5))
})

it('accounts for a failed middle source, continues, and retries that source without losing edits or accepted rows', async () => {
  const sources = [source(10, 0), source(11, 1), source(12, 2)]
  let fail = true
  const durable = new ReviewTestTransport()
  const requests: Record<string, unknown>[] = []
  vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const resumed = durable.handle(String(input), init); if (resumed) return resumed
    if (String(input).endsWith('/extract')) {
      const body = JSON.parse(String(init?.body)); requests.push(body)
      if (body.visual_page_id === 11 && fail) return json({ detail: { code: 'catalog_extraction_page_failed' } }, 422)
      const index = sources.findIndex(item => item.id === body.visual_page_id)
      return json(durable.record(preview(sources[index], index * 5 + 1)))
    }
    return json([])
  }))
  render(<I18nProvider><GuidedParts page={makePage(sources)} changed={vi.fn(async () => {})} onDirtyChange={vi.fn()} /></I18nProvider>)
  const user = userEvent.setup()
  await user.click(screen.getByRole('button', { name: 'Разпознай частите' }))
  await screen.findByText('Общо части: 10 · Обработени източници: 3 / 3')
  expect(requests[2]).toEqual({ visual_page_id: 12, continuation_token: null, expected_version: 1, group_context: false, context_only: false })
  expect(within(screen.getByLabelText('Списъци с резервни части')).getByRole('alert')).toHaveTextContent('PDF страница 3')
  const first = screen.getAllByLabelText('Описание')[0]
  await user.clear(first); await user.type(first, 'Human correction')
  fail = false
  await waitFor(() => expect(within(screen.getByLabelText('Списъци с резервни части')).getByRole('button', { name: 'Грешка — опитайте отново' })).toBeEnabled())
  await user.click(within(screen.getByLabelText('Списъци с резервни части')).getByRole('button', { name: 'Грешка — опитайте отново' }))
  await screen.findByText('Общо части: 15 · Обработени източници: 3 / 3')
  expect(requests).toHaveLength(4)
  expect(screen.getAllByLabelText('Описание')[0]).toHaveValue('Human correction')
})

it('shows a zero-row source and maps only that page while keeping the first page review', async () => {
  const sources = [source(10, 0), source(11, 1)]
  const second = preview(sources[1], 6)
  const unresolved: Preview = { ...second, rows: [], warnings: ['CONTINUATION_UNRESOLVED'], tables: [{
    bbox: [0, 0, 100, 100], headers: ['', '', '', ''], sample_cells: [['6', 'QA-6', 'Synthetic component', '2']], schema: { state: 'NEEDS_REVIEW', mapping: {} },
  }] }
  let mapping: Record<string, unknown> | undefined
  const durable = new ReviewTestTransport()
  vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const path = String(input)
    const resumed = durable.handle(path, init); if (resumed) return resumed
    if (path.endsWith('/extract')) return json(durable.record(JSON.parse(String(init?.body)).visual_page_id === 10 ? preview(sources[0], 1) : unresolved))
    if (path.endsWith('/mapping')) { mapping = JSON.parse(String(init?.body)); return json(durable.record(second)) }
    return json([])
  }))
  render(<I18nProvider><GuidedParts page={makePage(sources)} changed={vi.fn(async () => {})} onDirtyChange={vi.fn()} /></I18nProvider>)
  const user = userEvent.setup()
  await user.click(screen.getByRole('button', { name: 'Разпознай частите' }))
  await screen.findByText('Общо части: 5 · Обработени източници: 2 / 2')
  expect(screen.getAllByText(/qa-20.pdf · PDF страница 3/)[0]).toBeVisible()
  const first = screen.getByLabelText('Описание')
  await user.clear(first); await user.type(first, 'Kept edit')
  await user.click(screen.getByText('Уточни колоните', { selector: 'summary' }))
  await waitFor(() => expect(screen.getByRole('combobox', { name: /^Колона 1/ })).toBeEnabled())
  for (const [index, role] of ['position', 'part_number', 'description', 'quantity'].entries()) {
    await user.selectOptions(screen.getByRole('combobox', { name: new RegExp(`^Колона ${index + 1}`) }), role)
  }
  await user.click(screen.getByRole('button', { name: 'Прочети таблицата отново' }))
  await screen.findByText('Общо части: 10 · Обработени източници: 2 / 2')
  expect(mapping?.token).toBe('signed-11')
  expect(screen.getAllByLabelText('Описание')[0]).toHaveValue('Kept edit')
  expect(screen.getAllByRole('checkbox')).toHaveLength(10)
})
