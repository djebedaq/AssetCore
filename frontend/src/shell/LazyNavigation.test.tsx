import { act, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, expect, it, vi } from 'vitest'
import App from '../App'
import { I18nProvider } from '../i18n'

const gate = vi.hoisted(() => {
  let release!: () => void
  return { started: vi.fn(), promise: new Promise<void>((resolve) => { release = resolve }), release: () => release() }
})
vi.mock('../features/reports/Reports', async (original) => {
  gate.started()
  await gate.promise
  return original()
})
afterEach(() => vi.unstubAllGlobals())

it('loads reports only on selection; navigating away from a pending import does not resurrect it', async () => {
  vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
    const path = String(input)
    const value = path.endsWith('/auth/me') ? {
      id: 1, role: 'director', preferred_language: 'bg', permissions: ['assets.view', 'audit.view_operational'],
      is_active: true, is_system_owner: false, must_change_password: false,
    } : path.endsWith('/emergency-access/status') ? { active: false } : []
    return new Response(JSON.stringify(value), { headers: { 'Content-Type': 'application/json' } })
  }))
  render(<I18nProvider initialLocale="bg"><App /></I18nProvider>)
  const reportButton = await screen.findByRole('button', { name: 'Отчети' })
  expect(gate.started).not.toHaveBeenCalled()
  await userEvent.click(reportButton)
  expect(await screen.findByRole('status')).toHaveTextContent('Зареждане')
  await userEvent.click(screen.getByRole('button', { name: 'Журнал' }))
  expect(await screen.findByRole('button', { name: 'Експорт на одита' })).toBeVisible()
  await act(async () => { gate.release(); await gate.promise })
  expect(screen.getByRole('button', { name: 'Експорт на одита' })).toBeVisible()
  expect(screen.queryByRole('button', { name: /Изтегли дневен/ })).not.toBeInTheDocument()
  await userEvent.click(reportButton)
  expect(await screen.findByRole('button', { name: /Изтегли дневен/ })).toBeVisible()
  expect(gate.started).toHaveBeenCalledTimes(1)
})
