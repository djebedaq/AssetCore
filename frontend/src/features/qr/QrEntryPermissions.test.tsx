import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import App from '../../App'
import { bg, I18nProvider } from '../../i18n'
import { entryApi, entrySession, mutations, stubEntryImages } from '../passport/machineEntryTestFixtures'

beforeEach(() => { localStorage.clear(); window.history.replaceState({}, '', '/'); stubEntryImages() })
afterEach(() => { cleanup(); vi.unstubAllGlobals(); vi.restoreAllMocks() })

it('keeps authenticated QR image endpoints after explicit category selection', async () => {
  const fetchMock = entryApi()
  render(<I18nProvider initialLocale="bg"><App /></I18nProvider>)
  await userEvent.click(await screen.findByRole('button', { name: bg['nav.qr'] }))
  await userEvent.click(await screen.findByRole('button', { name: /Водоструйни машини.*2/ }))
  await waitFor(() => expect(screen.getAllByRole('img', { name: /QR/ })).toHaveLength(2))
  await waitFor(() => expect(fetchMock.mock.calls.filter(([url]) => String(url).endsWith('/qr')).map(([url]) => url).sort()).toEqual(['/api/machines/13/qr', '/api/machines/9/qr']))
  for (const image of screen.getAllByRole('img', { name: /QR/ })) expect(image.getAttribute('src')).toBe('blob:test-only')
  expect(mutations(fetchMock)).toHaveLength(0)
})

it('does not add QR navigation or QR requests for Observer', async () => {
  const fetchMock = entryApi({ user: entrySession('observer') })
  render(<I18nProvider initialLocale="bg"><App /></I18nProvider>)
  await screen.findByRole('button', { name: bg['nav.machines'] })
  expect(screen.queryByRole('button', { name: bg['nav.qr'] })).not.toBeInTheDocument()
  expect(fetchMock.mock.calls.some(([url]) => String(url).endsWith('/qr'))).toBe(false)
})
