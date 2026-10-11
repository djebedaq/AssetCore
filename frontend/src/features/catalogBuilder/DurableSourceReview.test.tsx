import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
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
  vi.stubGlobal('URL', class extends NativeURL { static createObjectURL = vi.fn(() => 'blob:qa-original'); static revokeObjectURL = vi.fn() })
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
  expect(screen.getByText(/Изисква проверка/)).toBeVisible()
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
