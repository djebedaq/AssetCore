import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, expect, it, vi } from 'vitest'
import { I18nProvider } from '../../i18n'
import DurableSourceReview from './DurableSourceReview'
import type { ReviewSession } from './guidedTypes'

const json = (value: unknown, status = 200) => new Response(JSON.stringify(value), { status, headers: { 'Content-Type': 'application/json' } })
const session: ReviewSession = { id: 1, selection_digest: 'qa-selection', sources: [{
  id: 1, visual_page_id: 11, version: 7, fingerprint: 'f'.repeat(64), processing_state: 'SUCCEEDED', review_state: 'NEEDS_REVIEW',
  source: { visual_page_id: 11, artifact_id: 5, page_number: 3, filename: 'qa-original.pdf' }, preview: null, candidates: [],
  attempts: [{ id: 2, state: 'SUCCEEDED', row_count: 0, error_code: null }],
}] }
afterEach(() => { cleanup(); vi.unstubAllGlobals(); vi.restoreAllMocks() })
function images() {
  const NativeURL = URL
  let count = 0
  vi.stubGlobal('URL', class extends NativeURL { static createObjectURL = vi.fn(() => count++ ? `blob:qa-original-${count}` : 'blob:qa-original'); static revokeObjectURL = vi.fn() })
}

const conflict = (id: number) => ({ id, version: 2, state: 'CONFLICT', part_id: null, reason: null,
  values: { position: String(id), part_number: `QA-${id}`, description: 'QA', quantity: 1 },
  original: { payload: { position: String(id), part_number: `QA-${id}`, description: 'QA', quantity: 1 } } })
const conflicts: ReviewSession = { ...session, sources: [
  { ...session.sources[0], candidates: [conflict(20), conflict(21)] },
  { ...session.sources[0], id: 2, visual_page_id: 12, version: 9, fingerprint: 'a'.repeat(64),
    source: { ...session.sources[0].source, visual_page_id: 12, page_number: 4 }, candidates: [] },
] }
const parts = [{ id: 101, position: '1', part_number: 'QA-CORRECTED', description: 'QA', quantity: 1 }]
function originalResponse(receipt = 'qa-receipt') {
  return new Response(new Uint8Array([137]), { headers: { 'Content-Type': 'image/png', 'X-Catalog-Review-Receipt': receipt } })
}

it('requires an inspected original and reason, and submits the exact durable version/fingerprint', async () => {
  images()
  let decision: Record<string, unknown> | undefined
  vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    if (String(input).endsWith('/review-original')) return new Response(new Uint8Array([137]), { headers: { 'Content-Type': 'image/png', 'X-Catalog-Review-Receipt': 'qa-receipt' } })
    decision = JSON.parse(String(init?.body)); return json({ review_state: 'VERIFIED' })
  }))
  const reload = vi.fn(async () => {})
  render(<I18nProvider><DurableSourceReview session={session} reload={reload} parts={[]} busy={false} /></I18nProvider>)
  const user = userEvent.setup()
  expect(screen.getByText(/Нуждае се от проверка/)).toBeVisible()
  await user.click(screen.getByRole('button', { name: 'Покажи оригинала' }))
  const verify = screen.getByRole('button', { name: 'Потвърди проверения източник' })
  expect(verify).toBeDisabled()
  fireEvent.load(await screen.findByRole('img', { name: 'PDF страница 3' }))
  await user.type(screen.getByRole('textbox'), 'QA checked every applicable part')
  await user.click(screen.getByRole('checkbox'))
  await user.click(verify)
  await waitFor(() => expect(reload).toHaveBeenCalledOnce())
  expect(decision).toEqual({ expected_version: 7, fingerprint: 'f'.repeat(64), inspection_token: 'qa-receipt',
    reason: 'QA checked every applicable part', manual_transcription: true })
  expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:qa-original')
})

it('does not allow manual attestation to hide an unresolved candidate', async () => {
  images()
  const unresolved: ReviewSession = { ...session, sources: [{ ...session.sources[0], candidates: [{
    id: 20, version: 1, state: 'PENDING', part_id: null, reason: null,
    values: { position: '1', part_number: 'QA-1', description: 'QA', quantity: 1 },
    original: { payload: { position: '1', part_number: 'QA-1', description: 'QA', quantity: 1 } },
  }] }] }
  vi.stubGlobal('fetch', vi.fn(async () => new Response(new Uint8Array([137]), { headers: { 'Content-Type': 'image/png', 'X-Catalog-Review-Receipt': 'qa' } })))
  render(<I18nProvider><DurableSourceReview session={unresolved} reload={vi.fn(async () => {})} parts={[]} busy={false} /></I18nProvider>)
  const user = userEvent.setup()
  await user.click(screen.getByRole('button', { name: 'Покажи оригинала' }))
  fireEvent.load(await screen.findByRole('img'))
  await user.type(screen.getByRole('textbox'), 'QA attempted manual override')
  await user.click(screen.getByRole('checkbox'))
  expect(screen.getByRole('button', { name: 'Потвърди проверения източник' })).toBeDisabled()
})

it('shows a stale approval error and retains the source for a new inspection', async () => {
  images()
  const reload = vi.fn(async () => {})
  vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => String(input).endsWith('/review-original')
    ? new Response(new Uint8Array([137]), { headers: { 'Content-Type': 'image/png', 'X-Catalog-Review-Receipt': 'qa' } })
    : json({ detail: { code: 'catalog_reference_page_stale' } }, 409)))
  render(<I18nProvider><DurableSourceReview session={session} reload={reload} parts={[]} busy={false} /></I18nProvider>)
  const user = userEvent.setup()
  await user.click(screen.getByRole('button', { name: 'Покажи оригинала' }))
  fireEvent.load(await screen.findByRole('img'))
  await user.type(screen.getByRole('textbox'), 'QA compared the original')
  await user.click(screen.getByRole('button', { name: 'Потвърди проверения източник' }))
  expect(await screen.findByRole('alert')).toHaveTextContent('Страницата е променена')
  expect(reload).not.toHaveBeenCalled()
  expect(screen.getByRole('button', { name: 'Покажи оригинала' })).toBeEnabled()
})

it.each(['reason', 'manual', 'link', 'all'])('guards a source switch with unconfirmed %s, preserves on cancel and clears on accept', async field => {
  images()
  const confirm = vi.spyOn(window, 'confirm').mockReturnValue(false)
  const decisions: unknown[] = []
  let finishInspection: (response: Response) => void = () => {}
  const fetch = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    if (String(input).endsWith('/11/review-original')) return originalResponse('first-receipt')
    if (String(input).endsWith('/12/review-original')) return new Promise<Response>(resolve => { finishInspection = resolve })
    decisions.push(JSON.parse(String(init?.body))); return json({ review_state: 'VERIFIED' })
  })
  vi.stubGlobal('fetch', fetch)
  const dirty = vi.fn()
  render(<I18nProvider><DurableSourceReview session={conflicts} reload={vi.fn(async () => {})} parts={parts} busy={false} onDirtyChange={dirty} /></I18nProvider>)
  const user = userEvent.setup()
  await user.click(screen.getAllByRole('button', { name: 'Покажи оригинала' })[0])
  fireEvent.load(await screen.findByRole('img', { name: 'PDF страница 3' }))
  if (field === 'reason' || field === 'all') await user.type(screen.getByRole('textbox'), 'QA pending original inspection')
  if (field === 'manual' || field === 'all') await user.click(screen.getByRole('checkbox'))
  if (field === 'link' || field === 'all') await user.selectOptions(screen.getAllByRole('combobox')[0], '101')
  expect(dirty).toHaveBeenLastCalledWith(true)
  await user.click(screen.getAllByRole('button', { name: 'Покажи оригинала' })[1])
  expect(confirm).toHaveBeenCalledOnce()
  expect(confirm.mock.calls[0][0]).toContain('ще бъдат изчистени')
  expect(fetch).toHaveBeenCalledOnce()
  expect(screen.getByRole('img', { name: 'PDF страница 3' })).toBeVisible()
  expect(URL.revokeObjectURL).not.toHaveBeenCalled()
  expect(screen.getByRole('textbox')).toHaveValue(field === 'reason' || field === 'all' ? 'QA pending original inspection' : '')
  expect(screen.getByRole('checkbox')).toHaveProperty('checked', field === 'manual' || field === 'all')
  expect(screen.getAllByRole('combobox')[0]).toHaveValue(field === 'link' || field === 'all' ? '101' : '')
  confirm.mockReturnValue(true)
  await user.click(screen.getAllByRole('button', { name: 'Покажи оригинала' })[1])
  expect(fetch).toHaveBeenCalledTimes(2)
  expect(screen.queryByRole('img')).not.toBeInTheDocument()
  expect(screen.getByRole('textbox')).toHaveValue('')
  expect(screen.getByRole('checkbox')).not.toBeChecked()
  expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:qa-original')
  await user.type(screen.getByRole('textbox'), 'QA second exact original')
  finishInspection(originalResponse('second-receipt'))
  const image = await screen.findByRole('img', { name: 'PDF страница 4' })
  const verify = screen.getByRole('button', { name: 'Потвърди проверения източник' })
  expect(verify).toBeDisabled() // Loading the old image cannot attest the new source.
  fireEvent.load(image)
  await user.click(verify)
  await waitFor(() => expect(decisions).toEqual([{ expected_version: 9, fingerprint: 'a'.repeat(64),
    inspection_token: 'second-receipt', reason: 'QA second exact original', manual_transcription: false }]))
  expect(dirty).toHaveBeenLastCalledWith(false)
})

it('never shares a LINK_EXISTING choice between conflicting candidates or physical sources', async () => {
  images()
  vi.spyOn(window, 'confirm').mockReturnValue(true)
  vi.stubGlobal('fetch', vi.fn(async () => originalResponse()))
  const twoSources = { ...conflicts, sources: [conflicts.sources[0], { ...conflicts.sources[1], candidates: [conflict(22)] }] }
  render(<I18nProvider><DurableSourceReview session={twoSources} reload={vi.fn(async () => {})} parts={parts} busy={false} /></I18nProvider>)
  const user = userEvent.setup()
  await user.click(screen.getAllByRole('button', { name: 'Покажи оригинала' })[0])
  await user.type(screen.getByRole('textbox'), 'QA pending conflict resolution')
  const selects = screen.getAllByRole('combobox')
  await user.selectOptions(selects[0], '101')
  expect(selects[1]).toHaveValue('')
  expect(within(screen.getAllByRole('alert')[1]).getByRole('button', { name: 'Свържи с вече поправена част' })).toBeDisabled()
  await user.selectOptions(selects[1], '101')
  expect(selects[0]).toHaveValue('')
  expect(selects[1]).toHaveValue('101')
  await user.click(screen.getAllByRole('button', { name: 'Покажи оригинала' })[1])
  await screen.findByRole('img', { name: 'PDF страница 4' })
  expect(screen.getByRole('combobox')).toHaveValue('')
  await user.type(screen.getByRole('textbox'), 'QA second source conflict')
  expect(screen.getByRole('button', { name: 'Свържи с вече поправена част' })).toBeDisabled()
  await user.click(screen.getAllByRole('button', { name: 'Покажи оригинала' })[0])
  await screen.findByRole('img', { name: 'PDF страница 3' })
  expect(screen.getAllByRole('combobox').map(select => (select as HTMLSelectElement).value)).toEqual(['', ''])
})

it('keeps approval blocked if inspecting the newly selected source fails, without reusing the old receipt', async () => {
  images()
  vi.spyOn(window, 'confirm').mockReturnValue(true)
  const fetch = vi.fn(async (input: RequestInfo | URL) => String(input).endsWith('/11/review-original')
    ? originalResponse('old-receipt') : json({ detail: { code: 'catalog_source_inspection_required' } }, 422))
  vi.stubGlobal('fetch', fetch)
  render(<I18nProvider><DurableSourceReview session={conflicts} reload={vi.fn(async () => {})} parts={parts} busy={false} /></I18nProvider>)
  const user = userEvent.setup()
  await user.click(screen.getAllByRole('button', { name: 'Покажи оригинала' })[0])
  fireEvent.load(await screen.findByRole('img'))
  await user.type(screen.getByRole('textbox'), 'QA first inspected original')
  await user.click(screen.getByRole('checkbox'))
  await user.selectOptions(screen.getAllByRole('combobox')[0], '101')
  await user.click(screen.getAllByRole('button', { name: 'Покажи оригинала' })[1])
  await screen.findByRole('alert')
  expect(screen.queryByRole('img')).not.toBeInTheDocument()
  expect(screen.getByRole('textbox')).toHaveValue('')
  expect(screen.getByRole('checkbox')).not.toBeChecked()
  await user.type(screen.getByRole('textbox'), 'QA cannot attest without inspection')
  expect(screen.getByRole('button', { name: 'Потвърди проверения източник' })).toBeDisabled()
  expect(fetch).toHaveBeenCalledTimes(2)
})

it.each(['candidate', 'source', 'fingerprint'])('does not reuse a link after the %s version changes', async changed => {
  images()
  vi.stubGlobal('fetch', vi.fn(async () => originalResponse()))
  const view = (data: ReviewSession) => <I18nProvider><DurableSourceReview session={data} reload={vi.fn(async () => {})} parts={parts} busy={false} /></I18nProvider>
  const { rerender } = render(view(conflicts))
  const user = userEvent.setup()
  await user.click(screen.getAllByRole('button', { name: 'Покажи оригинала' })[0])
  await user.type(screen.getByRole('textbox'), 'QA checked this exact candidate')
  await user.selectOptions(screen.getAllByRole('combobox')[0], '101')
  const source = conflicts.sources[0]
  rerender(view({ ...conflicts, sources: [{ ...source,
    version: changed === 'source' ? source.version + 1 : source.version,
    fingerprint: changed === 'fingerprint' ? 'b'.repeat(64) : source.fingerprint,
    candidates: source.candidates.map((candidate, index) => ({ ...candidate, version: candidate.version + (changed === 'candidate' && index === 0 ? 1 : 0) })),
  }, conflicts.sources[1]] }))
  expect(screen.getAllByRole('combobox')[0]).toHaveValue('')
  expect(within(screen.getAllByRole('alert')[0]).getByRole('button', { name: 'Свържи с вече поправена част' })).toBeDisabled()
})

it('submits only the explicitly selected candidate link and clears it after successful resolution', async () => {
  images()
  let decision: Record<string, unknown> | undefined
  vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    if (String(input).endsWith('/review-original')) return originalResponse()
    expect(String(input)).toContain('/extraction-candidates/21')
    decision = JSON.parse(String(init?.body)); return json({ state: 'CONFIRMED' })
  }))
  const reload = vi.fn(async () => {})
  render(<I18nProvider><DurableSourceReview session={conflicts} reload={reload} parts={parts} busy={false} /></I18nProvider>)
  const user = userEvent.setup()
  await user.click(screen.getAllByRole('button', { name: 'Покажи оригинала' })[0])
  fireEvent.load(await screen.findByRole('img'))
  await user.type(screen.getByRole('textbox'), 'QA original matches corrected part')
  await user.selectOptions(screen.getAllByRole('combobox')[1], '101')
  await user.click(within(screen.getAllByRole('alert')[1]).getByRole('button', { name: 'Свържи с вече поправена част' }))
  await waitFor(() => expect(reload).toHaveBeenCalledOnce())
  expect(decision).toEqual({ expected_version: 2, action: 'LINK_EXISTING', reason: 'QA original matches corrected part', part_id: 101 })
  expect(screen.getAllByRole('combobox').map(select => (select as HTMLSelectElement).value)).toEqual(['', ''])
  expect(screen.queryByRole('img')).not.toBeInTheDocument()
})
