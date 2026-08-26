import { type FormEvent, useEffect, useState } from 'react'
import { ShieldCheck } from 'lucide-react'
import { api, ApiError } from './api'
import { useI18n } from './i18n'
import { setSessionUser } from './permissions'
import type { Department, UserSession } from './types'

export default function ProfileCompletion({
  user,
  onCompleted,
}: {
  user: UserSession
  onCompleted: (user: UserSession) => void
}) {
  const { t } = useI18n()
  const [departments, setDepartments] = useState<Department[]>([])
  const [firstName, setFirstName] = useState(user.first_name || '')
  const [middleName, setMiddleName] = useState(user.middle_name || '')
  const [lastName, setLastName] = useState(user.last_name || '')
  const [jobTitle, setJobTitle] = useState(user.job_title || '')
  const [departmentId, setDepartmentId] = useState(user.department_id ? String(user.department_id) : '')
  const [exception, setException] = useState(Boolean(user.legal_name_exception))
  const [exceptionReason, setExceptionReason] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    void api<Department[]>('/departments').then(setDepartments).catch(() => setDepartments([]))
  }, [])

  async function submit(event: FormEvent) {
    event.preventDefault()
    setBusy(true)
    setError('')
    try {
      const updated = await api<UserSession>('/users/me/profile', {
        method: 'PUT',
        body: JSON.stringify({
          first_name: firstName,
          middle_name: middleName || null,
          last_name: lastName,
          job_title: jobTitle,
          department_id: departmentId ? Number(departmentId) : null,
          legal_name_exception: exception,
          legal_name_exception_reason: exception ? exceptionReason : null,
        }),
      })
      setSessionUser(updated)
      onCompleted(updated)
    } catch (caught) {
      setError(caught instanceof ApiError && caught.data.message ? caught.data.message : t('profile.saveError'))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="profile-completion-shell">
      <section className="profile-completion-card" aria-labelledby="profile-completion-title">
        <div className="profile-completion-top"><ShieldCheck size={30} /><strong>AssetCore</strong></div>
        <h1 id="profile-completion-title">{t('profile.completeTitle')}</h1>
        <p>{t('profile.completeHint')}</p>
        <form onSubmit={submit}>
          <div className="form-grid three-columns">
            <label>{t('profile.firstName')}<input value={firstName} onChange={(event) => setFirstName(event.target.value)} autoComplete="given-name" required /></label>
            <label>{t('profile.middleName')}<input value={middleName} onChange={(event) => setMiddleName(event.target.value)} autoComplete="additional-name" required={!exception} disabled={exception} /></label>
            <label>{t('profile.lastName')}<input value={lastName} onChange={(event) => setLastName(event.target.value)} autoComplete="family-name" required /></label>
          </div>
          <div className="form-grid">
            <label>{t('profile.jobTitle')}<input value={jobTitle} onChange={(event) => setJobTitle(event.target.value)} required /></label>
            <label>{t('profile.department')}<select value={departmentId} onChange={(event) => setDepartmentId(event.target.value)}><option value="">{t('common.notSpecified')}</option>{departments.map((item) => <option key={item.id} value={item.id}>{item.name_bg}</option>)}</select></label>
          </div>
          <label className="checkbox-line"><input type="checkbox" checked={exception} onChange={(event) => { setException(event.target.checked); if (event.target.checked) setMiddleName('') }} />{t('profile.legalException')}</label>
          {exception && <label>{t('profile.exceptionReason')}<textarea value={exceptionReason} onChange={(event) => setExceptionReason(event.target.value)} required /></label>}
          <div className="notice">{t('profile.officialDocumentWarning')}</div>
          {error && <div className="error" role="alert">{error}</div>}
          <button className="primary" disabled={busy}>{busy ? t('common.loading') : t('profile.confirm')}</button>
        </form>
      </section>
    </div>
  )
}
