import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, expect, it, vi } from 'vitest'
import { I18nProvider } from '../../i18n'
import RevisionParts from './RevisionParts'

const json = (value: unknown, status = 200) => new Response(JSON.stringify(value),
  { status, headers: { 'Content-Type': 'application/json' } })

afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks() })

it('adds a draft part and imports a CSV only after preview confirmation', async () => {
  const actor = userEvent.setup()
  let rows: Array<Record<string, unknown>> = []
  const calls: string[] = []
  vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const path = String(input)
    const method = init?.method || 'GET'
    calls.push(`${method} ${path}`)
    if (path.endsWith('/assemblies/7/parts') && method === 'GET') return json(rows)
    if (path.endsWith('/assemblies/7/spare-list-pages')) return json([])
    if (path.endsWith('/assemblies/7/parts') && method === 'POST') {
      const body = JSON.parse(String(init?.body)) as Record<string, unknown>
      rows = [{ ...body, id: 9, validation_status: 'INCOMPLETE', source_pages: [] }]
      return json(rows[0], 201)
    }
    if (path.endsWith('/assemblies/7/parts/import-preview')) return json({
      token: 'signed', source_digest: 'digest',
      rows: [{ row_number: 2, normalized: { position: '2', part_number: 'B', name_en: 'Valve' },
        status: 'WARNING', errors: [], warnings: ['catalog_part_import_unmapped'], resolved_visual_page_ids: [] }],
      summary: { total_rows: 1, valid_rows: 0, warning_rows: 1, error_rows: 0, duplicate_rows: 0 },
    })
    if (path.endsWith('/assemblies/7/parts/import-confirm')) {
      const body = JSON.parse(String(init?.body)) as Record<string, unknown>
      expect(body).toEqual({ token: 'signed', confirm_warnings: true })
      rows = [...rows, { id: 10, position: '2', part_number: 'B', name_en: 'Valve',
        validation_status: 'INCOMPLETE', source_pages: [] }]
      return json({ created_count: 1, part_ids: [10] })
    }
    return json({ detail: { code: 'unexpected' } }, 404)
  }))
  render(<I18nProvider><RevisionParts assemblyId={7} editable /></I18nProvider>)
  await actor.click(await screen.findByRole('button', { name: 'Добави част' }))
  await actor.type(screen.getByLabelText('Позиция *'), '1')
  await actor.type(screen.getByLabelText('Номер на част *'), 'A')
  await actor.type(screen.getByLabelText('Име EN'), 'Seal')
  await actor.click(screen.getByRole('button', { name: 'Запази' }))
  await screen.findByText('Seal')
  await actor.click(screen.getByRole('button', { name: 'Импорт CSV' }))
  await actor.upload(screen.getByLabelText('CSV UTF-8 файл'),
    new File(['position,part_number,name_en\n2,B,Valve\n'], 'parts.csv', { type: 'text/csv' }))
  expect(calls.some(call => call.includes('import-confirm'))).toBe(false)
  await actor.click(screen.getByRole('button', { name: 'Преглед' }))
  await screen.findByText('Няма изрично избрана изходна страница.')
  expect(calls.some(call => call.includes('import-confirm'))).toBe(false)
  await actor.click(screen.getByRole('button', { name: 'Потвърди импорта' }))
  await waitFor(() => expect(screen.getByText('Valve')).toBeInTheDocument())
  expect(calls.filter(call => call.includes('import-confirm'))).toHaveLength(1)
})
