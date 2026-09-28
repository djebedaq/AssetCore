import { act, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, expect, it, vi } from 'vitest'
import { I18nProvider } from '../../i18n'
import RevisionVisualSources from './RevisionVisualSources'

const json = (value: unknown, status = 200) => new Response(JSON.stringify(value), {
  status, headers: { 'Content-Type': 'application/json' },
})

afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks() })

it('creates an assembly, reuses one PDF for both explicit roles, and previews lazily', async () => {
  const actor = userEvent.setup()
  const assembly = { id: 10, code: 'PUMP', name_bg: 'Помпа', name_en: 'Pump', name_ru: 'Насос',
    description: null, sort_order: 0, artifact_count: 0, exploded_page_count: 0, spare_list_page_count: 0 }
  const artifact = { id: 20, title: 'QA source', filename: 'qa.pdf', sha256: 'abc', page_count: 2,
    document_reference: null, document_date: null, language: null }
  let assemblies: typeof assembly[] = []
  let artifacts: typeof artifact[] = []
  let assignments: Array<{ id: number; artifact_id: number; page_number: number; role: string }> = []
  const calls: Array<{ path: string; method: string; body?: Record<string, unknown> }> = []
  const reveal: Array<() => void> = []
  vi.stubGlobal('IntersectionObserver', class {
    callback: IntersectionObserverCallback
    constructor(callback: IntersectionObserverCallback) { this.callback = callback }
    observe() { reveal.push(() => this.callback([{ isIntersecting: true } as IntersectionObserverEntry], this as unknown as IntersectionObserver)) }
    disconnect() { /* cleanup */ }
  })
  vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const path = String(input)
    const method = init?.method || 'GET'
    const body = init?.body ? JSON.parse(String(init.body)) as Record<string, unknown> : undefined
    calls.push({ path, method, body })
    if (path.endsWith('/artifacts/20/pages/1/preview')) return new Response(new Uint8Array([137, 80, 78, 71]),
      { headers: { 'Content-Type': 'image/png' } })
    if (path.endsWith('/revisions/1/assemblies') && method === 'GET') return json(assemblies)
    if (path.endsWith('/revisions/1/assemblies') && method === 'POST') { assemblies = [assembly]; return json(assembly, 201) }
    if (path.endsWith('/assemblies/10/artifacts') && method === 'GET') return json(artifacts)
    if (path.endsWith('/assemblies/10/artifacts') && method === 'POST') { artifacts = [artifact]; return json(artifact, 201) }
    if (path.endsWith('/artifacts/20') && method === 'DELETE') { artifacts = []; return new Response(null, { status: 204 }) }
    if (path.endsWith('/artifacts/20/visual-pages') && method === 'GET') return json(assignments)
    if (path.endsWith('/artifacts/20/visual-pages') && method === 'POST') {
      if (((body?.page_numbers || []) as number[]).some(number => assignments.some(item => item.page_number === number && item.role === body?.role))) {
        return json({ detail: { code: 'catalog_visual_page_duplicate' } }, 409)
      }
      assignments = [...assignments, ...((body?.page_numbers || []) as number[]).map(number => ({
        id: assignments.length + number, artifact_id: 20, page_number: number, role: String(body?.role),
      }))]
      return json(assignments, 201)
    }
    return json({ detail: { code: 'unexpected' } }, 404)
  }))
  render(<I18nProvider><RevisionVisualSources revisionId={1} editable /></I18nProvider>)
  await actor.click(await screen.findByRole('button', { name: 'Добави възел' }))
  await actor.type(screen.getByLabelText('Код'), 'PUMP')
  await actor.type(screen.getByLabelText('Име на български'), 'Помпа')
  await actor.type(screen.getByLabelText('Име на английски'), 'Pump')
  await actor.type(screen.getByLabelText('Име на руски'), 'Насос')
  await actor.click(screen.getByRole('button', { name: 'Запази' }))
  await actor.click(await screen.findByRole('button', { name: '+ Разглобена схема' }))
  await actor.click(await screen.findByRole('button', { name: 'Качи изходен PDF' }))
  await actor.type(screen.getByLabelText('Заглавие на източника'), 'QA source')
  await actor.upload(screen.getByLabelText('PDF файл'), new File(['%PDF-qa'], 'qa.pdf', { type: 'application/pdf' }))
  expect((screen.getByLabelText('PDF файл') as HTMLInputElement).files?.length).toBe(1)
  expect(screen.getByRole('button', { name: 'Запази' })).not.toBeDisabled()
  await actor.click(screen.getByRole('button', { name: 'Запази' }))
  expect(screen.queryByRole('alert')?.textContent).toBeFalsy()
  await waitFor(() => expect(calls.some(call => call.path.endsWith('/assemblies/10/artifacts') && call.method === 'POST')).toBe(true))
  await waitFor(() => expect(screen.getAllByText(/SHA-256: abc/).length).toBeGreaterThan(0))
  expect(calls.filter(call => call.path.includes('/preview'))).toHaveLength(0)
  await waitFor(() => expect(screen.getAllByLabelText('Избери страница')).toHaveLength(2))
  await act(async () => { reveal[0]?.() })
  await waitFor(() => expect(calls.some(call => call.path.endsWith('/artifacts/20/pages/1/preview'))).toBe(true))
  await actor.click(screen.getAllByLabelText('Избери страница')[0])
  await actor.click(screen.getByRole('button', { name: 'Задай избраните страници като: Разглобена схема' }))
  await screen.findByText('Разглобена схема')
  await actor.click(screen.getByRole('button', { name: '+ Списък резервни части' }))
  await actor.click(screen.getAllByRole('button', { name: 'Отвори работното пространство' })[1])
  await actor.click(screen.getAllByLabelText('Избери страница')[1])
  await actor.click(screen.getByRole('button', { name: 'Задай избраните страници като: Списък резервни части' }))
  await screen.findByText('Списък резервни части')
  expect(calls.filter(call => call.method === 'POST' && call.path.endsWith('/artifacts/20/visual-pages'))
    .map(call => call.body)).toEqual([
    { role: 'EXPLODED_SCHEME', page_numbers: [1] },
    { role: 'SPARE_PARTS_LIST', page_numbers: [2] },
  ])
  expect(calls.filter(call => call.method === 'POST' && call.path.endsWith('/assemblies/10/artifacts'))).toHaveLength(1)
  await actor.click(screen.getAllByLabelText('Избери страница')[0])
  await actor.click(screen.getByRole('button', { name: 'Отбележи като разглобена схема' }))
  expect(await screen.findByRole('alert')).toHaveTextContent('Тази роля вече е зададена за избрана страница.')
  const confirm = vi.fn().mockReturnValueOnce(false).mockReturnValueOnce(true)
  vi.stubGlobal('confirm', confirm)
  await actor.click(screen.getAllByRole('button', { name: 'Премахни' })[1])
  expect(calls.filter(call => call.method === 'DELETE')).toHaveLength(0)
  await actor.click(screen.getAllByRole('button', { name: 'Премахни' })[1])
  await waitFor(() => expect(calls.filter(call => call.method === 'DELETE' && call.path.endsWith('/artifacts/20'))).toHaveLength(1))
  expect(confirm).toHaveBeenCalledTimes(2)
})
