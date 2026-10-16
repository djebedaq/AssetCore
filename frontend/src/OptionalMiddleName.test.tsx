import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, expect, it, vi } from 'vitest'
import { I18nProvider, translate } from './i18n'
import ProfileCompletion from './ProfileCompletion'
import type { UserSession } from './types'

afterEach(() => { cleanup(); vi.unstubAllGlobals() })

it.each(['bg', 'en', 'ru'] as const)('completes a two-name profile without requesting an exception (%s)', async locale => {
  const completed = vi.fn()
  const user = { id: 8, profile_status: 'PROFILE_INCOMPLETE', preferred_language: locale } as UserSession
  vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    if (String(input).endsWith('/departments')) return new Response('[]', { status: 200 })
    const payload = JSON.parse(String(init?.body))
    expect(payload.middle_name).toBeNull()
    expect(payload.legal_name_exception).toBe(false)
    return new Response(JSON.stringify({ ...user, ...payload, profile_status: 'PROFILE_COMPLETE' }), { status: 200 })
  }))
  render(<I18nProvider initialLocale={locale}><ProfileCompletion user={user} onCompleted={completed} /></I18nProvider>)
  const t = (key: Parameters<typeof translate>[1]) => translate(locale, key)
  expect(screen.getByLabelText(t('profile.middleNameOptional'))).not.toBeRequired()
  await userEvent.type(screen.getByLabelText(t('profile.firstName')), 'QA')
  await userEvent.type(screen.getByLabelText(t('profile.lastName')), 'Profile')
  await userEvent.type(screen.getByLabelText(t('profile.jobTitle')), 'QA operator')
  await userEvent.click(screen.getByRole('button', { name: t('profile.confirm') }))
  expect(completed).toHaveBeenCalledWith(expect.objectContaining({ profile_status: 'PROFILE_COMPLETE' }))
})
