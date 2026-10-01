import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, expect, it, vi } from 'vitest'
import { uploadApiFile } from '../../api'
import { I18nProvider } from '../../i18n'
import AnalysisProgress from './AnalysisProgress'
import CandidateSource from './CandidateSource'
import IngestReview from './IngestReview'
import RevisionHotspotEditor from './RevisionHotspotEditor'
import { ingestBg, ingestEn, ingestRu } from './ingestTranslations'
import type { Candidate } from './ingestTypes'
import { UploadTestTransport } from './uploadTestTransport'

const json = (value: unknown, status = 200) => new Response(JSON.stringify(value), { status, headers: { 'Content-Type': 'application/json' } })
afterEach(() => { cleanup(); vi.unstubAllGlobals(); vi.restoreAllMocks() })

it.each(['bg', 'en', 'ru'] as const)('explains an ambiguous table and shows source cells and alternatives in %s', async locale => {
  const texts = { bg: ingestBg, en: ingestEn, ru: ingestRu }[locale]
  const candidate: Candidate = { id: 1, source_key: 'qa', version: 1, kind: 'PAGE', state: 'NEEDS_REVIEW',
    page_number: null, artifact_id: 1, sha256: 'a'.repeat(64), confidence: .4, warnings: ['SCHEMA_AMBIGUOUS'],
    payload: { role: 'SPARE_PARTS_LIST' }, evidence: { tables: [{ headers: ['ID', 'Number', 'Type', 'Qty'], bbox: [30, 100, 500, 200],
      sample_cells: [['1', '51', 'Seal', '2']], schema: { state: 'NEEDS_REVIEW', score: 20, margin: 0,
        mapping: { '0': 'position', '1': 'part_number', '2': 'description', '3': 'quantity' }, alternatives: [
          { score: 20, mapping: { '0': 'part_number', '1': 'position', '2': 'description', '3': 'quantity' } },
        ] } }] } }
  render(<I18nProvider initialLocale={locale}><CandidateSource candidate={candidate} onClose={() => {}} /></I18nProvider>)
  expect(screen.getByRole('status')).toHaveTextContent(texts['ingest.schema.help'])
  expect(screen.getByText('Seal')).toBeVisible()
  expect(screen.getByText(texts['ingest.schema.ambiguous'])).toBeVisible()
  await userEvent.click(screen.getByText(texts['ingest.schema.alternatives']))
  expect(screen.getByText(new RegExp(`ID: ${texts['ingest.field.part_number']}`))).toBeVisible()
})

it('sends a PDF larger than the old limit as one binary File with progress and CSRF', async () => {
  vi.stubGlobal('XMLHttpRequest', UploadTestTransport)
  document.cookie = 'assetcore_csrf=qa-csrf'
  const file = new File([new Uint8Array(13 * 1024 * 1024)], 'qa.pdf', { type: 'application/pdf' })
  const progress = vi.fn()
  const transport = vi.fn(async (_input: RequestInfo | URL, options?: RequestInit) => {
    expect(options?.body).toBeInstanceOf(FormData)
    const form = options?.body as FormData
    expect(form.get('file')).toBeInstanceOf(File)
    expect((form.get('file') as File).size).toBe(file.size)
    expect((form.get('file') as File).name).toBe(file.name)
    expect(form.get('content_base64')).toBeNull()
    expect(new Headers(options?.headers).get('Content-Type')).toBeNull()
    expect(new Headers(options?.headers).get('X-CSRF-Token')).toBe('qa-csrf')
    return json({ id: 8 }, 201)
  })
  vi.stubGlobal('fetch', transport)
  expect(await uploadApiFile('/admin/catalog-builder/revisions/1/pdf', file, progress)).toEqual({ id: 8 })
  expect(transport).toHaveBeenCalledTimes(1)
  expect(progress.mock.calls.map(call => call[0])).toEqual([50, 100])
  document.cookie = 'assetcore_csrf=; max-age=0'
})

it('automatically resumes checkpoints and shows analysis failure with a retry', async () => {
  let run = { id: 1, status: 'RUNNING', processed_pages: 1, page_count: 3, counts: {}, states: {}, ocr_pages: 0 }
  let advances = 0
  vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
    const path = String(input)
    if (path.endsWith('/analyses')) return json([run])
    if (path.endsWith('/advance')) { advances++; run = { ...run, status: advances === 1 ? 'FAILED' : 'COMPLETED', processed_pages: advances === 1 ? 1 : 3 }; return json(run) }
    if (path.endsWith('/retry')) { run = { ...run, status: 'RUNNING' }; return json(run) }
    return json({})
  }))
  const done = vi.fn(async () => {})
  render(<I18nProvider><AnalysisProgress revisionId={2} refreshKey={0} onCompleted={done} /></I18nProvider>)
  expect(await screen.findByText(/Анализът е прекъснат след 1/)).toBeVisible()
  await userEvent.click(screen.getByRole('button', { name: 'Продължи анализа' }))
  expect(await screen.findByText(/Анализът приключи: 3/)).toBeVisible()
  expect(advances).toBe(2)
  await waitFor(() => expect(done).toHaveBeenCalledTimes(1))
})

it('edits a source row, accepts selected proposals, rejects/restores and keeps evidence visible', async () => {
  const user = userEvent.setup()
  const row = { id: 10, source_key: 'b'.repeat(64), kind: 'PART', version: 1, state: 'NEEDS_REVIEW', page_number: 2,
    confidence: .5, artifact_id: 8, sha256: 'a'.repeat(64), warnings: ['MISSING_PART_NUMBER'],
    payload: { group_key: 'g'.repeat(64), position: '13A', part_number: '', description: 'QA seal', quantity: '2' },
    evidence: { raw_text: '13A   QA seal   2', bbox: [50, 100, 500, 120] } }
  const writes: Array<Record<string, unknown>> = []
  const NativeURL = URL
  vi.stubGlobal('URL', class extends NativeURL { static createObjectURL = () => 'blob:qa'; static revokeObjectURL = vi.fn() })
  vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const path = String(input)
    const body = init?.body ? JSON.parse(String(init.body)) as Record<string, unknown> : {}
    if (path.endsWith('/analyses')) return json([{ id: 1, status: 'COMPLETED' }])
    if (path.includes('kind=GROUP')) return json({ items: [{ id: 1, source_key: 'g'.repeat(64), state: 'ACCEPTED', payload: { name: 'QA source group' } }], total: 1, next_after: null })
    if (path.includes('/candidates?')) return json({ items: [row], total: 1, next_after: null })
    if (path.endsWith('/preview')) return new Response(new Blob(['qa'], { type: 'image/png' }))
    if (path.endsWith('/review')) {
      writes.push(body); row.version++
      if (body.action === 'EDIT') Object.assign(row.payload, (body.edit as { part: object }).part)
      if (body.action === 'REJECT') row.state = 'REJECTED'
      if (body.action === 'RESTORE') row.state = 'NEEDS_REVIEW'
      return json(row)
    }
    if (path.endsWith('/bulk-review')) { writes.push(body); row.state = 'ACCEPTED'; return json({ count: 1 }) }
    return json({})
  }))
  render(<I18nProvider><IngestReview revisionId={2} kind="PART" onChanged={async () => {}} /></I18nProvider>)
  await user.click(await screen.findByRole('button', { name: 'Коригирай' }))
  await user.type(screen.getByLabelText('Номер на част'), 'QA-PART')
  await user.click(screen.getByRole('button', { name: 'Запази' }))
  await waitFor(() => expect(row.payload.part_number).toBe('QA-PART'))
  await user.click(screen.getByRole('button', { name: 'Оригинална страница и текст' }))
  await waitFor(() => expect(document.querySelector('.ingest-source > pre')).toBeVisible())
  expect(document.querySelector('.ingest-source > pre')?.textContent).toBe('13A   QA seal   2')
  await waitFor(() => expect(screen.getByRole('img', { name: 'Оригинална страница и текст' })).toHaveAttribute('src', 'blob:qa'))
  await user.click(screen.getByRole('button', { name: 'Отхвърли' }))
  await user.click(await screen.findByRole('button', { name: 'Върни за преглед' }))
  await user.click(await screen.findByLabelText('Избери 13A'))
  await user.click(screen.getByRole('button', { name: 'Приеми избраните' }))
  expect(writes.at(-1)).toMatchObject({ action: 'ACCEPT', items: [{ id: 10, expected_version: 4 }] })
})

function pointers() {
  const NativeURL = URL
  vi.stubGlobal('URL', class extends NativeURL { static createObjectURL = () => 'blob:scheme'; static revokeObjectURL = vi.fn() })
  vi.stubGlobal('PointerEvent', class extends MouseEvent {
    pointerId: number; pointerType: string
    constructor(type: string, init: PointerEventInit = {}) { super(type, init); this.pointerId = init.pointerId || 1; this.pointerType = init.pointerType || 'mouse' }
  })
  HTMLElement.prototype.setPointerCapture = vi.fn()
  HTMLElement.prototype.hasPointerCapture = vi.fn(() => false)
}

it.each(['mouse', 'touch'])('point mode clicks directly on the image and visibly creates the correct position (%s)', async pointerType => {
  pointers()
  const rows: Array<Record<string, unknown>> = []
  vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const path = String(input)
    if (path.endsWith('/exploded-pages')) return json([{ visual_page_id: 5, artifact_id: 8, page_number: 1 }])
    if (path.endsWith('/hotspot-coverage')) return json([{ position: '13A', part_count: 1, part_numbers: ['QA-PART'], hotspot_count: rows.length, state: rows.length ? 'UNVERIFIED' : 'NO_HOTSPOT' }])
    if (path.endsWith('/preview')) return new Response(new Blob(['qa'], { type: 'image/png' }))
    if (init?.method === 'POST') { const body = JSON.parse(String(init.body)); rows.push({ ...body, id: 1, version: 1, is_verified: false }); return json(rows[0], 201) }
    return json(rows)
  }))
  render(<I18nProvider><RevisionHotspotEditor assemblyId={7} editable simple /></I18nProvider>)
  await userEvent.click(await screen.findByRole('checkbox'))
  const image = await screen.findByRole('img', { name: 'Страница на разглобената схема' })
  const canvas = image.parentElement as HTMLElement
  vi.spyOn(canvas, 'getBoundingClientRect').mockReturnValue({ left: 0, top: 0, width: 100, height: 200 } as DOMRect)
  fireEvent.pointerDown(image, { pointerId: 4, pointerType, button: 0, clientX: 50, clientY: 100 })
  expect(within(canvas).getByRole('button', { name: 'Позиция 13A' })).toBeVisible()
  fireEvent.pointerUp(image, { pointerId: 4, pointerType, button: 0, clientX: 50, clientY: 100 })
  await waitFor(() => expect(rows).toHaveLength(1))
  expect(rows[0]).toMatchObject({ position: '13A', x: .485, y: .485, width: .03, height: .03 })
  expect(within(canvas).getByRole('button', { name: 'Позиция 13A' })).toBeVisible()
})

it('explains the no-position state on image clicks and does not POST a hotspot', async () => {
  pointers()
  const fetch = vi.fn(async (input: RequestInfo | URL, _init?: RequestInit) => {
    const path = String(input)
    if (path.endsWith('/exploded-pages')) return json([{ visual_page_id: 5, artifact_id: 8, page_number: 1 }])
    if (path.endsWith('/preview')) return new Response(new Blob(['qa'], { type: 'image/png' }))
    return json([])
  })
  vi.stubGlobal('fetch', fetch)
  render(<I18nProvider><RevisionHotspotEditor assemblyId={7} editable simple /></I18nProvider>)
  const image = await screen.findByRole('img', { name: 'Страница на разглобената схема' })
  fireEvent.pointerDown(image, { pointerId: 1, button: 0 })
  expect(screen.getByRole('alert')).toHaveTextContent('няма приети части/позиции')
  expect(fetch.mock.calls.every(call => call[1]?.method !== 'POST')).toBe(true)
})

it('has complete distinct BG/EN/RU ingestion text', () => {
  expect(Object.keys(ingestBg).sort()).toEqual(Object.keys(ingestEn).sort())
  expect(Object.keys(ingestBg).sort()).toEqual(Object.keys(ingestRu).sort())
  expect(ingestEn['ingest.noPositions']).not.toBe(ingestBg['ingest.noPositions'])
  expect(ingestRu['ingest.noPositions']).not.toBe(ingestBg['ingest.noPositions'])
})

it.each(['GROUP', 'PAGE'] as const)('corrects %s structure with an explicit source group relationship', async kind => {
  const groupKey = 'c'.repeat(64)
  const row = { id: 12, source_key: 'd'.repeat(64), kind, version: 3, state: 'PROPOSED', confidence: .8,
    page_number: 2, warnings: [], payload: { name: 'Source heading', role: 'AMBIGUOUS', group_key: '' }, evidence: {} }
  const writes: Array<Record<string, unknown>> = []
  vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const path = String(input)
    if (path.endsWith('/analyses')) return json([{ id: 1, status: 'COMPLETED' }])
    if (path.includes('kind=GROUP&limit')) return json({ items: [{ id: 11, source_key: groupKey, state: 'ACCEPTED', payload: { name: 'Accepted source heading' } }], next_after: null })
    if (path.includes('/candidates?')) return json({ items: [row], total: 1, next_after: null })
    if (path.endsWith('/review')) { writes.push(JSON.parse(String(init?.body))); return json(row) }
    return json({})
  }))
  render(<I18nProvider><IngestReview revisionId={2} kind={kind} onChanged={async () => {}} /></I18nProvider>)
  await userEvent.click(await screen.findByRole('button', { name: 'Коригирай' }))
  if (kind === 'GROUP') {
    const input = screen.getByLabelText('Име на групата')
    await userEvent.clear(input)
    await userEvent.type(input, 'Reviewed source heading')
    await userEvent.selectOptions(screen.getByLabelText(ingestBg['ingest.merge']), groupKey)
  } else {
    await userEvent.selectOptions(screen.getByLabelText('Група'), groupKey)
    await userEvent.selectOptions(screen.getByLabelText('Роля на страницата'), 'BOTH')
  }
  await userEvent.click(screen.getByRole('button', { name: 'Запази' }))
  expect(writes[0]).toMatchObject({ expected_version: 3, action: 'EDIT', edit: kind === 'GROUP'
    ? { name: 'Reviewed source heading', merge_into_key: groupKey }
    : { group_key: groupKey, role: 'BOTH' } })
})

it('requires a deliberate ambiguity choice and verifies only after accepting its location', async () => {
  const NativeURL = URL
  vi.stubGlobal('URL', class extends NativeURL { static createObjectURL = () => 'blob:qa'; static revokeObjectURL = vi.fn() })
  const row = { id: 15, source_key: 'e'.repeat(64), kind: 'HOTSPOT', version: 2, state: 'NEEDS_REVIEW', confidence: .6,
    page_number: 1, artifact_id: 8, warnings: [], evidence: {}, payload: { position: '13A', match: 'MULTIPLE_CANDIDATES', verified: false,
      locations: [0, 1].map(index => ({ page_number: 1, x: .1 + index * .4, y: .2, width: .03, height: .02 })) } }
  const writes: Array<Record<string, unknown>> = []
  vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const path = String(input)
    if (path.endsWith('/analyses')) return json([{ id: 1, status: 'COMPLETED' }])
    if (path.includes('kind=GROUP')) return json({ items: [], next_after: null })
    if (path.includes('/candidates?')) return json({ items: [row], total: 1, next_after: null })
    if (path.endsWith('/preview')) return new Response(new Blob(['qa'], { type: 'image/png' }))
    if (path.endsWith('/review')) {
      const body = JSON.parse(String(init?.body)); writes.push(body); row.version++
      if (body.action === 'ACCEPT') row.state = 'ACCEPTED'
      if (body.action === 'VERIFY') row.payload.verified = true
      return json(row)
    }
    return json({})
  }))
  render(<I18nProvider><IngestReview revisionId={2} kind="HOTSPOT" onChanged={async () => {}} /></I18nProvider>)
  expect(await screen.findByRole('button', { name: ingestBg['ingest.accept'] })).toBeDisabled()
  await userEvent.click(screen.getByRole('button', { name: ingestBg['ingest.source'] }))
  await userEvent.click(screen.getByLabelText(ingestBg['ingest.includeLocation']))
  await userEvent.selectOptions(screen.getByLabelText(ingestBg['ingest.location']), '1')
  await userEvent.click(screen.getByLabelText(ingestBg['ingest.includeLocation']))
  await userEvent.click(screen.getByRole('button', { name: ingestBg['ingest.chooseLocation'] }))
  expect(writes[0]).toMatchObject({ action: 'ACCEPT', expected_version: 2, locations: [1] })
  expect(row.payload.verified).toBe(false)
  await userEvent.click(await screen.findByRole('button', { name: ingestBg['ingest.verify'] }))
  expect(writes[1]).toMatchObject({ action: 'VERIFY', expected_version: 3 })
})
