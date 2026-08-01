import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import ChangePassword from './ChangePassword'
import { I18nProvider } from './i18n'

function renderForm() {
  return render(<I18nProvider initialLocale="bg"><ChangePassword forced onChanged={vi.fn()} /></I18nProvider>)
}

describe('задължителна смяна на парола', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('не предлага отказ при временна парола', () => {
    renderForm()
    expect(screen.getByRole('heading', { name: 'Задължителна смяна на паролата' })).toBeVisible()
    expect(screen.queryByRole('button', { name: 'Отказ' })).not.toBeInTheDocument()
  })

  it('показва безопасно локализирано съобщение при грешна текуща парола', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({ detail: { code: 'current_password_invalid', message: 'RAW HASH DETAIL' } }), { status: 409, headers: { 'Content-Type': 'application/json' } })))
    renderForm()
    await userEvent.type(screen.getByLabelText('Текуща парола'), 'Old-Test9!')
    await userEvent.type(screen.getByLabelText('Нова парола'), 'New-Strong9!')
    await userEvent.type(screen.getByLabelText('Потвърди новата парола'), 'New-Strong9!')
    await userEvent.click(screen.getByRole('button', { name: 'Смени паролата' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Текущата парола е неправилна.')
    expect(screen.queryByText(/RAW HASH DETAIL/)).not.toBeInTheDocument()
  })
})
