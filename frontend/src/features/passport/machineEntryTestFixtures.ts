// Isolated frontend HTTP fixtures, never production or seed records.
import { vi } from 'vitest'
import type { MachinePassport, RepairCase, TransferAvailability, UserSession } from '../../types'
import { passport } from './passportTestFixtures'

export const entrySession = (role: UserSession['role'] = 'administrator'): UserSession => ({
  id: 1, email: 'entry-test@example.invalid', full_name: 'Test Only Actor', first_name: 'Test', middle_name: 'Only', last_name: 'Actor', job_title: 'QA',
  role, preferred_language: 'bg', is_active: true, is_system_owner: false, must_change_password: false, profile_status: 'PROFILE_COMPLETE',
  permissions: role === 'observer' ? ['assets.view'] : ['assets.view', 'transfers.view', 'transfers.create', 'transfers.return', 'repairs.view', 'repairs.create', 'repairs.edit', 'parts.view', 'documents.view', 'documents.generate'],
  created_at: '2026-09-01T00:00:00Z', updated_at: '2026-09-01T00:00:00Z',
})

export function entryPassport(id = 13): MachinePassport {
  return {
    ...passport, limited_view: false, machine: { ...passport.machine, id, inventory_number: String(id), name: `Test-only machine ${id}`, status: 'READY', is_active: true },
    current_state: { ...passport.current_state, available: true, active_transfer: null, active_repair: null, last_transfer: null, last_completed_repair: null,
      pending_part_requests: { count: 0, latest_request_reference: null }, allowed_actions: { issue: true, return: false, repair: true, edit: false } },
    attachments: [], history: [], repairs: [], transfers: [], part_requests: [], parts_used: [], generated_documents: [], official_documents: [], technical_documents: [], audit: [], audit_visible: false,
    qr_endpoint: `/machines/${id}/qr`,
  }
}
export function entryRepair(machineId = 13, id = 41): RepairCase {
  return { id, machine_id: machineId, machine_number: String(machineId), machine_name: `Test-only machine ${machineId}`, repair_reference: `TEST-REPAIR-${id}`, reported_problem: 'Test-only problem', condition_before: 'Test-only condition', status: 'ACCEPTED', total_work_minutes: 0, participant_total_minutes: 0, cleaning_required: false, test_required: true, participants: [], events: [], parts_used: [], attachments: [], generated_documents: [], opened_at: '2026-09-01T00:00:00Z' }
}
export function entryAvailability(id = 13): TransferAvailability {
  return { machine_id: id, machine_number: String(id), brand: 'Test-only', pressure_bar: 500, status: 'READY', available: true, returnable: false }
}
export const json = (value: unknown, status = 200) => new Response(JSON.stringify(value), { status, headers: { 'Content-Type': 'application/json' } })
export function entryApi(options: {
  user?: UserSession
  loggedOut?: boolean
  passport?: (id: number) => MachinePassport
  availability?: TransferAvailability[]
  repairs?: RepairCase[]
  intercept?: (path: string, init: RequestInit) => Response | Promise<Response> | undefined
} = {}) {
  const user = options.user || entrySession()
  const machinePassport = options.passport || entryPassport
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init: RequestInit = {}) => {
    const path = String(input)
    const intercepted = options.intercept?.(path, init)
    if (intercepted) return intercepted
    if (path === '/api/auth/me') return options.loggedOut ? json({}, 401) : json(user)
    if (path === '/api/auth/login') return json({ user })
    if (path === '/api/auth/change-password') return json({ user: { ...user, must_change_password: false } })
    if (path === '/api/users/me/profile') return json({ ...user, profile_status: 'PROFILE_COMPLETE' })
    if (path === '/api/emergency-access/status') return json({ active: false })
    if (path === '/api/dashboard') return json({ total_machines: 2, ready: 2, in_use: 0, open_repairs: 0, pending_parts: 0, status_breakdown: {}, recent_repairs: [] })
    if (path === '/api/machines') return json([machinePassport(13).machine, machinePassport(9).machine])
    const match = /^\/api\/machines\/(\d+)\/passport$/.exec(path)
    if (match) {
      const id = Number(match[1])
      if (![13, 9].includes(id)) return json({ detail: 'opaque-not-found' }, 404)
      const value = machinePassport(id)
      return json(user.role === 'observer' ? { ...value, limited_view: true, qr_endpoint: null, current_state: { available: value.current_state.available, allowed_actions: { issue: false, return: false, repair: false, edit: false } } } : value)
    }
    if (path.endsWith('/qr')) return new Response(new Blob(['test-image'], { type: 'image/png' }))
    if (path === '/api/transfers/availability') return json(options.availability || [entryAvailability(13), entryAvailability(9)])
    if (path === '/api/repair-cases') return json(options.repairs || [])
    const repair = options.repairs?.find((item) => path === `/api/repair-cases/${item.id}`)
    if (repair) return json(repair)
    if (path.includes('/catalog/v2/machines/')) return json({ machine_id: 13, supported: false, message: 'Test-only unsupported catalog', assemblies: [] })
    if (path.includes('/search?')) return json({ machines: [machinePassport(9).machine], parts: [], documents: [], repairs: [], part_requests: [], transfers: [], generated_documents: [] })
    return json([])
  })
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}
export const passportGets = (fetchMock: ReturnType<typeof entryApi>) => fetchMock.mock.calls.filter(([url]) => String(url).endsWith('/passport'))
export const mutations = (fetchMock: ReturnType<typeof entryApi>) => fetchMock.mock.calls.filter(([, init]) => ['POST', 'PUT', 'PATCH', 'DELETE'].includes(init?.method || 'GET'))
export function stubEntryImages() {
  const NativeURL = URL
  vi.stubGlobal('URL', class extends NativeURL { static createObjectURL = () => 'blob:test-only'; static revokeObjectURL = vi.fn() })
}
