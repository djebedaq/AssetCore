import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { I18nProvider } from './i18n'
import UserAdministration from './UserAdministration'
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
  localStorage.setItem('assetcore_user', JSON.stringify(session))
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

  it('не предлага administrator в стандартната owner форма за нов акаунт', async () => {
    const owner = account(1, 'administrator', true)
    renderPage(owner, [owner])
    await screen.findByText('Основен администратор')
    await userEvent.click(screen.getByRole('button', { name: 'Добави потребител' }))
    const roleSelect = within(screen.getByRole('dialog')).getByLabelText('Роля')
    expect(within(roleSelect).queryByRole('option', { name: 'Администратор' })).not.toBeInTheDocument()
    expect(within(roleSelect).getByRole('option', { name: 'Директор' })).toBeInTheDocument()
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

  it('изчиства временната парола след успешно създаване', async () => {
    const owner = account(1, 'administrator', true)
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      if (init?.method === 'POST') return response(account(5, 'mechanic'), 201)
      return response(String(input).includes('/departments') ? [] : [owner])
    })
    renderPage(owner, [owner], fetchMock)
    await screen.findByText('Основен администратор')
    await userEvent.click(screen.getByRole('button', { name: 'Добави потребител' }))
    const dialog = within(screen.getByRole('dialog', { name: 'Добави потребител' }))
    await userEvent.type(dialog.getByLabelText('Собствено име'), 'Temporary')
    await userEvent.type(dialog.getByLabelText('Бащино име'), 'Automation')
    await userEvent.type(dialog.getByLabelText('Фамилия'), 'Test')
    await userEvent.type(dialog.getByLabelText('Длъжност'), 'Test mechanic')
    await userEvent.type(dialog.getByLabelText('Служебен имейл'), 'temporary@example.invalid')
    await userEvent.selectOptions(dialog.getByLabelText('Роля'), 'mechanic')
    await userEvent.type(dialog.getByLabelText('Временна парола'), 'Strong-Test9!')
    await userEvent.type(dialog.getByLabelText('Потвърди паролата'), 'Strong-Test9!')
    await userEvent.click(dialog.getByRole('button', { name: 'Запази' }))
    expect(await screen.findByRole('status')).toHaveTextContent('Потребителят е създаден.')
    await userEvent.click(screen.getByRole('button', { name: 'Добави потребител' }))
    const reopened = within(screen.getByRole('dialog', { name: 'Добави потребител' }))
    expect(reopened.getByLabelText('Временна парола')).toHaveValue('')
    expect(reopened.getByLabelText('Потвърди паролата')).toHaveValue('')
  })
})
