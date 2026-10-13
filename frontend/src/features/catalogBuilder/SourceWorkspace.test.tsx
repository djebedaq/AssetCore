import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, expect, it, vi } from 'vitest'
import { I18nProvider } from '../../i18n'
import GuidedSources from './GuidedSources'
import GuidedWorkspace from './GuidedWorkspace'
import type { ReferencePage, Source } from './guidedTypes'
import { workspaceBg, workspaceEn, workspaceRu } from './workspaceTranslations'

const json = (data: unknown, status = 200) => new Response(JSON.stringify(data), { status, headers: { 'Content-Type': 'application/json' } })
const empty: ReferencePage = { id: 7, assembly_id: 3, stable_key: 'qa', sort_order: 0, version: 1, title: null,
  sources: [], scheme_count: 0, spare_list_count: 0, part_count: 0, position_count: 0, mapped_position_count: 0, status: 'NOT_STARTED' }
afterEach(() => { cleanup(); vi.unstubAllGlobals(); vi.restoreAllMocks() })
function images() {
  vi.stubGlobal('ResizeObserver', class { observe() {} disconnect() {} })
  const NativeURL = URL
  vi.stubGlobal('URL', class extends NativeURL { static createObjectURL = vi.fn(() => 'blob:qa'); static revokeObjectURL = vi.fn() })
}

it('browses first, middle, last, previous/next and zoom without loading an entire manual', async () => {
  images()
  const paths: string[] = []
  vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
    const path = String(input); paths.push(path)
    return path.includes('/preview') ? new Response(new Uint8Array([137]), { headers: { 'Content-Type': 'image/png' } }) : json([{ id: 20, filename: 'manual.pdf', page_count: 120 }])
  }))
  render(<I18nProvider><GuidedSources revisionId={2} page={empty} changed={vi.fn(async () => {})} onDirtyChange={vi.fn()} /></I18nProvider>)
  const user = userEvent.setup()
  await user.click(screen.getByRole('button', { name: '+ Добави списък с части' }))
  await screen.findByRole('img', { name: 'PDF страница 1' })
  expect(screen.getByRole('button', { name: 'Предишна PDF страница' })).toBeDisabled()
  fireEvent.change(screen.getByRole('spinbutton'), { target: { value: '60' } })
  fireEvent.keyDown(screen.getByRole('spinbutton'), { key: 'Enter' })
  await screen.findByRole('img', { name: 'PDF страница 60' })
  await user.click(screen.getByRole('button', { name: 'Следваща PDF страница' }))
  await screen.findByRole('img', { name: 'PDF страница 61' })
  await user.click(screen.getByRole('button', { name: 'Предишна PDF страница' }))
  await screen.findByRole('img', { name: 'PDF страница 60' })
  fireEvent.change(screen.getByRole('spinbutton'), { target: { value: '120' } })
  fireEvent.keyDown(screen.getByRole('spinbutton'), { key: 'Enter' })
  const img = await screen.findByRole('img', { name: 'PDF страница 120' })
  expect(screen.getByRole('button', { name: 'Следваща PDF страница' })).toBeDisabled()
  await user.click(screen.getByRole('button', { name: 'По ширина' }))
  await user.click(screen.getByRole('button', { name: 'Увеличи' }))
  expect(img.parentElement).toHaveStyle({ width: '125%' })
  await user.click(screen.getByRole('button', { name: 'По ширина' }))
  expect(img.parentElement).toHaveStyle({ width: '100%' })
  expect(paths.filter(path => path.includes('/preview'))).toHaveLength(5)
  expect(URL.revokeObjectURL).toHaveBeenCalledTimes(4)
})

it('assigns multiple schemes and lists in one request and confirms a real dependency preview', async () => {
  images()
  let page = { ...empty }
  const writes: Array<{ path: string; body: Record<string, unknown> }> = []
  vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const path = String(input)
    if (path.includes('/preview')) return new Response(new Uint8Array([137]), { headers: { 'Content-Type': 'image/png' } })
    if (path.includes('/draft-deletion/') && !init?.method) return json({ digest: 'a'.repeat(64), counts: { catalog_revision_visual_pages: 1 }, blockers: [] })
    if (init?.method === 'POST') {
      const body = JSON.parse(String(init.body)); writes.push({ path, body })
      if (path.endsWith('/sources')) {
        const sources: Source[] = body.selections.flatMap((item: { page_number: number; roles: Source['role'][] }) => item.roles.map(role => ({
          id: page.sources.length + item.page_number * 2 + (role === 'SPARE_PARTS_LIST' ? 1 : 0), artifact_id: 20, page_number: item.page_number, role, title: '', filename: 'manual.pdf',
        })))
        page = { ...page, version: page.version + 1, sources }
      } else page = { ...page, version: page.version + 1, sources: page.sources.slice(1) }
      return path.includes('/draft-deletion/') ? new Response(null, { status: 204 }) : json(page)
    }
    return json([{ id: 20, filename: 'manual.pdf', page_count: 4 }])
  }))
  const view = render(<I18nProvider><GuidedSources revisionId={2} page={page} changed={refresh} onDirtyChange={vi.fn()} /></I18nProvider>)
  async function refresh() { view.rerender(<I18nProvider><GuidedSources revisionId={2} page={page} changed={refresh} onDirtyChange={vi.fn()} /></I18nProvider>) }
  const user = userEvent.setup()
  await user.click(screen.getByRole('button', { name: '+ Добави схема' }))
  await screen.findByRole('img')
  for (const index of [0, 1]) {
    const boxes = within(document.querySelectorAll('.pdf-page-picker article')[index] as HTMLElement).getAllByRole('checkbox')
    await user.click(boxes[0]); await user.click(boxes[1])
  }
  await user.click(screen.getByRole('button', { name: 'Добави избраните страници (2)' }))
  await waitFor(() => expect(page.sources).toHaveLength(4))
  expect(writes).toHaveLength(1)
  expect(writes[0].body).toEqual({ expected_version: 1, artifact_id: 20, selections: [1, 2].map(page_number => ({ page_number, roles: ['EXPLODED_SCHEME', 'SPARE_PARTS_LIST'] })) })
  await user.click(screen.getByRole('button', { name: 'Премахни страница 1: Схема' }))
  await screen.findByText('Избрани PDF страници: 1')
  await user.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Изтрий' }))
  await waitFor(() => expect(page.sources).toHaveLength(3))
  expect(writes.at(-1)?.body.expected_digest).toBe('a'.repeat(64))
})

it('keeps reference and page selected when switching the local sources/parts/mapping work', async () => {
  const groups = [3, 4].map(id => ({ id, code: 'QA', name_bg: `Reference ${id}`, name_en: '', name_ru: '', part_count: 0, exploded_page_count: 0, spare_list_page_count: 0 }))
  vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => String(input).endsWith('/review-session') ? json({ id: 1, sources: [], selection_digest: 'qa' })
    : String(input).endsWith('/reference-pages') ? json([empty, { ...empty, id: 8 }]) : json([])))
  render(<I18nProvider><GuidedWorkspace revisionId={2} groups={groups} task="references" changed={vi.fn(async () => {})} onDirtyChange={vi.fn()} /></I18nProvider>)
  const user = userEvent.setup()
  await user.click(await screen.findByRole('button', { name: /Схема и списъци 2/ }))
  await user.click(screen.getByRole('button', { name: 'Части' }))
  expect(screen.getByRole('button', { name: /Схема и списъци 2/ })).toHaveAttribute('aria-current', 'page')
  expect(screen.getByRole('button', { name: /Reference 3/ })).toHaveAttribute('aria-current', 'page')
  await user.click(screen.getAllByRole('button', { name: 'Източници' })[0])
  expect(screen.getByRole('button', { name: /Схема и списъци 2/ })).toHaveAttribute('aria-current', 'page')
})

it('keeps complete workspace translation parity', () => {
  expect(Object.keys(workspaceEn).sort()).toEqual(Object.keys(workspaceBg).sort())
  expect(Object.keys(workspaceRu).sort()).toEqual(Object.keys(workspaceBg).sort())
})

it.each(['catalog', 'review'] as const)('opens sources when a draft workspace mounts from the global %s view', async task => {
  const groups = [{ id: 3, code: 'QA', name_bg: 'Reference', name_en: '', name_ru: '', part_count: 0, exploded_page_count: 0, spare_list_page_count: 0 }]
  vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => String(input).endsWith('/reference-pages') ? json([empty]) : json([])))
  render(<I18nProvider><GuidedWorkspace revisionId={2} groups={groups} task={task} changed={vi.fn(async () => {})} onDirtyChange={vi.fn()} /></I18nProvider>)
  expect(await screen.findByRole('button', { name: '+ Добави схема' })).toBeVisible()
})

it('prevents opening the previous page sources while a new logical page is still being created', async () => {
  const groups = [{ id: 3, code: 'QA', name_bg: 'Reference', name_en: '', name_ru: '', part_count: 0, exploded_page_count: 0, spare_list_page_count: 0 }]
  let pages = [empty]
  let complete!: () => void
  vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    if (init?.method === 'POST') return new Promise<Response>(resolve => {
      complete = () => { pages = [empty, { ...empty, id: 8 }]; resolve(json(pages[1])) }
    })
    return String(input).endsWith('/reference-pages') ? json(pages) : json([])
  }))
  render(<I18nProvider><GuidedWorkspace revisionId={2} groups={groups} task="references" changed={vi.fn(async () => {})} onDirtyChange={vi.fn()} /></I18nProvider>)
  const user = userEvent.setup()
  await screen.findByRole('button', { name: '+ Добави схема' })
  await user.click(screen.getByRole('button', { name: 'Добави страница' }))
  expect(screen.getByRole('button', { name: '+ Добави схема' })).toBeDisabled()
  complete()
  await waitFor(() => expect(screen.getByRole('button', { name: /Схема и списъци 2/ })).toHaveAttribute('aria-current', 'page'))
  await waitFor(() => expect(screen.getByRole('button', { name: '+ Добави схема' })).toBeEnabled())
})

it('recognizes a shared PDF assigned through another reference-local artifact alias', async () => {
  images()
  vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => String(input).includes('/preview')
    ? new Response(new Uint8Array([137]), { headers: { 'Content-Type': 'image/png' } })
    : json([{ id: 20, filename: 'manual.pdf', page_count: 120, sha256: 'shared-content' }])))
  const page = { ...empty, scheme_count: 1, sources: [{ id: 1, artifact_id: 99, sha256: 'shared-content', page_number: 22,
    role: 'EXPLODED_SCHEME' as const, title: '', filename: 'manual.pdf' }] }
  render(<I18nProvider><GuidedSources revisionId={2} page={page} changed={vi.fn(async () => {})} onDirtyChange={vi.fn()} /></I18nProvider>)
  const user = userEvent.setup()
  await user.click(await screen.findByRole('button', { name: 'PDF страница 22' }))
  await screen.findByRole('img', { name: 'PDF страница 22' })
  const boxes = within(document.querySelectorAll('.pdf-page-picker article')[21] as HTMLElement).getAllByRole('checkbox')
  expect(boxes[0]).toBeChecked(); expect(boxes[0]).toBeDisabled(); expect(boxes[1]).toBeEnabled()
})

it('offers retry after a failed real-page request without retaining the failed object URL', async () => {
  images()
  let attempts = 0
  vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
    if (!String(input).includes('/preview')) return json([{ id: 20, filename: 'manual.pdf', page_count: 120 }])
    attempts += 1
    return attempts === 1 ? json({ detail: 'busy' }, 409)
      : new Response(new Uint8Array([137]), { headers: { 'Content-Type': 'image/png' } })
  }))
  render(<I18nProvider><GuidedSources revisionId={2} page={empty} changed={vi.fn(async () => {})} onDirtyChange={vi.fn()} /></I18nProvider>)
  const user = userEvent.setup()
  await user.click(screen.getByRole('button', { name: '+ Добави схема' }))
  await screen.findByRole('alert')
  await user.click(screen.getByRole('button', { name: 'Грешка — опитайте отново' }))
  await screen.findByRole('img', { name: 'PDF страница 1' })
  expect(attempts).toBe(2)
})
