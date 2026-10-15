import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, expect, it, vi } from 'vitest'
import { I18nProvider } from '../../i18n'
import { api, createApiObjectUrl } from '../../api'
import { FreeFormRequestModal, validRequestQuantity } from './FreeFormRequestModal'
import { requests01Bg, requests01En, requests01Ru } from './requestTranslations'

vi.mock('../../api', () => ({ api: vi.fn(), createApiObjectUrl: vi.fn() }))
beforeEach(() => { vi.clearAllMocks(); vi.spyOn(window, 'confirm').mockReturnValue(true) })

it('validates decimal input without binary-float arithmetic', () => {
  expect(validRequestQuantity('2,5', 'l')).toBe(true)
  expect(validRequestQuantity('0.75', 'kg')).toBe(true)
  expect(validRequestQuantity('7.5', 'm')).toBe(true)
  expect(validRequestQuantity('1.0', 'pcs')).toBe(true)
  for (const value of ['0', '-1', 'NaN', '1e6', '0.0000001']) expect(validRequestQuantity(value, 'l')).toBe(false)
  expect(validRequestQuantity('1.2', 'pcs')).toBe(false)
  expect(Object.keys(requests01Bg).sort()).toEqual(Object.keys(requests01En).sort())
  expect(Object.keys(requests01Bg).sort()).toEqual(Object.keys(requests01Ru).sort())
})

it('saves and previews a free-form draft with editable decimal rows and no machine', async () => {
  vi.mocked(api).mockResolvedValue({ id: 7 })
  vi.mocked(createApiObjectUrl).mockResolvedValue({ url: 'blob:qa-preview', mediaType: 'application/pdf' })
  URL.revokeObjectURL = vi.fn()
  render(<I18nProvider initialLocale="bg"><FreeFormRequestModal onClose={vi.fn()} onSaved={vi.fn()} /></I18nProvider>)
  fireEvent.change(screen.getByLabelText('Отдел / звено'), { target: { value: 'QA отдел' } })
  fireEvent.change(screen.getByLabelText('Наименование на артикул'), { target: { value: 'QA ред' } })
  fireEvent.change(screen.getByLabelText('Мерна единица'), { target: { value: 'l' } })
  fireEvent.change(screen.getByLabelText('Количество'), { target: { value: '2,5' } })
  fireEvent.click(screen.getByRole('button', { name: 'Добави ред' }))
  expect(screen.getAllByLabelText('Наименование на артикул')).toHaveLength(2)
  fireEvent.click(screen.getByRole('button', { name: /Премахни 2/ }))
  fireEvent.click(screen.getByRole('button', { name: 'Преглед на заявката' }))
  await waitFor(() => expect(createApiObjectUrl).toHaveBeenCalledWith('/part-requests/7/preview'))
  const options = vi.mocked(api).mock.calls[0][1]
  const body = JSON.parse(String(options?.body))
  expect(body.lines).toEqual([{ description: 'QA ред', quantity: '2.5', unit: 'l' }])
  expect(body).not.toHaveProperty('machine_id')
  expect(body.submit_for_approval).toBe(false)
  expect(screen.getByTitle('Преглед на заявката')).toBeInTheDocument()
})
