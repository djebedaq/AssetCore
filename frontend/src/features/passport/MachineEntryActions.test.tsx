import { act, cleanup, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import App from '../../App'
import { bg, en, ru, I18nProvider } from '../../i18n'
import type { MachinePassport } from '../../types'
import { entryApi, entryAvailability, entryPassport, entryRepair, entrySession, json, mutations, stubEntryImages } from './machineEntryTestFixtures'

beforeEach(() => { localStorage.clear(); window.history.replaceState({}, '', '/machine/13'); stubEntryImages() })
afterEach(() => { cleanup(); window.history.replaceState({}, '', '/'); vi.unstubAllGlobals(); vi.restoreAllMocks() })
function start() { return render(<I18nProvider initialLocale="bg"><App /></I18nProvider>) }
const passportDialog = () => screen.findByRole('dialog', { name: /Цифров паспорт · машина №13/ })
function issuedPassport(id: number) {
  const value = entryPassport(id)
  value.machine.status = 'ISSUED'
  value.current_state.available = false
  value.current_state.allowed_actions = { issue: false, return: true, repair: false, edit: false }
  return value
}
const issuedAvailability = (id = 13) => ({ ...entryAvailability(id), available: false, returnable: true, active_transfer_id: 101, status: 'ISSUED', protocol_number: 'TEST-ISSUE' })

it.each(['issue', 'return'] as const)('%s uses the existing workflow once, waits for current availability, selects the exact target and does not POST', async (action) => {
  let resolve!: (value: Response) => void
  const pending = new Promise<Response>((done) => { resolve = done })
  const available = action === 'issue' ? [entryAvailability(13), entryAvailability(9)] : [issuedAvailability(13), { ...issuedAvailability(9), active_transfer_id: 102 }]
  const fetchMock = entryApi({ passport: action === 'return' ? issuedPassport : entryPassport, intercept: (path) => path === '/api/transfers/availability' ? pending.then((response) => response.clone()) : undefined })
  start()
  await userEvent.click(within(await passportDialog()).getByRole('button', { name: bg[`entry.${action}`] }))
  expect(window.location.pathname).toBe('/')
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  expect(mutations(fetchMock)).toHaveLength(0)
  await act(async () => resolve(json(available)))
  const modal = await screen.findByRole('dialog', { name: bg[`bulk.${action}`] })
  expect(screen.getAllByRole('dialog')).toHaveLength(1)
  await waitFor(() => expect(modal.contains(document.activeElement)).toBe(true))
  const checkboxes = within(modal).getAllByRole('checkbox').filter((item) => item.getAttribute('aria-label')?.includes('13') || item.getAttribute('aria-label')?.includes('9'))
  expect(checkboxes).toHaveLength(2)
  expect(checkboxes[0]).toBeChecked()
  expect(checkboxes[1]).not.toBeChecked()
  expect(within(modal).getByText('Избрани машини: 1')).toBeVisible()
  expect(mutations(fetchMock)).toHaveLength(0)
  await userEvent.click(within(modal).getByRole('button', { name: bg['common.close'] }))
  await userEvent.click(screen.getByRole('button', { name: bg['nav.machines'] }))
  await userEvent.click(screen.getByRole('button', { name: bg['nav.transfers'] }))
  await waitFor(() => expect(fetchMock.mock.calls.filter(([url]) => url === '/api/transfers/availability')).toHaveLength(2))
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  expect(mutations(fetchMock)).toHaveLength(0)
})

it.each(['issue', 'return'] as const)('%s never force-selects stale passport eligibility or falls back to another machine', async (action) => {
  const current = action === 'issue' ? [{ ...entryAvailability(13), available: false }, entryAvailability(9)] : [{ ...issuedAvailability(13), returnable: false }, issuedAvailability(9)]
  const fetchMock = entryApi({ passport: action === 'return' ? issuedPassport : entryPassport, availability: current })
  start()
  await userEvent.click(within(await passportDialog()).getByRole('button', { name: bg[`entry.${action}`] }))
  const modal = await screen.findByRole('dialog', { name: bg[`bulk.${action}`] })
  expect(within(modal).getByText(bg['entry.targetUnavailable'])).toBeVisible()
  expect(within(modal).getByText('Избрани машини: 0')).toBeVisible()
  for (const checkbox of within(modal).getAllByRole('checkbox')) expect(checkbox).not.toBeChecked()
  expect(within(modal).getByRole('button', { name: bg['bulk.reviewConfirm'] })).toBeDisabled()
  expect(mutations(fetchMock)).toHaveLength(0)
})

it('consumes a new issue target independently when opening a different machine, without retaining the old selection', async () => {
  const fetchMock = entryApi()
  start()
  await userEvent.click(within(await passportDialog()).getByRole('button', { name: bg['entry.issue'] }))
  await userEvent.click(within(await screen.findByRole('dialog', { name: bg['bulk.issue'] })).getByRole('button', { name: bg['common.close'] }))
  await userEvent.click(screen.getByRole('button', { name: bg['nav.machines'] }))
  const row = (await screen.findByText('Test-only machine 9')).closest('tr')!
  await userEvent.click(within(row).getByRole('button', { name: bg['passport.tab.passport'] }))
  const next = await screen.findByRole('dialog', { name: /Цифров паспорт · машина №9/ })
  await userEvent.click(within(next).getByRole('button', { name: bg['entry.issue'] }))
  const modal = await screen.findByRole('dialog', { name: bg['bulk.issue'] })
  expect(within(modal).getByLabelText('Машина №9')).toBeChecked()
  expect(within(modal).getByLabelText('Машина №13')).not.toBeChecked()
  expect(mutations(fetchMock)).toHaveLength(0)
})

it('starts the existing repair form with the exact machine and empty problem fields, then consumes the entry', async () => {
  const fetchMock = entryApi()
  start()
  await userEvent.click(within(await passportDialog()).getByRole('button', { name: bg['entry.startRepair'] }))
  const modal = await screen.findByRole('dialog', { name: bg['repairs.acceptTitle'] })
  await waitFor(() => expect(modal.contains(document.activeElement)).toBe(true))
  expect(window.location.pathname).toBe('/')
  expect(screen.getAllByRole('dialog')).toHaveLength(1)
  expect(within(modal).getByLabelText(bg['repairs.machine'])).toHaveValue('13')
  expect(within(modal).getByLabelText(bg['repairs.reportedProblem'])).toHaveValue('')
  expect(within(modal).getByLabelText(bg['repairCase.conditionBefore'])).toHaveValue('')
  expect(mutations(fetchMock)).toHaveLength(0)
  await userEvent.click(within(modal).getByRole('button', { name: bg['common.close'] }))
  await userEvent.click(screen.getByRole('button', { name: bg['nav.machines'] }))
  await userEvent.click(screen.getByRole('button', { name: bg['nav.repairs'] }))
  await waitFor(() => expect(fetchMock.mock.calls.filter(([url]) => url === '/api/repair-cases')).toHaveLength(2))
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
})

it.each(['ISSUED', 'REPAIR', 'inactive', 'missing'])('does not force a stale repair-create target (%s) into the current eligible set', async (state) => {
  const fetchMock = entryApi({ intercept: (path) => path === '/api/machines' ? json(state === 'missing' ? [] : [{ ...entryPassport().machine, status: state === 'inactive' ? 'READY' : state, is_active: state !== 'inactive' }]) : undefined })
  start()
  await userEvent.click(within(await passportDialog()).getByRole('button', { name: bg['entry.startRepair'] }))
  expect(await screen.findByText(bg['entry.targetUnavailable'])).toBeVisible()
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  expect(mutations(fetchMock)).toHaveLength(0)
})

function repairPassport(id: number): MachinePassport {
  const value = entryPassport(id)
  value.current_state.active_repair = { id: 41, repair_reference: 'TEST-REPAIR-41', status: 'ACCEPTED', reported_problem: 'Test-only problem', opened_at: '2026-09-01T00:00:00Z' }
  value.current_state.allowed_actions.repair = false
  return value
}
it('opens only the exact validated active repair workspace, consumes the intent and never creates another repair', async () => {
  const fetchMock = entryApi({ passport: repairPassport, repairs: [entryRepair()] })
  start()
  const passport = await passportDialog()
  expect(within(passport).queryByRole('button', { name: bg['entry.startRepair'] })).not.toBeInTheDocument()
  await userEvent.click(within(passport).getByRole('button', { name: bg['entry.openRepair'] }))
  const modal = await screen.findByRole('dialog', { name: 'TEST-REPAIR-41' })
  await waitFor(() => expect(modal.contains(document.activeElement)).toBe(true))
  expect(window.location.pathname).toBe('/')
  expect(fetchMock.mock.calls.some(([url]) => url === '/api/repair-cases/41')).toBe(true)
  expect(mutations(fetchMock)).toHaveLength(0)
  await userEvent.click(within(modal).getByRole('button', { name: bg['common.close'] }))
  await userEvent.click(screen.getByRole('button', { name: bg['nav.machines'] }))
  await userEvent.click(screen.getByRole('button', { name: bg['nav.repairs'] }))
  await waitFor(() => expect(fetchMock.mock.calls.filter(([url]) => url === '/api/repair-cases')).toHaveLength(2))
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
})

it.each(['missing', 'wrong-machine', 'completed'])('rejects a stale active repair handoff (%s) without guessing another record', async (state) => {
  const repairs = state === 'missing' ? [] : [{ ...entryRepair(state === 'wrong-machine' ? 9 : 13), status: state === 'completed' ? 'COMPLETED' : 'ACCEPTED' }]
  const fetchMock = entryApi({ passport: repairPassport, repairs })
  start()
  await userEvent.click(within(await passportDialog()).getByRole('button', { name: bg['entry.openRepair'] }))
  expect(await screen.findByText(bg['entry.targetUnavailable'])).toBeVisible()
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  expect(mutations(fetchMock)).toHaveLength(0)
})

it('switches existing Protocols/Files tabs without downloading/uploading, and hands the same machine to the existing catalog', async () => {
  const fetchMock = entryApi()
  start()
  const modal = await passportDialog()
  const actions = within(modal).getByRole('region', { name: bg['entry.quickActions'] })
  await userEvent.click(within(actions).getByRole('button', { name: bg['passport.tab.protocols'] }))
  expect(within(modal).getByRole('tab', { name: bg['passport.tab.protocols'] })).toHaveAttribute('aria-selected', 'true')
  await userEvent.click(within(actions).getByRole('button', { name: bg['passport.tab.files'] }))
  expect(within(modal).getByRole('tab', { name: bg['passport.tab.files'] })).toHaveAttribute('aria-selected', 'true')
  expect(within(modal).getByRole('button', { name: bg['passport.addFile'] })).toBeVisible()
  expect(fetchMock.mock.calls.some(([url]) => String(url).includes('/download'))).toBe(false)
  await userEvent.click(within(actions).getByRole('button', { name: bg['nav.catalog'] }))
  await waitFor(() => expect(screen.getByLabelText(bg['catalog.chooseMachine'])).toHaveValue('13'))
  expect(window.location.pathname).toBe('/')
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  await screen.findByText('Test-only unsupported catalog')
  expect(mutations(fetchMock)).toHaveLength(0)
})

it.each(['administrator', 'director', 'mechanic', 'observer'] as const)('keeps %s on its existing permissions; allowed_actions=false never becomes a mutation shortcut', async (role) => {
  const fetchMock = entryApi({ user: entrySession(role), passport: (id) => { const value = entryPassport(id); value.current_state.allowed_actions = { issue: false, return: false, repair: false, edit: false }; return value } })
  start()
  const modal = await passportDialog()
  for (const key of ['entry.issue', 'entry.return', 'entry.startRepair'] as const) expect(within(modal).queryByRole('button', { name: bg[key] })).not.toBeInTheDocument()
  if (role === 'observer') {
    expect(within(modal).queryByRole('region', { name: bg['entry.quickActions'] })).not.toBeInTheDocument()
    expect(within(modal).queryByRole('tablist')).not.toBeInTheDocument()
    expect(within(modal).queryByRole('img')).not.toBeInTheDocument()
    expect(fetchMock.mock.calls.some(([url]) => String(url).includes('/timeline') || String(url).endsWith('/qr'))).toBe(false)
  }
  expect(mutations(fetchMock)).toHaveLength(0)
})

it('clearly marks inactive assets without removing history/protocol tabs or exposing new mutation shortcuts', async () => {
  const fetchMock = entryApi({ passport: (id) => { const value = entryPassport(id); value.machine.is_active = false; value.current_state.available = false; value.current_state.allowed_actions.return = true; return value } })
  start()
  const modal = await passportDialog()
  expect(within(modal).getByText(bg['entry.inactive'])).toBeVisible()
  expect(within(modal).getByRole('tab', { name: bg['passport.tab.history'] })).toBeVisible()
  expect(within(modal).getByRole('tab', { name: bg['passport.tab.protocols'] })).toBeVisible()
  for (const key of ['entry.issue', 'entry.return', 'entry.startRepair', 'passport.tab.files'] as const) expect(within(modal).queryByRole('button', { name: bg[key] })).not.toBeInTheDocument()
  expect(mutations(fetchMock)).toHaveLength(0)
})

it('has explicit BG/EN/RU entry translations with key parity and no raw fallback', () => {
  const keys = Object.keys(bg).filter((key) => key.startsWith('entry.')) as Array<keyof typeof bg>
  expect(keys.length).toBe(9)
  for (const key of keys) { expect(en[key]).toBeTruthy(); expect(ru[key]).toBeTruthy(); expect(en[key]).not.toBe(bg[key]); expect(ru[key]).not.toBe(bg[key]) }
})

it.each(['administrator', 'director', 'mechanic'] as const)('shows allowed entry actions for %s without deriving authority from the role name', async (role) => {
  entryApi({ user: entrySession(role) })
  start()
  const modal = await passportDialog()
  expect(within(modal).getByRole('button', { name: bg['entry.issue'] })).toBeVisible()
  expect(within(modal).getByRole('button', { name: bg['entry.startRepair'] })).toBeVisible()
  expect(within(modal).queryByRole('button', { name: bg['entry.return'] })).not.toBeInTheDocument()
})

it('requires workflow navigation permission even when a stale passport claims allowed actions', async () => {
  entryApi({ user: { ...entrySession(), permissions: ['assets.view'] } })
  start()
  const modal = await passportDialog()
  for (const key of ['entry.issue', 'entry.return', 'entry.startRepair', 'entry.openRepair', 'nav.catalog'] as const) expect(within(modal).queryByRole('button', { name: bg[key] })).not.toBeInTheDocument()
})
