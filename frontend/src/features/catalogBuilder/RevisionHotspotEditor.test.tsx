import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, expect, it, vi } from 'vitest'
import { I18nProvider } from '../../i18n'
import RevisionHotspotEditor from './RevisionHotspotEditor'

const json = (value: unknown, status = 200) => new Response(JSON.stringify(value),
  { status, headers: { 'Content-Type': 'application/json' } })
afterEach(() => { cleanup(); vi.unstubAllGlobals(); vi.restoreAllMocks() })

it('draws normalized draft geometry, verifies explicitly, invalidates on edit and separates pan gestures', async () => {
  const actor = userEvent.setup()
  const NativeURL = URL
  vi.stubGlobal('URL', class extends NativeURL {
    static createObjectURL = vi.fn(() => 'blob:builder-scheme')
    static revokeObjectURL = vi.fn()
  })
  vi.stubGlobal('PointerEvent', class extends MouseEvent {
    pointerId: number
    pointerType: string
    constructor(type: string, init: PointerEventInit = {}) {
      super(type, init)
      this.pointerId = init.pointerId || 0
      this.pointerType = init.pointerType || 'mouse'
    }
  })
  HTMLElement.prototype.setPointerCapture = vi.fn()
  HTMLElement.prototype.hasPointerCapture = vi.fn(() => false)
  let rows: Array<Record<string, unknown>> = []
  const writes: Array<{ path: string; method: string; body: Record<string, unknown> }> = []
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const path = String(input); const method = init?.method || 'GET'
    const body = init?.body ? JSON.parse(String(init.body)) as Record<string, unknown> : {}
    if (method !== 'GET') writes.push({ path, method, body })
    if (path.endsWith('/assemblies/7/exploded-pages')) return json([{ visual_page_id: 5, artifact_id: 8,
      artifact_title: 'QA', filename: 'qa.pdf', sha256: 'a'.repeat(64), page_number: 1,
      hotspot_count: rows.length, verified_hotspot_count: rows.filter(row => row.is_verified).length }])
    if (path.endsWith('/assemblies/7/hotspot-coverage')) return json([{ position: '12', part_count: 2,
      part_numbers: ['A', 'B'], hotspot_count: rows.length, verified_hotspot_count: rows.filter(row => row.is_verified).length,
      state: rows.some(row => row.is_verified) ? 'VERIFIED' : rows.length ? 'UNVERIFIED' : 'NO_HOTSPOT' }])
    if (path.endsWith('/visual-pages/5/hotspots') && method === 'GET') return json(rows)
    if (path.endsWith('/artifacts/8/pages/1/preview')) return new Response(new Uint8Array([137, 80, 78, 71]),
      { headers: { 'Content-Type': 'image/png' } })
    if (path.endsWith('/visual-pages/5/hotspots') && method === 'POST') {
      const row = { ...body, id: rows.length + 1, visual_page_id: 5, version: 1, is_verified: false,
        provenance: 'MANUAL_BUILDER' }
      rows = [...rows, row]; return json(row, 201)
    }
    if (path.endsWith('/hotspots/1/verify')) {
      rows = rows.map(row => row.id === 1 ? { ...row, is_verified: true, version: Number(row.version) + 1 } : row)
      return json(rows[0])
    }
    if (path.endsWith('/hotspots/1') && method === 'PATCH') {
      rows = rows.map(row => row.id === 1 ? { ...row, ...body, is_verified: false, version: Number(row.version) + 1 } : row)
      return json(rows[0])
    }
    if (path.includes('/hotspots/1?expected_version=') && method === 'DELETE') {
      rows = rows.filter(row => row.id !== 1)
      return new Response(null, { status: 204 })
    }
    return json({ detail: { code: 'unexpected' } }, 404)
  })
  vi.stubGlobal('fetch', fetchMock)
  render(<I18nProvider><RevisionHotspotEditor assemblyId={7} editable /></I18nProvider>)
  await waitFor(() => expect(fetchMock.mock.calls.some(call => String(call[0]).includes('/preview'))).toBe(true))
  expect(screen.getAllByText('Варианти: 2').length).toBeGreaterThan(0)
  expect(screen.getByText('A')).toBeInTheDocument()
  expect(screen.getByText('B')).toBeInTheDocument()
  const canvas = document.querySelector('.builder-scheme-canvas') as HTMLElement
  vi.spyOn(canvas, 'getBoundingClientRect').mockReturnValue({ left: 0, top: 0, width: 100, height: 100 } as DOMRect)
  await actor.click(screen.getByRole('button', { name: 'Рисуване' }))
  // A second touch changes this to a navigation gesture. Neither finger may
  // leave a savable draft, even when it moves after the other one lifts.
  fireEvent.pointerDown(canvas, { pointerId: 20, pointerType: 'touch', clientX: 10, clientY: 20 })
  fireEvent.pointerMove(canvas, { pointerId: 20, pointerType: 'touch', clientX: 40, clientY: 60 })
  fireEvent.pointerDown(canvas, { pointerId: 21, pointerType: 'touch', clientX: 50, clientY: 60 })
  fireEvent.pointerMove(canvas, { pointerId: 21, pointerType: 'touch', clientX: 80, clientY: 90 })
  fireEvent.pointerUp(canvas, { pointerId: 20, pointerType: 'touch' })
  fireEvent.pointerMove(canvas, { pointerId: 21, pointerType: 'touch', clientX: 90, clientY: 95 })
  fireEvent.pointerUp(canvas, { pointerId: 21, pointerType: 'touch' })
  expect(screen.queryByRole('button', { name: 'Запази' })).not.toBeInTheDocument()
  expect(writes).toHaveLength(0)
  fireEvent.pointerDown(canvas, { pointerId: 22, pointerType: 'touch', clientX: 10, clientY: 20 })
  fireEvent.pointerMove(canvas, { pointerId: 22, pointerType: 'touch', clientX: 40, clientY: 60 })
  fireEvent.pointerCancel(canvas, { pointerId: 22, pointerType: 'touch' })
  expect(screen.queryByRole('button', { name: 'Запази' })).not.toBeInTheDocument()
  fireEvent.pointerDown(canvas, { pointerId: 1, pointerType: 'touch', clientX: 10, clientY: 20 })
  fireEvent.pointerMove(canvas, { pointerId: 1, pointerType: 'touch', clientX: 40, clientY: 60 })
  fireEvent.pointerUp(canvas, { pointerId: 1, pointerType: 'touch', clientX: 40, clientY: 60 })
  await actor.click(screen.getByRole('button', { name: 'Запази' }))
  await waitFor(() => expect(rows).toHaveLength(1))
  const created = writes.find(item => item.method === 'POST' && item.path.endsWith('/hotspots'))?.body
  expect(created?.position).toBe('12')
  expect(Number(created?.x)).toBeCloseTo(.1)
  expect(Number(created?.y)).toBeCloseTo(.2)
  expect(Number(created?.width)).toBeCloseTo(.3)
  expect(Number(created?.height)).toBeCloseTo(.4)
  expect(rows[0].is_verified).toBe(false)
  await actor.click(screen.getByRole('button', { name: 'Провери' }))
  await waitFor(() => expect(rows[0].is_verified).toBe(true))
  const x = screen.getByLabelText('X') as HTMLInputElement
  fireEvent.change(x, { target: { value: '0.2' } })
  await actor.click(screen.getByRole('button', { name: 'Запази' }))
  await waitFor(() => expect(rows[0].is_verified).toBe(false))
  expect(writes.find(item => item.method === 'PATCH')?.body.expected_version).toBe(2)
  await actor.click(screen.getByRole('button', { name: 'Избор и преместване' }))
  const selected = screen.getByRole('button', { name: 'Позиция 12' })
  fireEvent.pointerDown(selected, { pointerId: 3, clientX: 30, clientY: 30 })
  fireEvent.pointerMove(canvas, { pointerId: 3, clientX: 40, clientY: 40 })
  fireEvent.pointerUp(canvas, { pointerId: 3, clientX: 40, clientY: 40 })
  await actor.click(screen.getByRole('button', { name: 'Запази' }))
  await waitFor(() => expect(Number(rows[0].x)).toBeCloseTo(.3))
  const handle = document.querySelector('.builder-hotspot.draft .builder-hotspot-handle') as HTMLElement
  fireEvent.pointerDown(handle, { pointerId: 4, clientX: 60, clientY: 70 })
  fireEvent.pointerMove(canvas, { pointerId: 4, clientX: 70, clientY: 80 })
  fireEvent.pointerUp(canvas, { pointerId: 4, clientX: 70, clientY: 80 })
  await actor.click(screen.getByRole('button', { name: 'Запази' }))
  await waitFor(() => expect(Number(rows[0].width)).toBeCloseTo(.4))
  await actor.click(screen.getByRole('button', { name: 'Преместване на изгледа' }))
  const count = writes.length
  fireEvent.pointerDown(canvas, { pointerId: 2, pointerType: 'touch', clientX: 10, clientY: 20 })
  fireEvent.pointerMove(canvas, { pointerId: 2, pointerType: 'touch', clientX: 60, clientY: 70 })
  fireEvent.pointerUp(canvas, { pointerId: 2, pointerType: 'touch', clientX: 60, clientY: 70 })
  const viewport = document.querySelector('.builder-scheme-viewport') as HTMLElement
  viewport.scrollLeft = 100; viewport.scrollTop = 80
  fireEvent.pointerDown(canvas, { pointerId: 5, pointerType: 'mouse', button: 0, clientX: 50, clientY: 50 })
  fireEvent.pointerMove(canvas, { pointerId: 5, pointerType: 'mouse', clientX: 30, clientY: 20 })
  fireEvent.pointerUp(canvas, { pointerId: 5, pointerType: 'mouse', clientX: 30, clientY: 20 })
  expect(viewport.scrollLeft).toBe(120)
  expect(viewport.scrollTop).toBe(110)
  expect(writes).toHaveLength(count)
  expect(writes.every(item => !item.path.includes('/catalog/diagrams'))).toBe(true)
  vi.stubGlobal('confirm', vi.fn(() => true))
  await actor.click(screen.getByRole('button', { name: 'Премахни' }))
  await waitFor(() => expect(rows).toHaveLength(0))
})
