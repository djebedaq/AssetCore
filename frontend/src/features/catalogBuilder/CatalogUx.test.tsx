import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, expect, it, vi } from 'vitest'
import { I18nProvider } from '../../i18n'
import GuidedParts from './GuidedParts'
import { ReviewTestTransport } from './reviewTestTransport'
import type { Preview, ReferencePage } from './guidedTypes'
import { catalogUxBg, catalogUxEn, catalogUxRu } from './catalogUxTranslations'
import { evidenceRegion } from './evidenceGeometry'
import GuidedWorkspace from './GuidedWorkspace'

const page: ReferencePage = { id: 7, assembly_id: 3, version: 1, stable_key: 'qa', sort_order: 0, title: null,
  sources: [11, 12].map(id => ({ id, artifact_id: id, page_number: id, role: 'SPARE_PARTS_LIST', title: 'QA', filename: `qa-${id}.pdf` })),
  scheme_count: 1, spare_list_count: 2, part_count: 0, position_count: 0, mapped_position_count: 0, status: 'NEEDS_ATTENTION' }
const preview = (id: number): Preview => ({ token: `qa-${id}`, source: { visual_page_id: id, artifact_id: id, page_number: id, filename: `qa-${id}.pdf` },
  method: 'NATIVE', warnings: [], tables: [], rows: [{ warnings: ['OCR_REQUIRES_REVIEW'], raw_text: 'Original QA row',
    payload: { position: '1', part_number: '001-QA', description: 'Original QA description', quantity: 2 } }] })
const json = (data: unknown, status = 200) => new Response(JSON.stringify(data), { status, headers: { 'Content-Type': 'application/json' } })
afterEach(() => { cleanup(); vi.unstubAllGlobals(); vi.restoreAllMocks() })

function setup(durable: ReviewTestTransport, patch?: (init?: RequestInit) => Response) {
  vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    if (String(input).includes('/extraction-candidates/') && patch) return patch(init)
    return durable.handle(String(input), init) || json([])
  }))
  return render(<I18nProvider><GuidedParts page={page} changed={vi.fn(async () => {})} onDirtyChange={vi.fn()} /></I18nProvider>)
}

it('keeps identical occurrences separate in one table and bulk selects valid visible rows only', async () => {
  const durable = new ReviewTestTransport()
  durable.record(preview(11)); const partial = preview(12)
  partial.rows.push({ ...partial.rows[0], payload: { ...partial.rows[0].payload, quantity: null } })
  durable.record(partial); setup(durable)
  const user = userEvent.setup()
  await waitFor(() => expect(screen.getAllByRole('row')).toHaveLength(4))
  expect(screen.getAllByRole('table')).toHaveLength(1)
  expect(screen.getAllByRole('button', { name: /^Провери позиция 1,/ })).toHaveLength(3)
  await user.click(screen.getByRole('button', { name: 'Избери валидните видими редове' }))
  const boxes = screen.getAllByRole('checkbox')
  expect(boxes.map(box => (box as HTMLInputElement).checked)).toEqual([true, true, false])
  expect(boxes[2]).toBeDisabled()
  await user.type(screen.getByLabelText('Търсене'), 'absent')
  expect(screen.getAllByRole('row')).toHaveLength(1)
})

it('persists two rapid edits from different source occurrences before the debounce and survives remount', async () => {
  const durable = new ReviewTestTransport(); durable.record(preview(11)); durable.record(preview(12))
  const view = setup(durable), user = userEvent.setup()
  fireEvent.change(await screen.findByLabelText('Номер на част'), { target: { value: '001-HUMAN-A' } })
  await user.click(screen.getByRole('button', { name: /PDF стр. 12$/ }))
  fireEvent.change(screen.getByLabelText('Номер на част'), { target: { value: '002-HUMAN-B' } })
  await waitFor(() => expect([11, 12].map(id => durable.previews.get(id)?.rows[0].payload.part_number)).toEqual(['001-HUMAN-A', '002-HUMAN-B']))
  view.unmount(); setup(durable)
  expect(await screen.findByLabelText('Номер на част')).toHaveValue('001-HUMAN-A')
  await user.click(screen.getByRole('button', { name: /PDF стр. 12$/ }))
  expect(screen.getByLabelText('Номер на част')).toHaveValue('002-HUMAN-B')
})

it('never marks an omitted invalid row confirmed if reload fails after a partial confirmation', async () => {
  const durable = new ReviewTestTransport(), p = preview(11)
  p.rows[0].warnings = []
  p.rows.push({ ...p.rows[0], payload: { ...p.rows[0].payload, position: '2', part_number: '002-QA' } })
  durable.record(p)
  let confirmed = false
  const submitted: Array<{ index: number }> = []
  vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const path = String(input)
    if (path.endsWith('/confirm')) { confirmed = true; submitted.push(...JSON.parse(String(init?.body)).rows); return json({}) }
    if (path.endsWith('/review-session') && confirmed) return json({ detail: 'QA reload failure' }, 503)
    return durable.handle(path, init) || json([])
  }))
  render(<I18nProvider><GuidedParts page={page} changed={vi.fn(async () => {})} onDirtyChange={vi.fn()} /></I18nProvider>)
  const user = userEvent.setup()
  await user.click(await screen.findByRole('button', { name: /^Провери позиция 2,/ }))
  fireEvent.change(screen.getByLabelText('Количество'), { target: { value: '' } })
  await waitFor(() => expect(durable.previews.get(11)?.rows[1].payload.quantity).toBeNull())
  await waitFor(() => expect(screen.getByRole('button', { name: 'Потвърди избраните части' })).toBeEnabled())
  await user.click(screen.getByRole('button', { name: 'Потвърди избраните части' }))
  await waitFor(() => expect(confirmed).toBe(true))
  expect(submitted.map(row => row.index)).toEqual([0])
  await waitFor(() => expect(screen.getAllByRole('row')[1]).toHaveTextContent('Потвърдени'))
  await waitFor(() => expect(screen.getByLabelText('Количество')).toBeEnabled())
  expect(screen.getAllByRole('row')[2]).toHaveTextContent('Нуждае се от проверка')
  expect(screen.getAllByRole('row')[2]).not.toHaveTextContent('Потвърдени')
})

it('retains unsaved human values after a stale version and blocks confirmation', async () => {
  const durable = new ReviewTestTransport(); durable.record(preview(11))
  const patch = vi.fn((_init?: RequestInit) => json({ detail: { code: 'catalog_reference_page_stale' } }, 409))
  setup(durable, patch)
  fireEvent.change(await screen.findByLabelText('Номер на част'), { target: { value: 'HUMAN-UNSAVED' } })
  await screen.findByText(/Конфликт с друга промяна/)
  expect(screen.getByLabelText('Номер на част')).toHaveValue('HUMAN-UNSAVED')
  expect(screen.getByRole('button', { name: 'Потвърди избраните части' })).toBeDisabled()
  expect(patch).toHaveBeenCalledTimes(1)
  expect(JSON.parse(String(patch.mock.calls[0][0]?.body)).expected_version).toBe(1)
  expect(durable.previews.get(11)?.rows[0].payload.part_number).toBe('001-QA')
  vi.spyOn(window, 'confirm').mockReturnValue(false)
  const user = userEvent.setup()
  await user.click(screen.getByRole('button', { name: 'Зареди текущия ред' }))
  expect(screen.getByLabelText('Номер на част')).toHaveValue('HUMAN-UNSAVED')
  vi.mocked(window.confirm).mockReturnValue(true)
  await user.click(screen.getByRole('button', { name: 'Зареди текущия ред' }))
  await waitFor(() => expect(screen.getByLabelText('Номер на част')).toHaveValue('001-QA'))
  expect(screen.getByRole('button', { name: 'Избери валидните видими редове' })).toBeEnabled()
})

it.each([false, true])('renews an expired preview without silently adopting concurrent versions (concurrent=%s)', async concurrent => {
  const durable = new ReviewTestTransport(), p = preview(11)
  p.rows[0].warnings = []
  p.rows.push({ ...p.rows[0], payload: { ...p.rows[0].payload, position: '2', part_number: '002-QA' } })
  durable.record(p)
  const confirmations: Record<string, unknown>[] = []
  let resumes = 0
  vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const path = String(input)
    if (path.endsWith('/review-session')) {
      resumes += 1
      const current = durable.previews.get(11)!
      current.token = resumes === 1 ? 'expired-actor-bound-preview' : 'fresh-actor-bound-preview'
      if (concurrent && resumes === 2) current.rows[0].candidate_version = 2
    }
    if (path.endsWith('/confirm')) { confirmations.push(JSON.parse(String(init?.body))); return json({}) }
    return durable.handle(path, init) || json([])
  }))
  render(<I18nProvider><GuidedParts page={page} changed={vi.fn(async () => {})} onDirtyChange={vi.fn()} /></I18nProvider>)
  const user = userEvent.setup()
  await waitFor(() => expect(screen.getByRole('button', { name: 'Потвърди избраните части' })).toBeEnabled())
  await user.click(screen.getByRole('button', { name: 'Потвърди избраните части' }))
  if (concurrent) {
    await screen.findByText(/Страницата е променена/)
    expect(confirmations).toHaveLength(0)
    expect(screen.getByRole('button', { name: 'Потвърди избраните части' })).toBeDisabled()
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    await user.click(screen.getByRole('button', { name: 'Зареди текущия ред' }))
    await waitFor(() => expect(screen.getByRole('button', { name: 'Избери валидните видими редове' })).toBeEnabled())
  } else {
    await waitFor(() => expect(confirmations).toHaveLength(1))
    expect(confirmations[0].token).toBe('fresh-actor-bound-preview')
    expect((confirmations[0].rows as Array<{ expected_version: number }>)[0].expected_version).toBe(1)
  }
})

it('has complete Bulgarian, English and Russian UX keys', () => {
  expect(Object.keys(catalogUxEn).sort()).toEqual(Object.keys(catalogUxBg).sort())
  expect(Object.keys(catalogUxRu).sort()).toEqual(Object.keys(catalogUxBg).sort())
})

it('resumes retained partial candidates after a failed retry without a fabricated confirmation token', async () => {
  const durable = new ReviewTestTransport(), p = durable.record(preview(11))
  p.rows[0].payload.quantity = null
  vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const path = String(input)
    if (path.endsWith('/review-session')) return json({ id: 1, selection_digest: 'qa', sources: [{
      id: 11, visual_page_id: 11, version: 2, fingerprint: 'qa', source: p.source, preview: null,
      processing_state: 'FAILED', review_state: 'NEEDS_REVIEW', attempts: [{ id: 2, state: 'FAILED' }],
      candidates: p.rows.map(row => ({ id: row.candidate_id, version: row.candidate_version, state: 'PENDING', part_id: null, values: row.payload, original: row, reason: null })),
    }] })
    return durable.handle(path, init) || json([])
  }))
  const view = render(<I18nProvider><GuidedParts page={page} changed={vi.fn(async () => {})} onDirtyChange={vi.fn()} /></I18nProvider>)
  expect(await screen.findByLabelText('Номер на част')).toHaveValue('001-QA')
  expect(screen.getByLabelText('Количество')).toHaveValue('')
  expect(screen.getByRole('checkbox')).toBeDisabled()
  expect(screen.getByRole('button', { name: 'Потвърди избраните части' })).toBeDisabled()
  fireEvent.change(screen.getByLabelText('Количество'), { target: { value: '2' } })
  await waitFor(() => expect(durable.previews.get(11)?.rows[0].payload.quantity).toBe('2'))
  view.unmount()
  render(<I18nProvider><GuidedParts page={page} changed={vi.fn(async () => {})} onDirtyChange={vi.fn()} /></I18nProvider>)
  expect(await screen.findByLabelText('Количество')).toHaveValue('2')
  expect(screen.getByRole('button', { name: 'Потвърди избраните части' })).toBeDisabled()
  expect(screen.getAllByRole('button', { name: 'Грешка — опитайте отново' }).every(button => !(button as HTMLButtonElement).disabled)).toBe(true)
})

it('creates the first empty page with a new assembly and keeps it after the asynchronous refresh', async () => {
  const writes: string[] = []
  const group = { id: 3, code: 'QA', name_bg: 'QA assembly', name_en: 'QA assembly', name_ru: 'QA assembly', part_count: 0, exploded_page_count: 0, spare_list_page_count: 0 }
  let created = false
  vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const path = String(input)
    if (init?.method === 'POST') {
      writes.push(path)
      if (path.endsWith('/groups')) return json(group)
      if (path.endsWith('/reference-pages')) { created = true; return json({ ...page, sources: [], scheme_count: 0, spare_list_count: 0 }) }
    }
    if (path.endsWith('/reference-pages')) return json(created ? [{ ...page, sources: [], scheme_count: 0, spare_list_count: 0 }] : [])
    return json([])
  }))
  const navigate = vi.fn(), changed = vi.fn(async () => {})
  const view = render(<I18nProvider><GuidedWorkspace revisionId={2} groups={[]} task="references" onNavigate={navigate} changed={changed} onDirtyChange={vi.fn()} /></I18nProvider>)
  const user = userEvent.setup()
  await user.type(screen.getByLabelText('Възел'), 'QA assembly')
  await user.click(screen.getByRole('button', { name: 'Добави възел' }))
  await waitFor(() => expect(changed).toHaveBeenCalled())
  view.rerender(<I18nProvider><GuidedWorkspace revisionId={2} groups={[group]} task="documents" onNavigate={navigate} changed={changed} onDirtyChange={vi.fn()} /></I18nProvider>)
  expect(await screen.findByRole('button', { name: '+ Добави схема' })).toBeVisible()
  expect(writes).toEqual(['/api/admin/catalog-builder/revisions/2/groups', '/api/admin/catalog-builder/assemblies/3/reference-pages'])
  expect(writes.some(path => path.endsWith('/sources'))).toBe(false)
})

it('highlights only bounded original evidence and applies PDF rotation', () => {
  const p = preview(11)
  expect(evidenceRegion(p, [10, 20, 30, 40])).toBeNull()
  p.page_geometry = { width: 200, height: 100, rotation_matrix: [0, 1, -1, 0, 200, 0] }
  expect(evidenceRegion(p, [10, 20, 30, 40])).toEqual({ left: '80%', top: '10%', width: expect.any(String), height: expect.any(String) })
  expect(evidenceRegion(p, [-10, 20, 30, 40])).toBeNull()
  expect(evidenceRegion(p, [10, 20, Number.NaN, 40])).toBeNull()
  expect(evidenceRegion(p, [30, 20, 10, 40])).toBeNull()
})
