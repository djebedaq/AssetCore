import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { api, createApiObjectUrl } from '../../api'
import { I18nProvider } from '../../i18n'
import QrCodes from './QrCodes'

vi.mock('../../api', () => ({ api: vi.fn(), createApiObjectUrl: vi.fn() }))
vi.mock('../../AuthenticatedImage', () => ({ default: ({ src, alt }: { src: string; alt: string }) => <img src={src} alt={alt} /> }))
const machines = Array.from({ length: 27 }, (_, index) => ({ id: index + 1, inventory_number: String(index + 1), name: `QA ${index + 1}`, brand: 'QA', category_id: 1 }))
const page = (items: typeof machines, total = items.length) => ({ items, total, page: 1, page_size: 24, total_pages: 2, has_next: total > items.length, has_previous: false })

beforeEach(() => {
  vi.mocked(api).mockImplementation(async path => {
    if (path === '/machines/category-navigation') return [{ id: 1, code: 'QA_A', name_bg: 'QA A', asset_count: 27 }, { id: 2, code: 'QA_B', name_bg: 'QA B', asset_count: 1 }] as never
    const url = new URL(path, 'http://qa.invalid')
    if (url.searchParams.get('category_id') === '2') return page([{ ...machines[0], id: 100, name: 'QA B only' }]) as never
    return page(url.searchParams.get('page_size') === '100' ? machines : machines.slice(0, 24), 27) as never
  })
  vi.mocked(createApiObjectUrl).mockImplementation(async path => ({ url: `blob:${path}`, mediaType: 'image/png' }))
  vi.stubGlobal('Image', class { src = ''; decode() { return Promise.resolve() } })
  vi.spyOn(URL, 'revokeObjectURL').mockImplementation(() => undefined)
  vi.spyOn(window, 'print').mockImplementation(() => undefined)
})
afterEach(() => { cleanup(); vi.unstubAllGlobals(); vi.restoreAllMocks(); vi.clearAllMocks() })

it('loads category counts first and no machine images until an explicit category choice', async () => {
  render(<I18nProvider><QrCodes /></I18nProvider>)
  expect(await screen.findByRole('button', { name: 'QA A 27' })).toBeVisible()
  expect(api).toHaveBeenCalledTimes(1)
  expect(screen.queryAllByRole('img')).toHaveLength(0)
  expect(screen.getByRole('button', { name: 'Печат на QR етикети (0)' })).toBeDisabled()
  await userEvent.click(screen.getByRole('button', { name: 'QA B 1' }))
  expect(await screen.findByText('QA B only')).toBeVisible()
  expect(screen.getAllByRole('img')).toHaveLength(1)
  expect(screen.queryByText('QA 1')).not.toBeInTheDocument()
})

it('prints the entire selected category after every authenticated image has decoded', async () => {
  render(<I18nProvider><QrCodes /></I18nProvider>)
  await userEvent.click(await screen.findByRole('button', { name: 'QA A 27' }))
  await screen.findByText('QA 24')
  expect(screen.queryByText('QA 27')).not.toBeInTheDocument()
  await userEvent.click(screen.getByRole('button', { name: 'Печат на QR етикети (27)' }))
  await waitFor(() => expect(window.print).toHaveBeenCalledOnce())
  expect(createApiObjectUrl).toHaveBeenCalledTimes(27)
  expect(document.querySelectorAll('.qr-print-grid .qr-card')).toHaveLength(27)
  expect(document.querySelector('.qr-print-grid')?.textContent).not.toContain('QA B only')
})

it('refuses printing when any authenticated QR image fails', async () => {
  vi.mocked(createApiObjectUrl).mockRejectedValue(new Error('QA unauthorized image'))
  render(<I18nProvider><QrCodes /></I18nProvider>)
  await userEvent.click(await screen.findByRole('button', { name: 'QA A 27' }))
  await screen.findByText('QA 1')
  await userEvent.click(screen.getByRole('button', { name: 'Печат на QR етикети (27)' }))
  expect(await screen.findByRole('alert')).toBeVisible()
  expect(window.print).not.toHaveBeenCalled()
  expect(document.querySelector('.qr-print-grid')).toBeNull()
})
