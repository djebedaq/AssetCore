import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { I18nProvider } from './i18n'
import UserAdministration from './UserAdministration'
import GovernancePanel from './GovernancePanel'
import { setSessionUser } from './permissions'
import type { ManagedUser, PermissionCode, UserRole } from './types'

const ownerPermissions: PermissionCode[] = ['users.view', 'users.create', 'users.edit', 'users.activate', 'users.deactivate', 'users.reset_password']

function account(id: number, role: UserRole, owner = false): ManagedUser {
  return {
    id,
    email: `test-user-${id}@example.invalid`,
    full_name: `Test user ${id}`,
    role,
    preferred_language: 'bg',
    is_active: true,
    is_system_owner: owner,
    must_change_password: false,
    permissions: ownerPermissions,
    created_at: '2026-08-01T10:00:00Z',
    updated_at: '2026-08-01T10:00:00Z',
    last_login_at: null,
    password_changed_at: null,
  }
}

function response(value: unknown, status = 200): Response {
  return new Response(JSON.stringify(value), { status, headers: { 'Content-Type': 'application/json' } })
}

function renderPage(session: ManagedUser, items: ManagedUser[], fetchMock?: ReturnType<typeof vi.fn>) {
  setSessionUser(session)
  vi.stubGlobal('fetch', fetchMock || vi.fn(async (input: RequestInfo | URL) => response(String(input).includes('/departments') ? [] : items)))
  return render(<I18nProvider initialLocale="bg"><UserAdministration /></I18nProvider>)
}

describe('управление на потребителски акаунти', () => {
  beforeEach(() => localStorage.clear())
  afterEach(() => vi.unstubAllGlobals())

  it('показва защитения системен собственик без действия за промяна', async () => {
    const owner = account(1, 'administrator', true)
    renderPage(owner, [owner, account(2, 'director')])
    const ownerRow = (await screen.findByText('Основен администратор')).closest('tr')
    expect(ownerRow).not.toBeNull()
    expect(within(ownerRow!).queryByRole('button')).not.toBeInTheDocument()
    expect(screen.getByRole('option', { name: 'Администратор' })).toBeInTheDocument()
  })

  it('предлага всички четири роли в owner формата за нов акаунт', async () => {
    const owner = account(1, 'administrator', true)
    renderPage(owner, [owner])
    await screen.findByText('Основен администратор')
    await userEvent.click(screen.getByRole('button', { name: 'Добави потребител' }))
    const roleSelect = within(screen.getByRole('dialog')).getByLabelText('Роля')
    expect(within(roleSelect).getAllByRole('option').map((option) => option.getAttribute('value'))).toEqual(['administrator', 'director', 'mechanic', 'observer'])
  })

  it('owner може да редактира administrator, включително да го понижи', async () => {
    const owner = account(1, 'administrator', true)
    const target = account(2, 'administrator')
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      if (init?.method === 'PATCH') return response({ ...target, role: 'director' })
      return response(String(input).includes('/departments') ? [] : [owner, target])
    })
    renderPage(owner, [owner, target], fetchMock)
    const row = (await screen.findByText('Test user 2')).closest('tr')!
    await userEvent.click(within(row).getByRole('button', { name: 'Редактиране' }))
    const dialog = within(screen.getByRole('dialog'))
    const roles = dialog.getByLabelText('Роля')
    expect(roles).toHaveValue('administrator')
    expect(within(roles).getAllByRole('option').map((option) => option.getAttribute('value'))).toEqual(['administrator', 'director', 'mechanic', 'observer'])
    await userEvent.selectOptions(roles, 'director')
    // Test fixtures supply complete structured names, as required by the API.
    await userEvent.type(dialog.getByLabelText('Собствено име'), 'QA')
    await userEvent.type(dialog.getByLabelText('Бащино име'), 'Lifecycle')
    await userEvent.type(dialog.getByLabelText('Фамилия'), 'Administrator')
    await userEvent.type(dialog.getByLabelText('Длъжност'), 'QA administrator')
    await userEvent.click(dialog.getByRole('button', { name: 'Запази' }))
    expect(await screen.findByRole('status')).toHaveTextContent('Потребителят е актуализиран.')
    expect(fetchMock).toHaveBeenCalledWith('/api/users/2', expect.objectContaining({
      method: 'PATCH', body: expect.stringContaining('"role":"director"'),
    }))
  })

  it('administrator без ownership не може да задава administrator или да управлява director и administrator', async () => {
    const actor = account(2, 'administrator')
    renderPage(actor, [account(1, 'administrator', true), actor, account(3, 'administrator'), account(4, 'director'), account(5, 'mechanic')])
    await screen.findByText('Test user 5')
    for (const id of [1, 2, 3, 4]) {
      const row = screen.getByText(`Test user ${id}`).closest('tr')!
      expect(within(row).queryByRole('button')).not.toBeInTheDocument()
    }
    const mechanic = screen.getByText('Test user 5').closest('tr')!
    await userEvent.click(within(mechanic).getByRole('button', { name: 'Редактиране' }))
    let roles = within(screen.getByRole('dialog')).getByLabelText('Роля')
    expect(within(roles).getAllByRole('option').map((option) => option.getAttribute('value'))).toEqual(['mechanic', 'observer'])
    await userEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Отказ' }))
    await userEvent.click(screen.getByRole('button', { name: 'Добави потребител' }))
    roles = within(screen.getByRole('dialog')).getByLabelText('Роля')
    expect(within(roles).getAllByRole('option').map((option) => option.getAttribute('value'))).toEqual(['mechanic', 'observer'])
  })

  it('ограничава директора до роли механик и наблюдател', async () => {
    const director = account(3, 'director')
    renderPage(director, [account(4, 'mechanic')])
    await screen.findByText('Test user 4')
    await userEvent.click(screen.getByRole('button', { name: 'Добави потребител' }))
    const roleSelect = within(screen.getByRole('dialog', { name: 'Добави потребител' })).getByLabelText('Роля')
    expect(within(roleSelect).getAllByRole('option').map((option) => option.getAttribute('value'))).toEqual(['mechanic', 'observer'])
  })

  it('показва локализирана грешка и не визуализира raw backend съобщение', async () => {
    const owner = account(1, 'administrator', true)
    renderPage(owner, [], vi.fn(async () => response({ detail: { code: 'permission_denied', message: 'RAW INTERNAL ERROR' } }, 403)))
    expect(await screen.findByRole('alert')).toHaveTextContent('Нямате право да извършите тази операция.')
    expect(screen.queryByText(/RAW INTERNAL ERROR/)).not.toBeInTheDocument()
  })

  it('изисква потвърждение преди деактивиране', async () => {
    const owner = account(1, 'administrator', true)
    const target = account(2, 'mechanic')
    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(false)
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => response(String(input).includes('/departments') ? [] : [owner, target]))
    renderPage(owner, [owner, target], fetchMock)
    const targetRow = (await screen.findByText('Test user 2')).closest('tr')!
    await userEvent.click(within(targetRow).getByRole('button', { name: 'Деактивирай' }))
    expect(confirm).toHaveBeenCalledWith(expect.stringContaining('Test user 2'))
    expect(fetchMock).toHaveBeenCalledTimes(2)
  })

  it('създаденият administrator става кандидат за ownership и временната парола се изчиства', async () => {
    const owner = account(1, 'administrator', true)
    let created: ManagedUser | null = null
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input)
      if (init?.method === 'POST') {
        const payload = JSON.parse(String(init.body))
        created = {
          ...account(5, payload.role), email: payload.email, first_name: payload.first_name,
          middle_name: payload.middle_name, last_name: payload.last_name, job_title: payload.job_title,
          full_name: 'Temporary Automation Test', profile_status: 'PROFILE_COMPLETE',
        }
        return response(created, 201)
      }
      if (path === '/api/owner') return response({ owner_user_id: 1, owner_name: owner.full_name, owner_email: owner.email, role: owner.role, designated_at: owner.created_at, designation_version: 1 })
      if (path === '/api/license/status') return response({ state: 'NOT_INSTALLED', message: '', modules: [], checked_at: owner.created_at })
      if (path === '/api/emergency-access/status') return response({ active: false })
      return response(path.includes('/departments') ? [] : [owner, ...(created ? [created] : [])])
    })
    const page = renderPage(owner, [owner], fetchMock)
    await screen.findByText('Основен администратор')
    await userEvent.click(screen.getByRole('button', { name: 'Добави потребител' }))
    const dialog = within(screen.getByRole('dialog', { name: 'Добави потребител' }))
    await userEvent.type(dialog.getByLabelText('Собствено име'), 'Temporary')
    await userEvent.type(dialog.getByLabelText('Бащино име'), 'Automation')
    await userEvent.type(dialog.getByLabelText('Фамилия'), 'Test')
    await userEvent.type(dialog.getByLabelText('Длъжност'), 'Test mechanic')
    await userEvent.type(dialog.getByLabelText('Служебен имейл'), 'temporary@example.invalid')
    await userEvent.selectOptions(dialog.getByLabelText('Роля'), 'administrator')
    await userEvent.type(dialog.getByLabelText('Временна парола'), 'Strong-Test9!')
    await userEvent.type(dialog.getByLabelText('Потвърди паролата'), 'Strong-Test9!')
    await userEvent.click(dialog.getByRole('button', { name: 'Запази' }))
    expect(await screen.findByRole('status')).toHaveTextContent('Потребителят е създаден.')
    await userEvent.click(screen.getByRole('button', { name: 'Добави потребител' }))
    const reopened = within(screen.getByRole('dialog', { name: 'Добави потребител' }))
    expect(reopened.getByLabelText('Временна парола')).toHaveValue('')
    expect(reopened.getByLabelText('Потвърди паролата')).toHaveValue('')
    page.unmount()
    render(<I18nProvider initialLocale="bg"><GovernancePanel session={owner} /></I18nProvider>)
    expect(await screen.findByRole('option', { name: 'Temporary Automation Test · temporary@example.invalid' })).toHaveValue('5')
    expect(screen.getByRole('button', { name: 'Прехвърли собствеността' })).toBeEnabled()
  })
})
