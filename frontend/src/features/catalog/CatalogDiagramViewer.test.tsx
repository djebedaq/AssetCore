import { useState } from 'react'
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { I18nProvider } from '../../i18n'
import { setSessionUser } from '../../permissions'
import type { UserSession } from '../../types'
import { CatalogDiagramViewer, type DiagramFocus } from './CatalogDiagramViewer'
import { DIAGRAM_TAP_MOVEMENT_THRESHOLD_PX } from './catalogInteraction'
import type { CatalogDiagram, CatalogPart, PositionHotspot } from './catalogTypes'

// Synthetic HTTP/geometry fixtures only: no catalog data or database is changed.
function part(position: string, id: number): CatalogPart {
  return {
    id, position, source_record_key: `test-only-${id}`, source_id: 'test-only-diagram',
    source_row_index: id, family: 'TEST_ONLY', brand: 'Test fixture', model: 'Test fixture',
    assembly: 'TEST_ONLY', part_number: `TEST-${id}`, order_part_number: `TEST-${id}`,
    description: `Test part ${id}`, source_description: `Test part ${id}`,
    description_en: `Test part ${id}`, description_bg: `Тестова част ${id}`,
    quantity_raw: '1', source_document: 'TEST_ONLY.pdf', source_page: 1,
    source_version: 'TEST_ONLY', source_document_sha256: 'a'.repeat(64),
    verification_status: 'VERIFIED', source_anomaly_codes: [], is_verified: true,
    translation_version: 'TEST_ONLY', translation_qa_status: 'VERIFIED',
  }
}

const hotspots: PositionHotspot[] = [
  { id: 101, hotspot_key: 'test-only-1', position: '1', diagram_id: 901, page_number: 1,
    x: 0.25, y: 0.25, width: 0.25, height: 0.25, is_verified: true,
    provenance: 'AUTO_MATCHED', variants: [part('1', 11), part('1', 12)] },
  { id: 109, hotspot_key: 'test-only-9', position: '9', diagram_id: 901, page_number: 1,
    x: 0.375, y: 0.25, width: 0.25, height: 0.25, is_verified: true,
    provenance: 'AUTO_MATCHED', variants: [part('9', 91)] },
]
const diagram: CatalogDiagram = {
  id: 901, source_id: 'test-only-diagram', page_number: 1, title: 'Test-only overlap diagram',
  source_pdf_sha256: 'b'.repeat(64), render_version: 'TEST_ONLY', technical_document_id: 901,
  preview_endpoint: '/technical-library/901/preview?page=1', download_endpoint: '/technical-library/901/download',
}
const json = (value: unknown) => new Response(JSON.stringify(value), { headers: { 'Content-Type': 'application/json' } })
const button = (position: string) => screen.getByRole('button', { name: new RegExp(`Поз. ${position}:`) })
const canvas = () => document.querySelector<HTMLDivElement>('.catalog-v2-diagram-canvas')!
const viewport = () => document.querySelector<HTMLDivElement>('.catalog-v2-diagram-viewport')!
function rect(left: number, top: number, width: number, height: number): DOMRect {
  return { x: left, y: top, left, top, width, height, right: left + width, bottom: top + height, toJSON: () => ({}) }
}
function point(x: number, y = 0.375) {
  const bounds = canvas().getBoundingClientRect()
  return { clientX: bounds.left + x * bounds.width, clientY: bounds.top + y * bounds.height }
}
function tap(target: HTMLElement, pointerType: 'touch' | 'mouse' | 'pen', x: number) {
  const event = { pointerId: 1, pointerType, ...point(x) }
  fireEvent.pointerDown(target, event)
  fireEvent.pointerUp(viewport(), event)
  // Native pointer clicks must not also take the keyboard/synthetic-click path.
  fireEvent.click(target, { detail: 1, ...point(x) })
}

beforeEach(() => {
  localStorage.clear()
  vi.stubGlobal('innerWidth', 390)
  vi.stubGlobal('innerHeight', 600)
  class TestPointerEvent extends MouseEvent {
    readonly pointerId: number
    readonly pointerType: string
    constructor(type: string, init: PointerEventInit = {}) {
      super(type, init)
      this.pointerId = init.pointerId ?? 0
      this.pointerType = init.pointerType ?? ''
    }
  }
  vi.stubGlobal('PointerEvent', TestPointerEvent)
  const NativeURL = URL
  class TestURL extends NativeURL {
    static createObjectURL = vi.fn(() => 'blob:test-only-overlap')
    static revokeObjectURL = vi.fn()
  }
  vi.stubGlobal('URL', TestURL)
  const originalBounds = HTMLElement.prototype.getBoundingClientRect
  vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockImplementation(function (this: HTMLElement) {
    if (this.classList.contains('catalog-v2-diagram-canvas')) {
      const scale = Number.parseFloat(this.style.width) / 100
      return rect(15 - viewport().scrollLeft, 100 - viewport().scrollTop, 360 * scale, 480 * scale)
    }
    return originalBounds.call(this)
  })
})
afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.unstubAllGlobals() })

async function setup(reversed = false, manage = false) {
  setSessionUser({ role: manage ? 'administrator' : 'mechanic', permissions: manage ? ['parts.view', 'parts.manage'] : ['parts.view'] } as UserSession)
  const items = reversed ? [...hotspots].reverse() : hotspots
  const select = vi.fn()
  const open = vi.fn()
  const changed = vi.fn()
  const request = vi.fn((input: RequestInfo | URL, init: RequestInit = {}) => {
    const path = String(input)
    if (path === `/api${diagram.preview_endpoint}` && !init.method) return Promise.resolve(new Response(new Blob(['test-only-preview'], { type: 'image/png' })))
    if (path === '/api/catalog/v2/diagrams/901/hotspots?machine_id=9&verified_only=false' && !init.method) return Promise.resolve(json(items))
    if (path === '/api/catalog/v2/hotspots/109' && init.method === 'PATCH') return Promise.resolve(json({ id: 109, ...JSON.parse(String(init.body)), provenance: 'MANUALLY_CONFIRMED' }))
    throw new Error(`Unexpected test request: ${path}`)
  })
  vi.stubGlobal('fetch', request)
  function Harness({ focus = null }: { focus?: DiagramFocus }) {
    const [selected, setSelected] = useState<string | null>(null)
    return <I18nProvider initialLocale="bg"><CatalogDiagramViewer
      machineId={9} diagram={diagram} hotspots={items} selectedPosition={selected} focus={focus} kitPositions={new Set()}
      onSelectPosition={position => { select(position); setSelected(position) }}
      onOpenPosition={(position, variants, trigger) => { open(position, variants, trigger); setSelected(position) }}
      onHotspotsChange={changed}
    /></I18nProvider>
  }
  const view = render(<Harness />)
  await screen.findByRole('img', { name: diagram.title })
  return { user: userEvent.setup(), select, open, changed, request, focus: (position: string) => view.rerender(<Harness focus={{ position, nonce: 1 }} />) }
}
function expectPreviewOnly(request: Awaited<ReturnType<typeof setup>>['request']) {
  expect(request.mock.calls.map(([path, init]) => [path, init?.method || 'GET'])).toEqual([
    [`/api${diagram.preview_endpoint}`, 'GET'],
  ])
}

describe('NEW-02 overlapping hotspots on a 390 x 600 viewport', () => {
  it.each([false, true])('preserves geometric two-tap selection, variants and focus (reversed order: %s)', async reversed => {
    const { select, open, request } = await setup(reversed)
    expect([window.innerWidth, window.innerHeight]).toEqual([390, 600])
    expect(canvas().getBoundingClientRect()).toMatchObject({ left: 15, top: 100, width: 360, height: 480 })
    expect([...canvas().querySelectorAll<HTMLButtonElement>('button')].map(item => item.dataset.position)).toEqual(reversed ? ['9', '1'] : ['1', '9'])
    expect(button('1')).toHaveStyle({ left: '25%', width: '25%' })
    expect(button('9')).toHaveStyle({ left: '37.5%', width: '25%' })

    // DOM hit-testing reports 9, but the point is in BOTH rectangles, nearer 1.
    tap(button('9'), 'touch', 0.4)
    expect(select).toHaveBeenLastCalledWith('1')
    expect(button('1')).toHaveClass('selected')
    expect(button('9')).not.toHaveClass('selected')
    expect(button('1')).toHaveFocus()
    expect(open).not.toHaveBeenCalled()
    tap(button('9'), 'touch', 0.4)
    expect(open).toHaveBeenCalledExactlyOnceWith('1', hotspots[0].variants, button('1'))

    // A selected/focused 1 may stack above 9; it must not bias geometric resolution.
    tap(button('1'), 'touch', 0.475)
    expect(select).toHaveBeenLastCalledWith('9')
    expect(button('9')).toHaveClass('selected')
    expect(button('1')).not.toHaveClass('selected')
    expect(button('9')).toHaveFocus()
    expect(open).toHaveBeenCalledTimes(1)
    tap(button('1'), 'touch', 0.475)
    expect(open).toHaveBeenLastCalledWith('9', hotspots[1].variants, button('9'))
    expect(open).toHaveBeenCalledTimes(2)
    expectPreviewOnly(request)
  })

  it.each([
    { pointerType: 'mouse' as const, reversed: false, zoom: 100 },
    { pointerType: 'mouse' as const, reversed: true, zoom: 100 },
    { pointerType: 'mouse' as const, reversed: false, zoom: 150 },
    { pointerType: 'mouse' as const, reversed: true, zoom: 150 },
    { pointerType: 'pen' as const, reversed: false, zoom: 100 },
    { pointerType: 'pen' as const, reversed: true, zoom: 150 },
  ])('opens the resolved variants on $pointerType at $zoom% (reversed: $reversed)', async ({ pointerType, reversed, zoom }) => {
    const { user, select, open, request } = await setup(reversed)
    if (zoom === 150) {
      await user.click(screen.getByRole('button', { name: 'Увеличи схемата' }))
      await user.click(screen.getByRole('button', { name: 'Увеличи схемата' }))
      viewport().scrollLeft = 35
      viewport().scrollTop = 40
    }
    expect(canvas().getBoundingClientRect().width).toBe(360 * zoom / 100)
    tap(button('9'), pointerType, 0.4)
    expect(open).toHaveBeenCalledExactlyOnceWith('1', hotspots[0].variants, button('1'))
    tap(button('1'), pointerType, 0.475)
    expect(open).toHaveBeenLastCalledWith('9', hotspots[1].variants, button('9'))
    expect(open).toHaveBeenCalledTimes(2)
    expect(select).not.toHaveBeenCalled()
    expect(button('9')).toHaveClass('selected')
    expectPreviewOnly(request)
  })

  it.each(['pan', 'pinch', 'cancel'] as const)('does not activate either overlapping hotspot after %s', async gesture => {
    const { select, open, request } = await setup()
    const event = { pointerId: 1, pointerType: 'touch', ...point(0.4) }
    fireEvent.pointerDown(button('9'), event)
    if (gesture === 'pan') {
      expect(DIAGRAM_TAP_MOVEMENT_THRESHOLD_PX).toBe(8)
      fireEvent.pointerMove(viewport(), { ...event, clientX: event.clientX + DIAGRAM_TAP_MOVEMENT_THRESHOLD_PX })
      expect(viewport().scrollLeft).toBe(-DIAGRAM_TAP_MOVEMENT_THRESHOLD_PX)
    } else if (gesture === 'pinch') {
      fireEvent.pointerDown(button('1'), { ...event, pointerId: 2, clientX: event.clientX + 50 })
      fireEvent.pointerMove(viewport(), { ...event, pointerId: 2, clientX: event.clientX + 60 })
      fireEvent.pointerMove(viewport(), { ...event, pointerId: 2, clientX: event.clientX + 72 })
      expect(canvas()).toHaveStyle({ width: '120%' })
      fireEvent.pointerUp(viewport(), { ...event, pointerId: 2 })
    }
    if (gesture === 'cancel') fireEvent.pointerCancel(viewport(), event)
    else fireEvent.pointerUp(viewport(), event)
    fireEvent.click(button('9'), { detail: 1 })
    expect(select).not.toHaveBeenCalled()
    expect(open).not.toHaveBeenCalled()
    expect(button('1')).not.toHaveClass('selected')
    expect(button('9')).not.toHaveClass('selected')
    expectPreviewOnly(request)
  })

  it('keeps keyboard focus, Enter/Space and detail=0 activation independent of pointer geometry', async () => {
    const { user, open, request } = await setup()
    button('1').focus()
    await user.keyboard('{Enter}')
    expect(open).toHaveBeenCalledExactlyOnceWith('1', hotspots[0].variants, button('1'))
    await user.tab()
    expect(button('9')).toHaveFocus()
    await user.keyboard(' ')
    expect(open).toHaveBeenLastCalledWith('9', hotspots[1].variants, button('9'))
    fireEvent.click(button('1'), { detail: 0, ...point(0.475) })
    expect(open).toHaveBeenLastCalledWith('1', hotspots[0].variants, button('1'))
    expect(open).toHaveBeenCalledTimes(3)
    expect(button('1')).toHaveAttribute('title', 'Поз. 1 · Test part 11 / Тестова част 11')
    expect(button('1')).toHaveAccessibleName('Поз. 1: Test part 11 / Тестова част 11')
    expectPreviewOnly(request)
  })

  it('retains zoom limits, fit, fullscreen and focus-to-position', async () => {
    const { user, focus, open, select } = await setup()
    await user.click(screen.getByRole('button', { name: 'Намали схемата' }))
    expect(canvas()).toHaveStyle({ width: '75%' })
    expect(screen.getByRole('button', { name: 'Намали схемата' })).toBeDisabled()
    for (let index = 0; index < 9; index += 1) await user.click(screen.getByRole('button', { name: 'Увеличи схемата' }))
    expect(canvas()).toHaveStyle({ width: '300%' })
    expect(screen.getByRole('button', { name: 'Увеличи схемата' })).toBeDisabled()
    await user.click(screen.getByRole('button', { name: 'Побери схемата' }))
    expect(canvas()).toHaveStyle({ width: '100%' })
    const fullscreen = vi.fn().mockResolvedValue(undefined)
    Object.defineProperty(viewport(), 'requestFullscreen', { configurable: true, value: fullscreen })
    await user.click(screen.getByRole('button', { name: 'Цял екран' }))
    expect(fullscreen).toHaveBeenCalledTimes(1)
    const scroll = vi.fn()
    Object.defineProperty(viewport(), 'scrollTo', { configurable: true, value: scroll })
    focus('9')
    await waitFor(() => expect(button('9')).toHaveFocus())
    expect(canvas()).toHaveStyle({ width: '140%' })
    expect(scroll).toHaveBeenCalledWith(expect.objectContaining({ behavior: 'smooth' }))
    expect(open).not.toHaveBeenCalled()
    expect(select).not.toHaveBeenCalled()
  })

  it('keeps QA selection, drag, resize, verified flag, reason and PATCH bound to the actual edited occurrence', async () => {
    const { user, select, open, request, changed } = await setup(false, true)
    await user.click(screen.getByRole('button', { name: 'QA на областите' }))
    await waitFor(() => expect(request.mock.calls).toHaveLength(2))
    const event = { pointerId: 1, pointerType: 'mouse', ...point(0.4) }
    const bounds = canvas().getBoundingClientRect()
    fireEvent.pointerDown(button('9'), event)
    fireEvent.pointerMove(viewport(), { ...event, clientX: event.clientX + bounds.width / 16, clientY: event.clientY + bounds.height / 16 })
    fireEvent.pointerUp(viewport(), event)
    const editor = within(screen.getByRole('region', { name: 'Редактор на проверена позиционна област' }))
    expect(editor.getByText('Поз. 9')).toBeVisible()
    expect(editor.getByLabelText('x')).toHaveValue(0.4375)
    expect(editor.getByLabelText('y')).toHaveValue(0.3125)
    fireEvent.pointerDown(button('9').querySelector('.catalog-v2-resize-handle')!, event)
    fireEvent.pointerMove(viewport(), { ...event, clientX: event.clientX + bounds.width / 16, clientY: event.clientY + bounds.height / 16 })
    fireEvent.pointerUp(viewport(), event)
    expect(editor.getByLabelText('width')).toHaveValue(0.3125)
    expect(editor.getByLabelText('height')).toHaveValue(0.3125)
    expect(editor.getByRole('button', { name: 'Запази' })).toBeDisabled()
    await user.click(editor.getByRole('checkbox'))
    await user.type(editor.getByLabelText('Основание за корекцията'), '  Test-only QA reason  ')
    await user.click(editor.getByRole('button', { name: 'Запази' }))
    await waitFor(() => expect(changed).toHaveBeenCalledTimes(1))
    const mutations = request.mock.calls.filter(([, init]) => init?.method === 'PATCH')
    expect(mutations).toHaveLength(1)
    expect(mutations[0][0]).toBe('/api/catalog/v2/hotspots/109')
    expect(JSON.parse(String(mutations[0][1]?.body))).toEqual({ x: 0.4375, y: 0.3125, width: 0.3125, height: 0.3125, is_verified: false, reason: 'Test-only QA reason' })
    expect(changed).toHaveBeenCalledWith([hotspots[0]])
    expect(select).not.toHaveBeenCalled()
    expect(open).not.toHaveBeenCalled()
  })

  it('does not expose QA controls without parts.manage', async () => {
    await setup()
    expect(screen.queryByRole('button', { name: 'QA на областите' })).not.toBeInTheDocument()
  })
})
