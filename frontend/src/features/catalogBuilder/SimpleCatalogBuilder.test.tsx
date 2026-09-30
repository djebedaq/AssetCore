import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, expect, it, vi } from 'vitest'
import { I18nProvider } from '../../i18n'
import { setSessionUser } from '../../permissions'
import type { UserSession } from '../../types'
import CatalogBuilder from './CatalogBuilder'
import RevisionHotspotEditor from './RevisionHotspotEditor'
import { parsePageRange } from './WizardDocuments'
import { wizardBg, wizardEn, wizardRu } from './wizardTranslations'

const json = (value: unknown, status = 200) => new Response(JSON.stringify(value), { status, headers: { 'Content-Type': 'application/json' } })
const category = { id: 1, code: 'QA', name_bg: 'QA категория', name_en: 'QA', name_ru: 'QA', is_active: true, capabilities: ['HAS_PARTS_CATALOG'] }
const group = { id: 7, code: 'QA_GROUP', name_bg: 'QA група', name_en: 'QA', name_ru: 'QA', part_count: 0, exploded_page_count: 0, spare_list_page_count: 0 }
const actor = { id: 1, email: 'qa@example.invalid', role: 'administrator', permissions: ['parts.manage', 'parts.view'] } as UserSession

afterEach(() => { cleanup(); vi.unstubAllGlobals(); vi.restoreAllMocks() })
function pointerEnvironment() {
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

it('completes the default simple create, original PDF, bulk import, point, review and publish workflow', async () => {
  setSessionUser(actor); pointerEnvironment()
  vi.spyOn(window, 'confirm').mockReturnValue(true)
  const user = userEvent.setup()
  let catalogs: Array<Record<string, unknown>> = []
  let groups: typeof group[] = []
  let status = 'DRAFT'
  let parts: Array<Record<string, unknown>> = []
  let hotspots: Array<Record<string, unknown>> = []
  let documents: Array<{ id: number; title: string; filename: string; sha256: string; page_count: number; assignments: Array<Record<string, unknown>> }> = []
  const writes: Array<{ path: string; body: Record<string, unknown> }> = []
  vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const path = String(input); const method = init?.method || 'GET'; const body = init?.body ? JSON.parse(String(init.body)) as Record<string, unknown> : {}
    if (method !== 'GET') writes.push({ path, body })
    if (path === '/api/categories') return json([category])
    if (path.endsWith('/simple/catalogs')) {
      catalogs = [{ id: 10, code: 'QA_GENERATED', asset_category_id: 1, asset_category: category, name_bg: body.name, name_en: body.name, name_ru: body.name,
        manufacturer: body.manufacturer, model_reference: body.model_reference, is_active: true, published_revision: null, draft_revision_count: 1 }]
      return json(catalogs[0], 201)
    }
    if (path.endsWith('/catalogs')) return json(catalogs)
    if (path.endsWith('/catalogs/10/revisions')) return json([{ id: 11, revision_code: 'REV-1', status, created_at: '2026-09-30T10:00:00Z' }])
    if (path.endsWith('/revisions/11/assemblies')) return json(groups)
    if (path.endsWith('/revisions/11/groups')) { groups = [{ ...group, name_bg: String(body.name) }]; return json(groups[0], 201) }
    if (path.endsWith('/assemblies/7/artifacts') && method === 'POST') {
      documents = [{ id: 8, title: String(body.title), filename: String(body.filename), sha256: 'a'.repeat(64), page_count: 2, assignments: [] }]
      return json(documents[0], 201)
    }
    if (path.endsWith('/revisions/11/documents')) return json(documents)
    if (path.endsWith('/artifacts/8/classify')) {
      const numbers = body.page_numbers as number[]; const roles = body.roles as string[]
      documents[0].assignments = [...documents[0].assignments.filter(row => !numbers.includes(Number(row.page_number))),
        ...numbers.flatMap(number => roles.map(role => ({ id: role === 'EXPLODED_SCHEME' ? 5 : 6, artifact_id: 8, assembly_id: 7, page_number: number, role })))]
      groups = [{ ...groups[0], exploded_page_count: documents[0].assignments.filter(row => row.role === 'EXPLODED_SCHEME').length,
        spare_list_page_count: documents[0].assignments.filter(row => row.role === 'SPARE_PARTS_LIST').length }]
      return json(documents)
    }
    if (path.includes('/pages/') && path.includes('/preview')) return new Response(new Uint8Array([137, 80, 78, 71]), { headers: { 'Content-Type': 'image/png' } })
    if (path.endsWith('/revisions/11/parts/import-preview')) return json({
      token: 'qa-preview', summary: { total_rows: 1, valid_rows: 1, warning_rows: 0, error_rows: 0, duplicate_rows: 0 },
      rows: [{ row_number: 2, assembly_id: 7, assembly_code: 'QA_GROUP', normalized: { position: '1', part_number: 'QA-P' }, status: 'VALID', errors: [], warnings: [] }],
    })
    if (path.endsWith('/revisions/11/parts/import-confirm')) {
      parts = [{ id: 20, assembly_id: 7, position: '1', part_number: 'QA-P', name_bg: 'QA част', quantity: 1, source_pages: [{ id: 21, visual_page_id: 6, filename: 'original.pdf', page_number: 1 }], validation_status: 'READY' }]
      groups = [{ ...groups[0], part_count: 1 }]; return json({ created_count: 1, part_ids: [20] })
    }
    if (path.endsWith('/assemblies/7/parts')) return json(parts)
    if (path.endsWith('/assemblies/7/spare-list-pages')) return json([{ visual_page_id: 6, artifact_id: 8, artifact_title: 'QA', filename: 'original.pdf', page_number: 1 }])
    if (path.endsWith('/assemblies/7/exploded-pages')) return json([{ visual_page_id: 5, artifact_id: 8, artifact_title: 'QA', filename: 'original.pdf', page_number: 2 }])
    if (path.endsWith('/assemblies/7/hotspot-coverage')) return json(parts.map(part => ({ position: part.position, part_count: 1, part_numbers: [part.part_number],
      names: [{ name_bg: part.name_bg }], hotspot_count: hotspots.length, verified_hotspot_count: hotspots.filter(row => row.is_verified).length,
      state: hotspots.some(row => row.is_verified) ? 'VERIFIED' : hotspots.length ? 'UNVERIFIED' : 'NO_HOTSPOT' })))
    if (path.endsWith('/visual-pages/5/hotspots')) {
      if (method === 'POST') { hotspots = [{ ...body, id: 30, visual_page_id: 5, version: 1, is_verified: false }]; return json(hotspots[0], 201) }
      return json(hotspots)
    }
    if (path.endsWith('/hotspots/30/verify')) { hotspots = [{ ...hotspots[0], version: 2, is_verified: true }]; return json(hotspots[0]) }
    if (path.endsWith('/revisions/11/workflow')) return json({ ready: parts.length > 0, publication_digest: 'b'.repeat(64), current_published_revision_id: null,
      errors: [], warnings: [], summary: { assembly_count: groups.length, part_count: parts.length, spare_list_page_count: groups[0]?.spare_list_page_count || 0, exploded_page_count: groups[0]?.exploded_page_count || 0, verified_hotspot_count: hotspots.filter(row => row.is_verified).length },
      progress: { position_count: parts.length, completed_positions: hotspots.filter(row => row.is_verified).length }, resume_step: documents.length ? 'parts' : 'documents' })
    if (path.endsWith('/revisions/11/publish')) { status = 'PUBLISHED'; return json({ status }) }
    if (path.endsWith('/catalogs/10/assets') || path.includes('/eligible-assets')) return json([])
    return json({ detail: { code: 'unexpected' } }, 404)
  }))
  render(<I18nProvider><CatalogBuilder /></I18nProvider>)
  expect(await screen.findByRole('button', { name: 'Разширен режим' })).toBeVisible()
  await user.click(await screen.findByRole('button', { name: 'Нов каталог' }))
  const dialog = within(screen.getByRole('dialog'))
  expect(dialog.queryByLabelText('Код')).not.toBeInTheDocument()
  expect(dialog.queryByLabelText('Име на английски')).not.toBeInTheDocument()
  await user.type(dialog.getByLabelText('Име на каталога'), 'QA каталог')
  await user.selectOptions(dialog.getByLabelText('Категория активи'), '1')
  await user.click(dialog.getByRole('button', { name: 'Продължи' }))
  await user.type(await screen.findByLabelText('Име на групата'), 'QA група')
  await user.click(screen.getByRole('button', { name: 'Добави група' }))
  await waitFor(() => expect(groups).toHaveLength(1))
  await user.upload(screen.getByLabelText('Качи оригиналния PDF'), new File(['%PDF-QA'], 'original.pdf', { type: 'application/pdf' }))
  await user.click(screen.getByRole('button', { name: 'Качи оригиналния PDF' }))
  await screen.findByLabelText('Избери PDF страница 1')
  const docStep = screen.getByLabelText('Страници, например 10,12,14-16').closest('.builder-workspace') as HTMLElement
  await user.type(within(docStep).getByLabelText('Страници, например 10,12,14-16'), '1')
  await user.click(within(docStep).getByRole('button', { name: 'Избери диапазон' }))
  await user.selectOptions(within(docStep).getAllByLabelText('Роля на страницата')[0], 'list')
  await user.click(within(docStep).getByRole('button', { name: 'Приложи към избраните страници' }))
  await waitFor(() => expect(groups[0].spare_list_page_count).toBe(1))
  await user.clear(within(docStep).getByLabelText('Страници, например 10,12,14-16'))
  await user.type(within(docStep).getByLabelText('Страници, например 10,12,14-16'), '2')
  await user.click(within(docStep).getByRole('button', { name: 'Избери диапазон' }))
  await user.selectOptions(within(docStep).getAllByLabelText('Роля на страницата')[0], 'scheme')
  await user.click(within(docStep).getByRole('button', { name: 'Приложи към избраните страници' }))
  await waitFor(() => expect(groups[0].exploded_page_count).toBe(1))
  await user.click(screen.getByRole('button', { name: '3 Части' }))
  await user.upload(screen.getByLabelText('CSV UTF-8 файл'), new File(['assembly_code,position,part_number,name,source_page\nQA_GROUP,1,QA-P,QA,1'], 'parts.csv', { type: 'text/csv' }))
  await user.click(screen.getByRole('button', { name: 'Преглед' }))
  await user.click(await screen.findByRole('button', { name: 'Потвърди импорта' }))
  await waitFor(() => expect(parts).toHaveLength(1))
  await user.click(screen.getByRole('button', { name: '4 Маркиране' }))
  await screen.findByRole('img', { name: 'Страница на разглобената схема' })
  const surface = document.querySelector('.builder-scheme-canvas') as HTMLElement
  vi.spyOn(surface, 'getBoundingClientRect').mockReturnValue({ left: 0, top: 0, width: 100, height: 100 } as DOMRect)
  fireEvent.pointerDown(surface, { pointerId: 1, clientX: 50, clientY: 50 })
  fireEvent.pointerUp(surface, { pointerId: 1, clientX: 50, clientY: 50 })
  await waitFor(() => expect(hotspots[0]?.is_verified).toBe(true))
  expect(writes.find(write => write.path.endsWith('/visual-pages/5/hotspots'))?.body).toMatchObject({ x: .485, y: .485, width: .03, height: .03 })
  await user.click(screen.getByRole('button', { name: '5 Публикуване' }))
  await user.click(await screen.findByRole('button', { name: 'Публикувай каталог' }))
  expect(await screen.findByText('Каталогът е публикуван.')).toBeVisible()
  expect(writes.find(write => write.path.endsWith('/publish'))?.body).toMatchObject({ expected_publication_digest: 'b'.repeat(64), confirmed: true })
  expect(writes.filter(write => write.path.endsWith('/artifacts'))).toHaveLength(1)
})

it('keeps complete BG/EN/RU wizard keys and rejects unsafe physical page ranges', () => {
  expect(Object.keys(wizardEn).sort()).toEqual(Object.keys(wizardBg).sort())
  expect(Object.keys(wizardRu).sort()).toEqual(Object.keys(wizardBg).sort())
  expect(parsePageRange('10,12,14-16', 20)).toEqual([10, 12, 14, 15, 16])
  for (const input of ['0', '21', '3-1', '1,', '1-1000000', 'x']) expect(() => parsePageRange(input, 20)).toThrow()
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
