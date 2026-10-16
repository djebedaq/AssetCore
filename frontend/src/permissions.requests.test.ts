import { afterEach, describe, expect, it } from 'vitest'
import type { UserSession } from './types'
import { canEditRequestDraft, clearSessionUser, setSessionUser } from './permissions'

describe('request draft ownership', () => {
  afterEach(clearSessionUser)
  it.each(['mechanic', 'director', 'administrator'] as const)('%s respects the ownership rule', role => {
    setSessionUser({ id: 7, role, permissions: ['requests.create', 'requests.view'] } as UserSession)
    expect(canEditRequestDraft(7)).toBe(true)
    expect(canEditRequestDraft(8)).toBe(role === 'administrator')
    expect(canEditRequestDraft(null)).toBe(role === 'administrator')
  })
  it('requires an authenticated account and create permission', () => {
    expect(canEditRequestDraft(7)).toBe(false)
    setSessionUser({ id: 7, role: 'observer', permissions: ['assets.view'] } as UserSession)
    expect(canEditRequestDraft(7)).toBe(false)
  })
})
