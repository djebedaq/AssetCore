import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, expect, it, vi } from 'vitest'
import { I18nProvider } from '../../i18n'
import { setSessionUser } from '../../permissions'
import type { UserSession } from '../../types'
import CatalogBuilder from './CatalogBuilder'
import RevisionHotspotEditor from './RevisionHotspotEditor'
import { wizardBg, wizardEn, wizardRu } from './wizardTranslations'
import { UploadTestTransport } from './uploadTestTransport'

const json = (value: unknown, status = 200) => new Response(JSON.stringify(value), { status, headers: { 'Content-Type': 'application/json' } })
const category = { id: 1, code: 'QA', name_bg: 'QA категория', name_en: 'QA', name_ru: 'QA', is_active: true, capabilities: ['HAS_PARTS_CATALOG'] }
const actor = { id: 1, email: 'qa@example.invalid', role: 'administrator', permissions: ['parts.manage', 'parts.view'] } as UserSession

afterEach(() => { cleanup(); vi.unstubAllGlobals(); vi.restoreAllMocks() })
function pointerEnvironment() {
  vi.stubGlobal('XMLHttpRequest', UploadTestTransport)
  const NativeURL = URL
  vi.stubGlobal('URL', class extends NativeURL {
    static createObjectURL = vi.fn(() => 'blob:qa-page')
    static revokeObjectURL = vi.fn()
  })
  vi.stubGlobal('PointerEvent', class extends MouseEvent {
    pointerId: number
    pointerType: string
    constructor(type: string, init: PointerEventInit = {}) { super(type, init); this.pointerId = init.pointerId || 0; this.pointerType = init.pointerType || 'mouse' }
  })
  HTMLElement.prototype.setPointerCapture = vi.fn()
  HTMLElement.prototype.hasPointerCapture = vi.fn(() => false)
  HTMLElement.prototype.releasePointerCapture = vi.fn()
  vi.stubGlobal('IntersectionObserver', class {
    callback: IntersectionObserverCallback
    constructor(callback: IntersectionObserverCallback) { this.callback = callback }
    observe() { this.callback([{ isIntersecting: true } as IntersectionObserverEntry], this as unknown as IntersectionObserver) }
    disconnect() {}
  })
}

it('keeps complete BG/EN/RU wizard keys', () => {
  expect(Object.keys(wizardEn).sort()).toEqual(Object.keys(wizardBg).sort())
  expect(Object.keys(wizardRu).sort()).toEqual(Object.keys(wizardBg).sort())
})

it('preserves an unsaved simple form when a mode switch is cancelled', async () => {
  setSessionUser(actor)
  const confirm = vi.spyOn(window, 'confirm').mockReturnValue(false)
  vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => String(input).endsWith('/categories') ? json([category]) : json([])))
  render(<I18nProvider><CatalogBuilder /></I18nProvider>)
  const user = userEvent.setup()
  await user.click(await screen.findByRole('button', { name: 'Нов каталог' }))
  await user.type(screen.getByLabelText('Име на каталога'), 'QA незапазен каталог')
  await user.click(screen.getByRole('button', { name: 'Разширен режим' }))
  expect(confirm).toHaveBeenCalled()
  expect(screen.getByLabelText('Име на каталога')).toHaveValue('QA незапазен каталог')
  expect(screen.getByRole('dialog')).toBeVisible()
})

it('point mode cancels touch navigation, saves once, advances and retains verification failures', async () => {
  pointerEnvironment()
  const hotspots: Array<Record<string, unknown>> = []
  let failVerify = false
  const writes: string[] = []
  vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const path = String(input); const method = init?.method || 'GET'; const body = init?.body ? JSON.parse(String(init.body)) : {}
    if (method !== 'GET') writes.push(path)
    if (path.endsWith('/exploded-pages')) return json([{ visual_page_id: 5, artifact_id: 8, artifact_title: 'QA', filename: 'qa.pdf', page_number: 1 }])
    if (path.endsWith('/hotspot-coverage')) return json(['1', '2'].map(position => ({ position, part_count: 1, part_numbers: [`QA-${position}`],
      hotspot_count: hotspots.filter(row => row.position === position).length,
      state: hotspots.some(row => row.position === position && row.is_verified) ? 'VERIFIED' : hotspots.some(row => row.position === position) ? 'UNVERIFIED' : 'NO_HOTSPOT' })))
    if (path.includes('/preview')) return new Response(new Uint8Array([137]), { headers: { 'Content-Type': 'image/png' } })
    if (path.endsWith('/visual-pages/5/hotspots')) {
      if (method === 'POST') { const row = { ...body, id: hotspots.length + 1, version: 1, is_verified: false }; hotspots.push(row); return json(row, 201) }
      return json(hotspots)
    }
    if (path.endsWith('/verify')) {
      if (failVerify) return json({ detail: { code: 'catalog_hotspot_stale' } }, 409)
      const id = Number(path.split('/').at(-2)); const row = hotspots.find(row => row.id === id)!
      Object.assign(row, { is_verified: true, version: 2 }); return json(row)
    }
    return json({}, 404)
  }))
  render(<I18nProvider><RevisionHotspotEditor assemblyId={7} editable simple /></I18nProvider>)
  await screen.findByRole('img')
  const surface = document.querySelector('.builder-scheme-canvas') as HTMLElement
  vi.spyOn(surface, 'getBoundingClientRect').mockReturnValue({ left: 0, top: 0, width: 100, height: 100 } as DOMRect)
  fireEvent.pointerDown(surface, { pointerId: 10, pointerType: 'touch', clientX: 10, clientY: 10 })
  fireEvent.pointerDown(surface, { pointerId: 11, pointerType: 'touch', clientX: 20, clientY: 20 })
  fireEvent.pointerUp(surface, { pointerId: 10, pointerType: 'touch' }); fireEvent.pointerUp(surface, { pointerId: 11, pointerType: 'touch' })
  fireEvent.pointerDown(surface, { pointerId: 12, pointerType: 'pen', clientX: 10, clientY: 10 }); fireEvent.pointerCancel(surface, { pointerId: 12, pointerType: 'pen' })
  fireEvent.pointerDown(surface, { pointerId: 13, pointerType: 'touch', clientX: 10, clientY: 10 })
  fireEvent.pointerMove(surface, { pointerId: 13, pointerType: 'touch', clientX: 50, clientY: 50 }); fireEvent.pointerUp(surface, { pointerId: 13, pointerType: 'touch' })
  expect(writes).toHaveLength(0)
  fireEvent.pointerDown(surface, { pointerId: 1, pointerType: 'pen', clientX: 0, clientY: 0 }); fireEvent.pointerUp(surface, { pointerId: 1, pointerType: 'pen', clientX: 0, clientY: 0 })
  await waitFor(() => expect(hotspots[0]?.is_verified).toBe(true))
  await waitFor(() => expect(screen.getByLabelText('Позиция')).toHaveValue('2'))
  expect(hotspots[0]).toMatchObject({ x: 0, y: 0, width: .03, height: .03 })
  failVerify = true
  fireEvent.pointerDown(surface, { pointerId: 2, clientX: 50, clientY: 50 }); fireEvent.pointerUp(surface, { pointerId: 2, clientX: 50, clientY: 50 })
  expect(await screen.findByRole('alert')).toHaveTextContent('Зоната е запазена, но потвърждението не успя')
  expect(screen.getByLabelText('Позиция')).toHaveValue('2')
  expect(hotspots).toHaveLength(2)
  expect(writes.filter(path => path.endsWith('/hotspots'))).toHaveLength(2)
})
