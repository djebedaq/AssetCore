import { act, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, expect, it, vi } from 'vitest'
import { I18nProvider } from '../../i18n'
import { ProposalDialog } from './ProposalDialog'
import type { StudioTemplate, StudioVersion } from './shared'

const template: StudioTemplate = { id: 4, code: 'QA', document_type: 'PART_REQUEST', name_bg: 'QA шаблон', name_en: 'QA', name_ru: 'QA', authoring_supported: true, versions: [] }
const version = { id: 19, version: 7, language: 'bg' } as StudioVersion
const json = (value: unknown, status = 200) => new Response(JSON.stringify(value), { status, headers: { 'Content-Type': 'application/json' } })
afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks() })

it('submits only proposal text and exact target and waits for server persistence', async () => {
  let complete!: (response: Response) => void
  const fetch = vi.fn(async () => new Promise<Response>(resolve => { complete = resolve }))
  vi.stubGlobal('fetch', fetch)
  const submitted = vi.fn()
  render(<I18nProvider initialLocale="bg"><ProposalDialog template={template} version={version} submitted={submitted} close={vi.fn()} /></I18nProvider>)
  expect(screen.getByText(/QA шаблон/)).toBeVisible()
  expect(screen.getByRole('button', { name: 'Изпрати предложение' })).toBeDisabled()
  await userEvent.type(screen.getByLabelText('Заглавие на предложението'), 'Синтетична промяна')
  await userEvent.type(screen.getByLabelText('Подробно описание'), 'Преместете номера под заглавието на документа.')
  await userEvent.click(screen.getByRole('button', { name: 'Изпрати предложение' }))
  expect(submitted).not.toHaveBeenCalled()
  const init = (fetch.mock.calls as unknown as [string, RequestInit][])[0][1]
  expect(JSON.parse(String(init.body))).toEqual({ template_id: 4, target_version_id: 19, language: 'bg', title: 'Синтетична промяна', description: 'Преместете номера под заглавието на документа.', attachments: [] })
  await act(async () => complete(json({ id: 22 }, 201)))
  await waitFor(() => expect(submitted).toHaveBeenCalledWith(22))
})

it('preserves description on failure and does not show successful submission', async () => {
  vi.stubGlobal('fetch', vi.fn(async () => json({ detail: { code: 'studio_invalid' } }, 422)))
  const submitted = vi.fn()
  render(<I18nProvider initialLocale="bg"><ProposalDialog template={template} version={version} submitted={submitted} close={vi.fn()} /></I18nProvider>)
  await userEvent.type(screen.getByLabelText('Заглавие на предложението'), 'QA промяна')
  await userEvent.type(screen.getByLabelText('Подробно описание'), 'Описание, което трябва да се запази при грешка.')
  await userEvent.click(screen.getByRole('button', { name: 'Изпрати предложение' }))
  expect(await screen.findByRole('alert')).toBeVisible()
  expect(screen.getByLabelText('Подробно описание')).toHaveValue('Описание, което трябва да се запази при грешка.')
  expect(submitted).not.toHaveBeenCalled()
})
