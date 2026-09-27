import { render, screen, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { formatDate, I18nProvider, translate } from '../../i18n'
import type { LicenseStatus, ManagedUser, UserSession } from '../../types'
import GovernancePanel from './GovernancePanel'

const expiry = '2035-01-20T12:00:00Z'
const session: UserSession = {
  id: 1, email: 'presentation@example.invalid', full_name: 'QA presentation', role: 'director',
  preferred_language: 'bg', is_active: true, is_system_owner: false, must_change_password: false,
  permissions: [], created_at: '2035-01-01T10:00:00Z', updated_at: '2035-01-01T10:00:00Z',
}

type ExpiryCase = Pick<LicenseStatus, 'state' | 'license_type' | 'valid_until'> & {
  expected: 'common.noValue' | 'governance.unlimited' | 'date'
}

const cases: ExpiryCase[] = [
  { state: 'INVALID', license_type: null, valid_until: null, expected: 'common.noValue' },
  { state: 'NOT_INSTALLED', license_type: null, valid_until: null, expected: 'common.noValue' },
  { state: 'INVALID', license_type: 'PERPETUAL', valid_until: null, expected: 'common.noValue' },
  { state: 'NOT_INSTALLED', license_type: 'SUPPORT_ONLY', valid_until: null, expected: 'common.noValue' },
  { state: 'ACTIVE', license_type: 'PERPETUAL', valid_until: null, expected: 'governance.unlimited' },
  { state: 'ACTIVE', license_type: 'SUPPORT_ONLY', valid_until: null, expected: 'governance.unlimited' },
  { state: 'NOT_YET_VALID', license_type: 'PERPETUAL', valid_until: null, expected: 'governance.unlimited' },
  { state: 'ACTIVE', license_type: 'ANNUAL', valid_until: null, expected: 'common.noValue' },
  { state: 'ACTIVE', license_type: 'ANNUAL', valid_until: expiry, expected: 'date' },
  { state: 'GRACE_PERIOD', license_type: 'ANNUAL', valid_until: expiry, expected: 'date' },
  { state: 'READ_ONLY', license_type: 'ANNUAL', valid_until: expiry, expected: 'date' },
  { state: 'NOT_YET_VALID', license_type: 'ANNUAL', valid_until: expiry, expected: 'date' },
  { state: 'ACTIVE', license_type: 'PERPETUAL', valid_until: expiry, expected: 'date' },
  { state: 'ACTIVE', license_type: 'SUPPORT_ONLY', valid_until: expiry, expected: 'date' },
]

beforeEach(() => localStorage.clear())
afterEach(() => vi.unstubAllGlobals())

it.each(['bg', 'en', 'ru'] as const)('only active complete nonowner administrators are candidates (%s)', async (locale) => {
  const owner: UserSession = { ...session, role: 'administrator', is_system_owner: true, permissions: ['users.view'] }
  const candidate = (id: number, overrides: Partial<ManagedUser> = {}): ManagedUser => ({
    ...owner, id, full_name: `QA candidate ${id}`, email: `candidate-${id}@example.invalid`,
    is_system_owner: false, profile_status: 'PROFILE_COMPLETE', last_login_at: null,
    password_changed_at: null, ...overrides,
  })
  const responses: Record<string, unknown> = {
    '/api/owner': { owner_user_id: 1, owner_name: owner.full_name, owner_email: owner.email, role: owner.role, designated_at: owner.created_at, designation_version: 1 },
    '/api/users': [owner, candidate(2), candidate(3, { is_active: false }), candidate(4, { profile_status: 'PROFILE_INCOMPLETE' }), candidate(5, { role: 'director' })],
    '/api/license/status': { state: 'NOT_INSTALLED', message: '', modules: [], checked_at: owner.created_at },
    '/api/emergency-access/status': { active: false },
  }
  vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => new Response(JSON.stringify(responses[String(input)]), { headers: { 'Content-Type': 'application/json' } })))
  render(<I18nProvider initialLocale={locale}><GovernancePanel session={owner} /></I18nProvider>)
  const select = await screen.findByLabelText(translate(locale, 'governance.newOwner'))
  expect(within(select).getAllByRole('option').map((option) => option.getAttribute('value'))).toEqual(['', '2'])
})

describe.each(['bg', 'en', 'ru'] as const)('license expiry presentation (%s)', (locale) => {
  it.each(cases)('$state/$license_type/$valid_until displays $expected', async ({ expected, ...values }) => {
    const license: LicenseStatus = {
      ...values, message: '', read_only: values.state !== 'ACTIVE' && values.state !== 'GRACE_PERIOD',
      modules: [], allowed_domains: [], checked_at: '2035-01-15T10:00:00Z',
    }
    const responses: Record<string, unknown> = {
      '/api/owner': {
        owner_user_id: 2, owner_name: 'QA owner', owner_email: 'owner@example.invalid',
        role: 'administrator', designated_at: '2035-01-01T10:00:00Z', designation_version: 1,
      },
      '/api/license/status': license,
      '/api/emergency-access/status': { active: false, mfa_verified: false, message: '' },
    }
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
      const path = String(input)
      if (!(path in responses)) throw new Error(`Unexpected request: ${path}`)
      return new Response(JSON.stringify(responses[path]), { headers: { 'Content-Type': 'application/json' } })
    }))

    render(<I18nProvider initialLocale={locale}><GovernancePanel session={session} /></I18nProvider>)

    const label = await screen.findByText(translate(locale, 'governance.validUntil'))
    const value = label.parentElement?.querySelector('dd')
    expect(value).not.toBeNull()
    expect(value?.textContent).toBe(expected === 'date'
      ? formatDate(locale, expiry)
      : translate(locale, expected))
    if (expected !== 'governance.unlimited') {
      expect(value?.textContent).not.toBe(translate(locale, 'governance.unlimited'))
    }
  })
})
