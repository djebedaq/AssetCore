import { type FormEvent, useState } from 'react'
import { ShieldCheck } from 'lucide-react'
import { api } from '../../api'
import { useI18n } from '../../i18n'
import { setSessionUser } from '../../permissions'
import type { UserSession } from '../../types'
import { LanguageSwitcher } from '../../shell/LanguageSwitcher'

export default function Login({ onLogin }: { onLogin: (user: UserSession) => void }) {
  const { setLocale, t } = useI18n()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  async function submit(event: FormEvent) {
    event.preventDefault()
    setBusy(true)
    setError('')
    try {
      const data = await api<{ user: UserSession }>('/auth/login', {
        method: 'POST',
        body: JSON.stringify({ email, password }),
      })
      setSessionUser(data.user)
      setLocale(data.user.preferred_language, false)
      onLogin(data.user)
    } catch {
      setError(t('login.error'))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="login-shell">
      <div className="login-panel">
        <div className="login-language"><LanguageSwitcher compact /></div>
        <div className="brand-mark"><ShieldCheck size={30} /></div>
        <h1>AssetCore</h1>
        <p>{t('login.subtitle')}</p>
        <form onSubmit={submit}>
          <label>
            {t('login.email')}
            <input
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              type="email"
              autoComplete="username"
              placeholder={t('login.emailPlaceholder')}
              required
            />
          </label>
          <label>
            {t('login.password')}
            <input
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              type="password"
              autoComplete="current-password"
              placeholder={t('login.passwordPlaceholder')}
              required
            />
          </label>
          {error && <div className="error" role="alert">{error}</div>}
          <button disabled={busy}>{busy ? t('login.signingIn') : t('login.signIn')}</button>
        </form>
      </div>
    </div>
  )
}
