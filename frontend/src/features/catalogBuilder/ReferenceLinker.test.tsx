import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, expect, it, vi } from 'vitest'
import { api } from '../../api'
import { I18nProvider } from '../../i18n'
import ReferenceLinker from './ReferenceLinker'

vi.mock('../../api', () => ({ api: vi.fn() }))
vi.mock('../../AuthenticatedImage', () => ({ default: ({ alt }: { alt: string }) => <img alt={alt} /> }))
vi.mock('../../ui/workspace', () => ({ MachineSelect: ({ value, onChange, label }: { value: string; onChange: (value: string) => void; label: string }) => <select aria-label={label} value={value} onChange={event => onChange(event.target.value)}><option value="" /><option value="4">QA 4</option><option value="5">QA 5</option></select> }))
afterEach(() => { cleanup(); vi.clearAllMocks() })

it('requires exact pages, individually selected variants, multiple targets and explicit confirmation', async () => {
  const source = { source_id: 'QA_SOURCE', revision: 'PARTS_CATALOG_V2', title: 'QA source', pages: [
    { id: 1, role: 'EXPLODED_SCHEME', page_number: 1, preview_endpoint: '/qa/scheme' },
    { id: 2, role: 'SPARE_PARTS_LIST', page_number: 2, preview_endpoint: '/qa/list' },
  ] }
  vi.mocked(api).mockImplementation(async (path, init) => {
    if (init?.method === 'POST') return [] as never
    if (path === '/admin/catalog-builder/reference-sources') return [source] as never
    if (path.endsWith('/parts')) return [10, 11].map(id => ({ id, position: '1', part_number: `QA-${id}`, description: 'QA', valid_for_raw: `Variant ${id}` })) as never
    return { name: 'QA machine', inventory_number: path.split('/').at(-1) } as never
  })
  render(<I18nProvider><ReferenceLinker onClose={vi.fn()} /></I18nProvider>)
  const choose = async (label: string, option: RegExp) => { await userEvent.click(screen.getByRole('combobox', { name: label })); await userEvent.click(screen.getByRole('option', { name: option })) }
  for (const id of ['4', '5']) { await userEvent.selectOptions(screen.getByRole('combobox', { name: 'Целева машина' }), id); await userEvent.click(screen.getByRole('button', { name: 'Добави машина' })) }
  await choose('Публикуван източник / ревизия', /QA source/)
  await choose('Разглобена схема', /PDF страница 1/)
  await choose('Списък с резервни части', /PDF страница 2/)
  await userEvent.click(await screen.findByRole('checkbox', { name: '1 · QA-10' }))
  expect(screen.getByRole('checkbox', { name: '1 · QA-11' })).not.toBeChecked()
  await userEvent.type(screen.getByRole('textbox'), 'QA verified variants')
  expect(screen.getByRole('button', { name: 'Запази' })).toBeDisabled()
  await userEvent.click(screen.getByRole('checkbox', { name: /Проверих схемата/ }))
  await userEvent.click(screen.getByRole('button', { name: 'Запази' }))
  await waitFor(() => expect(screen.getByText('Референцията е свързана с одитна следа.')).toBeVisible())
  const post = vi.mocked(api).mock.calls.find(([, init]) => init?.method === 'POST')
  expect(JSON.parse(String(post?.[1]?.body))).toEqual({ machine_ids: [4, 5], scheme_id: 1, parts_list_id: 2, source_revision: 'PARTS_CATALOG_V2', part_ids: [10], reason: 'QA verified variants', compatibility_confirmed: true })
})
