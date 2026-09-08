import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import App from '../../App'
import { bg, I18nProvider } from '../../i18n'
import { machineIdFromPath } from './useMachineEntryRoute'
import { entryApi, entrySession, json, passportGets, stubEntryImages } from './machineEntryTestFixtures'

beforeEach(() => { localStorage.clear(); window.history.replaceState({}, '', '/'); stubEntryImages() })
afterEach(() => { cleanup(); window.history.replaceState({}, '', '/'); vi.unstubAllGlobals(); vi.restoreAllMocks() })
function open(path = '/machine/13') { window.history.replaceState({}, '', path); return render(<I18nProvider initialLocale="bg"><App /></I18nProvider>) }
const dialog = (id = 13) => screen.findByRole('dialog', { name: `Цифров паспорт · машина №${id}` })
async function login() {
  fireEvent.change(await screen.findByLabelText(bg['login.email']), { target: { value: 'entry-test@example.invalid' } })
  fireEvent.change(screen.getByLabelText(bg['login.password']), { target: { value: 'test-only-login' } })
  await userEvent.click(screen.getByRole('button', { name: bg['login.signIn'] }))
}

describe('machine entry route parsing', () => {
  it.each([['/machine/13', 13], ['/machine/13/', 13], ['/machine/0013', 13], ['/machine/9', 9], ['/machine/foo', null], ['/machine/-1', null], ['/machine/0', null], ['/machine/abc123', null], ['/machine/13/extra', null], ['/machine/9007199254740993', null], ['/machine/1e3', null], ['/', null]])('%s → %s', (path, id) => expect(machineIdFromPath(path)).toBe(id))
})

it('waits for session bootstrap before any passport GET, then opens the exact direct target and supports refresh startup', async () => {
  let resolve!: (value: Response) => void
  const pending = new Promise<Response>((done) => { resolve = done })
  const fetchMock = entryApi({ intercept: (path) => path === '/api/auth/me' ? pending.then((response) => response.clone()) : undefined })
  const mounted = open('/machine/13/')
  expect(passportGets(fetchMock)).toHaveLength(0)
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  await act(async () => resolve(json(entrySession())))
  expect(await dialog()).toBeVisible()
  expect(window.location.pathname).toBe('/machine/13')
  mounted.unmount()
  render(<I18nProvider initialLocale="bg"><App /></I18nProvider>)
  expect(await dialog()).toBeVisible()
  expect(passportGets(fetchMock).map(([url]) => url)).toEqual(['/api/machines/13/passport', '/api/machines/13/passport'])
})

it('retains unauthenticated machine intent after the real Login component succeeds, without storing it', async () => {
  const fetchMock = entryApi({ loggedOut: true })
  open()
  await screen.findByRole('button', { name: bg['login.signIn'] })
  expect(passportGets(fetchMock)).toHaveLength(0)
  await login()
  expect(await dialog()).toBeVisible()
  expect(window.location.pathname).toBe('/machine/13')
  expect(Object.values(localStorage)).not.toContain('/machine/13')
  expect(sessionStorage.length).toBe(0)
})

it.each(['password', 'profile'] as const)('retains the exact target through mandatory %s completion, never mounting a passport early', async (gate) => {
  const user = { ...entrySession(), must_change_password: gate === 'password', profile_status: gate === 'profile' ? 'PROFILE_INCOMPLETE' as const : 'PROFILE_COMPLETE' as const }
  const fetchMock = entryApi({ user, loggedOut: true })
  open()
  await login()
  if (gate === 'password') {
    await screen.findByText(bg['password.forcedTitle'])
    expect(passportGets(fetchMock)).toHaveLength(0)
    for (const key of ['password.current', 'password.new', 'password.confirm'] as const) fireEvent.change(screen.getByLabelText(bg[key]), { target: { value: 'Test-only-value-123!' } })
    await userEvent.click(screen.getByRole('button', { name: bg['password.submit'] }))
  } else {
    await screen.findByText(bg['profile.completeTitle'])
    expect(passportGets(fetchMock)).toHaveLength(0)
    await userEvent.click(screen.getByRole('button', { name: bg['profile.confirm'] }))
  }
  expect(await dialog()).toBeVisible()
  expect(passportGets(fetchMock)).toHaveLength(1)
  expect(window.location.pathname).toBe('/machine/13')
})

it('closes a direct entry safely by replacing the route, never traversing unknown external history', async () => {
  entryApi()
  const go = vi.spyOn(window.history, 'go')
  open()
  await userEvent.click(within(await dialog()).getByRole('button', { name: bg['common.close'] }))
  expect(window.location.pathname).toBe('/')
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  expect(go).not.toHaveBeenCalled()
  await waitFor(() => expect(document.querySelector('[data-shell-focus]')).toHaveFocus())
  expect(screen.getByRole('button', { name: bg['nav.machines'] })).toBeVisible()
})

it('synchronizes Machines and Global Search with URL, Back/Forward and another target; internal close restores the shell', async () => {
  entryApi()
  open('/')
  await userEvent.click(await screen.findByRole('button', { name: bg['nav.machines'] }))
  const row = (await screen.findByText('Test-only machine 13')).closest('tr')!
  await userEvent.click(within(row).getByRole('button', { name: bg['passport.tab.passport'] }))
  await dialog()
  expect(window.location.pathname).toBe('/machine/13')
  act(() => window.history.back())
  await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
  expect(window.location.pathname).toBe('/')
  act(() => window.history.forward())
  await dialog()
  expect(window.location.pathname).toBe('/machine/13')
  await userEvent.type(screen.getByLabelText(bg['global.search']), 'test')
  await userEvent.click(await screen.findByRole('button', { name: /Test-only machine 9/ }))
  await dialog(9)
  expect(window.location.pathname).toBe('/machine/9')
  expect(screen.queryByRole('dialog', { name: /№13/ })).not.toBeInTheDocument()
  await userEvent.click(within(await dialog(9)).getByRole('button', { name: bg['common.close'] }))
  await waitFor(() => expect(window.location.pathname).toBe('/'))
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  expect(screen.getByLabelText(bg['global.search'])).toHaveValue('test')
})

it('contains an unknown numeric target, localizes its error, stops loading and offers recovery', async () => {
  const fetchMock = entryApi()
  open('/machine/999999')
  expect(await screen.findByRole('alert')).toHaveTextContent(bg['entry.notFound'])
  expect(screen.queryByText('opaque-not-found')).not.toBeInTheDocument()
  const modal = screen.getByRole('dialog')
  expect(within(modal).queryByRole('status')).not.toBeInTheDocument()
  expect(passportGets(fetchMock).map(([url]) => url)).toEqual(['/api/machines/999999/passport'])
  await userEvent.click(screen.getByRole('button', { name: bg['entry.recover'] }))
  expect(window.location.pathname).toBe('/')
})

it.each(['/machine/foo', '/machine/-1', '/machine/abc123', '/machine/0'])('normalizes malformed %s without fetching any machine passport', async (path) => {
  const fetchMock = entryApi()
  open(path)
  await screen.findByRole('button', { name: bg['nav.machines'] })
  expect(window.location.pathname).toBe('/')
  expect(passportGets(fetchMock)).toHaveLength(0)
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
})
