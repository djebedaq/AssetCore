import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, expect, it, vi } from 'vitest'
import { I18nProvider } from '../../i18n'
import RevisionRepairKits from './RevisionRepairKits'

const json = (value: unknown, status = 200) => new Response(JSON.stringify(value),
  { status, headers: { 'Content-Type': 'application/json' } })
afterEach(() => { cleanup(); vi.unstubAllGlobals(); vi.restoreAllMocks() })

it('creates a draft kit from same-assembly parts, keeps code stable and highlights all position occurrences', async () => {
  const actor = userEvent.setup()
  const NativeURL = URL
  vi.stubGlobal('URL', class extends NativeURL {
    static createObjectURL = vi.fn(() => 'blob:kit-preview')
    static revokeObjectURL = vi.fn()
  })
  const part = { id: 4, position: '12', part_number: 'A', name_bg: 'Уплътнение', name_en: 'Seal',
    name_ru: 'Уплотнение', description: null, validation_status: 'READY' }
  const second = { ...part, id: 5, part_number: 'B' }
  let kits: Array<Record<string, unknown>> = []
  const calls: Array<{ path: string; method: string; body: Record<string, unknown> }> = []
  vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const path = String(input); const method = init?.method || 'GET'
    const body = init?.body ? JSON.parse(String(init.body)) as Record<string, unknown> : {}
    calls.push({ path, method, body })
    if (path.endsWith('/assemblies/7/repair-kits') && method === 'GET') return json(kits)
    if (path.endsWith('/assemblies/7/parts')) return json([part, second])
    if (path.endsWith('/assemblies/7/spare-list-pages')) return json([
      { visual_page_id: 9, artifact_title: 'QA source', filename: 'qa.pdf', page_number: 1 }])
    if (path.endsWith('/assemblies/7/repair-kits') && method === 'POST') {
      const kit = { ...body, id: 3, version: 1, components: [], component_count: 0, code_locked: false,
        validation_status: 'INCOMPLETE', incomplete_part_ids: [] }
      kits = [kit]; return json(kit, 201)
    }
    if (path.endsWith('/repair-kits/3/components') && method === 'POST') {
      const component = { ...body, id: 6, kit_id: 3, version: 1, part }
      kits = [{ ...kits[0], version: 2, components: [component], component_count: 1, code_locked: true, validation_status: 'READY' }]
      return json(component, 201)
    }
    if (path.endsWith('/assemblies/7/exploded-pages')) return json([{ visual_page_id: 10,
      artifact_id: 8, artifact_title: 'QA source', filename: 'qa.pdf', sha256: 'a'.repeat(64), page_number: 2 }])
    if (path.endsWith('/assemblies/7/hotspot-coverage')) return json([{ position: '12', part_count: 2,
      part_numbers: ['A', 'B'], hotspot_count: 2, verified_hotspot_count: 2, state: 'VERIFIED' }])
    if (path.endsWith('/visual-pages/10/hotspots')) return json([1, 2].map(id => ({ id, visual_page_id: 10,
      position: '12', x: id / 10, y: .2, width: .1, height: .1, version: 1, is_verified: true })))
    if (path.endsWith('/artifacts/8/pages/2/preview')) return new Response(new Uint8Array([137, 80, 78, 71]),
      { headers: { 'Content-Type': 'image/png' } })
    return json({ detail: { code: 'unexpected' } }, 404)
  }))
  render(<I18nProvider><RevisionRepairKits assemblyId={7} editable /></I18nProvider>)
  await actor.click(await screen.findByRole('button', { name: 'Добави комплект' }))
  await actor.type(screen.getByLabelText('Код'), 'KIT_SEALS')
  await actor.type(screen.getByLabelText('Име на български'), 'Комплект уплътнения')
  await actor.selectOptions(screen.getByLabelText('Изходна страница от списък'), '9')
  await actor.click(screen.getByRole('button', { name: 'Запази' }))
  await waitFor(() => expect(kits).toHaveLength(1))
  expect(kits[0].source_visual_page_id).toBe(9)
  await actor.selectOptions(screen.getByLabelText('Част'), '4')
  await actor.click(screen.getByRole('button', { name: 'Добави компонент' }))
  await waitFor(() => expect(kits[0].component_count).toBe(1))
  await waitFor(() => expect(document.querySelectorAll('.builder-hotspot.highlight')).toHaveLength(2))
  expect(screen.getByText('Готов')).toBeInTheDocument()
  await actor.click(screen.getAllByRole('button', { name: 'Редактиране' })[0])
  expect(screen.getByLabelText('Код')).toHaveAttribute('readonly')
  expect(calls.some(call => call.path.includes('/api/catalog/'))).toBe(false)
})
