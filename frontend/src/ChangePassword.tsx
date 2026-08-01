import { type FormEvent, useState } from 'react'
import { KeyRound, ShieldCheck } from 'lucide-react'
import { ApiError, api, setToken } from './api'
import { useI18n, type TranslationKey } from './i18n'
import type { UserSession } from './types'

function errorKey(error: unknown): TranslationKey {
  if (!(error instanceof ApiError)) return 'password.error.generic'
  if (error.code === 'current_password_invalid') return 'password.error.current'
  if (error.code === 'password_reuse') return 'password.error.reuse'
  if (error.code === 'password_policy' || error.status === 422) return 'password.error.policy'
  return 'password.error.generic'
}

export default function ChangePassword({ forced = false, onChanged, onCancel }: {
  forced?: boolean; onChanged: (user: UserSession) => void; onCancel?: () => void
}) {
  const { t } = useI18n()
  const [form, setForm] = useState({ current_password: '', new_password: '', confirm_password: '' })
  const [error, setError] = useState<TranslationKey | ''>('')
  const [busy, setBusy] = useState(false)

  async function submit(event: FormEvent) {
    event.preventDefault()
    setError('')
    setBusy(true)
    try {
      const result = await api<{ access_token: string; user: UserSession }>('/auth/change-password', {
        method: 'POST', body: JSON.stringify(form),
      })
      setToken(result.access_token)
      localStorage.setItem('assetcore_user', JSON.stringify(result.user))
      setForm({ current_password: '', new_password: '', confirm_password: '' })
      onChanged(result.user)
    } catch (caught) { setError(errorKey(caught)) }
    finally { setBusy(false) }
  }

  return <div className={forced ? 'login-shell password-shell' : 'panel password-panel'}><section className={forced ? 'login-panel password-panel' : ''}><div className="brand-mark"><ShieldCheck size={28} /></div><h2>{t(forced ? 'password.forcedTitle' : 'password.title')}</h2><p>{t(forced ? 'password.forcedHint' : 'password.hint')}</p><form onSubmit={submit}><label>{t('password.current')}<input required type="password" autoComplete="current-password" value={form.current_password} onChange={(event) => setForm({ ...form, current_password: event.target.value })} /></label><label>{t('password.new')}<input required minLength={10} type="password" autoComplete="new-password" value={form.new_password} onChange={(event) => setForm({ ...form, new_password: event.target.value })} /></label><label>{t('password.confirm')}<input required minLength={10} type="password" autoComplete="new-password" value={form.confirm_password} onChange={(event) => setForm({ ...form, confirm_password: event.target.value })} /></label><small>{t('users.passwordPolicy')}</small>{error && <div className="error" role="alert">{t(error)}</div>}<div className="actions">{!forced && onCancel && <button type="button" className="secondary" onClick={onCancel}>{t('common.cancel')}</button>}<button className="primary" disabled={busy}><KeyRound size={16} />{busy ? t('common.loading') : t('password.submit')}</button></div></form></section></div>
}
