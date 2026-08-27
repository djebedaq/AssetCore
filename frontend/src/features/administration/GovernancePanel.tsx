import { type ChangeEvent, type FormEvent, useEffect, useState } from 'react'
import { AlertTriangle, BadgeCheck, FileCheck2, KeyRound, Shield } from 'lucide-react'
import { api, ApiError } from '../../api'
import { useI18n, type TranslationKey } from '../../i18n'
import type { EmergencyAccessStatus, LicenseStatus, ManagedUser, OwnerStatus, UserSession } from '../../types'

type TemplateSummary = { id: number; code: string; name_bg: string; versions: Array<{ id: number; version: number; language: string; validation_status?: string; validation_report?: { errors?: string[] } | null; is_published: boolean }> }

export default function GovernancePanel({ session }: { session: UserSession }) {
  const { date, t } = useI18n()
  const [owner, setOwner] = useState<OwnerStatus | null>(null)
  const [license, setLicense] = useState<LicenseStatus | null>(null)
  const [users, setUsers] = useState<ManagedUser[]>([])
  const [templates, setTemplates] = useState<TemplateSummary[]>([])
  const [emergency, setEmergency] = useState<EmergencyAccessStatus | null>(null)
  const [envelope, setEnvelope] = useState<{ payload: Record<string, unknown>; signature: string } | null>(null)
  const [target, setTarget] = useState('')
  const [password, setPassword] = useState('')
  const [reason, setReason] = useState('')
  const [emergencyPassword, setEmergencyPassword] = useState('')
  const [emergencyReason, setEmergencyReason] = useState('')
  const [emergencyDuration, setEmergencyDuration] = useState('30')
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState('')
  const [error, setError] = useState('')

  const load = () => Promise.all([
    api<OwnerStatus>('/owner'),
    api<LicenseStatus>('/license/status'),
    session.permissions.includes('users.view') ? api<ManagedUser[]>('/users') : Promise.resolve([]),
    session.permissions.includes('templates.manage') ? api<TemplateSummary[]>('/document-templates') : Promise.resolve([]),
  ]).then(([ownerValue, licenseValue, userValues, templateValues]) => {
    setOwner(ownerValue)
    setLicense(licenseValue)
    setUsers(userValues)
    setTemplates(templateValues)
  }).catch(() => setError(t('governance.loadError')))

  useEffect(() => { void load() }, [])
  useEffect(() => {
    void api<EmergencyAccessStatus>('/emergency-access/status')
      .then(setEmergency)
      .catch(() => setEmergency(null))
  }, [])

  async function chooseLicense(event: ChangeEvent<HTMLInputElement>) {
    setError('')
    setMessage('')
    const file = event.target.files?.[0]
    if (!file) return setEnvelope(null)
    try {
      const parsed = JSON.parse(await file.text()) as { payload?: Record<string, unknown>; signature?: string }
      if (!parsed.payload || !parsed.signature) throw new Error('invalid envelope')
      setEnvelope({ payload: parsed.payload, signature: parsed.signature })
    } catch {
      setEnvelope(null)
      setError(t('governance.invalidLicenseFile'))
    }
  }

  async function installLicense() {
    if (!envelope) return
    setBusy(true)
    setError('')
    setMessage('')
    try {
      const value = await api<LicenseStatus>('/license/install', { method: 'POST', body: JSON.stringify(envelope) })
      setLicense(value)
      setMessage(t('governance.licenseInstalled'))
    } catch (caught) {
      setError(caught instanceof ApiError && caught.data.message ? caught.data.message : t('governance.licenseInstallError'))
    } finally {
      setBusy(false)
    }
  }

  async function transfer(event: FormEvent) {
    event.preventDefault()
    setBusy(true)
    setError('')
    setMessage('')
    try {
      const value = await api<OwnerStatus>('/owner/transfer', { method: 'POST', body: JSON.stringify({ target_user_id: Number(target), current_password: password, reason }) })
      setOwner(value)
      setPassword('')
      setReason('')
      setTarget('')
      setMessage(t('governance.ownerTransferred'))
    } catch (caught) {
      setError(caught instanceof ApiError && caught.data.message ? caught.data.message : t('governance.ownerTransferError'))
    } finally {
      setBusy(false)
    }
  }

  async function validateTemplate(versionId: number) {
    setBusy(true)
    setError('')
    try {
      await api(`/document-template-versions/${versionId}/validate`, { method: 'POST' })
      await load()
      setMessage(t('governance.templateValidated'))
    } catch {
      setError(t('governance.templateValidationError'))
    } finally {
      setBusy(false)
    }
  }

  async function changeEmergencyAccess(event: FormEvent) {
    event.preventDefault()
    setBusy(true)
    setError('')
    setMessage('')
    try {
      const endpoint = emergency?.active
        ? `/emergency-access/${emergency.session_id}/end`
        : '/emergency-access/start'
      const body = emergency?.active
        ? { current_password: emergencyPassword, reason: emergencyReason }
        : { current_password: emergencyPassword, reason: emergencyReason, duration_minutes: Number(emergencyDuration) }
      const value = await api<EmergencyAccessStatus>(endpoint, { method: 'POST', body: JSON.stringify(body) })
      setEmergency(value)
      setEmergencyPassword('')
      setEmergencyReason('')
      setMessage(t(emergency?.active ? 'emergency.ended' : 'emergency.started'))
      window.dispatchEvent(new Event('assetcore-emergency-change'))
    } catch {
      setError(t('emergency.operationError'))
    } finally {
      setBusy(false)
    }
  }

  const isOwner = owner?.owner_user_id === session.id && session.role === 'administrator'
  const ownerCandidates = users.filter((user) => user.role === 'administrator' && user.is_active && user.profile_status === 'PROFILE_COMPLETE' && user.id !== session.id)

  return (
    <div className="governance-grid">
      <section className="panel">
        <div className="panel-title"><h3>{t('governance.ownerTitle')}</h3><BadgeCheck /></div>
        {owner ? <dl className="governance-details"><div><dt>{t('governance.owner')}</dt><dd>{owner.owner_name}</dd></div><div><dt>{t('login.email')}</dt><dd>{owner.owner_email}</dd></div><div><dt>{t('governance.designatedAt')}</dt><dd>{date(owner.designated_at)}</dd></div><div><dt>{t('governance.version')}</dt><dd>{owner.designation_version}</dd></div></dl> : <p>{t('common.loading')}</p>}
        {isOwner && <form onSubmit={transfer} className="governance-form"><h4>{t('governance.transferTitle')}</h4><p className="muted">{t('governance.transferWarning')}</p><label>{t('governance.newOwner')}<select value={target} onChange={(event) => setTarget(event.target.value)} required><option value="">{t('common.notSpecified')}</option>{ownerCandidates.map((user) => <option key={user.id} value={user.id}>{user.full_name} · {user.email}</option>)}</select></label><label>{t('governance.currentPassword')}<input type="password" autoComplete="current-password" value={password} onChange={(event) => setPassword(event.target.value)} required /></label><label>{t('governance.reason')}<textarea value={reason} onChange={(event) => setReason(event.target.value)} minLength={10} required /></label><button className="secondary danger" disabled={busy || !ownerCandidates.length}>{t('governance.transfer')}</button>{!ownerCandidates.length && <small>{t('governance.noCandidates')}</small>}</form>}
      </section>
      <section className="panel emergency-access-panel">
        <div className="panel-title"><h3>{t('emergency.title')}</h3><AlertTriangle /></div>
        <p className="muted">{t('emergency.hint')}</p>
        <div className={`license-state ${emergency?.active ? 'state-read_only' : 'state-active'}`}><Shield size={18} /><strong>{t(emergency?.active ? 'emergency.active' : 'emergency.inactive')}</strong></div>
        {emergency?.active && <dl className="governance-details"><div><dt>{t('emergency.owner')}</dt><dd>{emergency.owner_name || t('common.noValue')}</dd></div><div><dt>{t('emergency.expires')}</dt><dd>{emergency.expires_at ? date(emergency.expires_at) : t('common.noValue')}</dd></div><div><dt>{t('emergency.mfa')}</dt><dd>{emergency.mfa_verified ? t('common.yes') : t('emergency.mfaNotConfigured')}</dd></div></dl>}
        {isOwner && <form className="governance-form" onSubmit={changeEmergencyAccess}><label>{t('governance.currentPassword')}<input type="password" autoComplete="current-password" value={emergencyPassword} onChange={(event) => setEmergencyPassword(event.target.value)} required /></label><label>{t('emergency.reason')}<textarea value={emergencyReason} onChange={(event) => setEmergencyReason(event.target.value)} minLength={10} required /></label>{!emergency?.active && <label>{t('emergency.duration')}<select value={emergencyDuration} onChange={(event) => setEmergencyDuration(event.target.value)}><option value="5">5 {t('emergency.minutes')}</option><option value="15">15 {t('emergency.minutes')}</option><option value="30">30 {t('emergency.minutes')}</option><option value="60">60 {t('emergency.minutes')}</option></select></label>}<button className={emergency?.active ? 'secondary danger' : 'secondary'} disabled={busy}>{t(emergency?.active ? 'emergency.end' : 'emergency.start')}</button></form>}
      </section>
      {session.permissions.includes('templates.manage') && <section className="panel governance-templates"><div className="panel-title"><h3>{t('governance.templateValidationTitle')}</h3><FileCheck2 /></div><p className="muted">{t('governance.templateValidationHint')}</p><div className="participant-list">{templates.flatMap((template) => template.versions.map((version) => <div key={version.id}><div><strong>{template.name_bg} · {version.language.toUpperCase()} v{version.version}</strong><span>{t(`governance.templateStatus.${version.validation_status || 'NOT_VALIDATED'}` as TranslationKey)}{version.is_published ? ` · ${t('governance.templatePublished')}` : ''}</span></div><button className="secondary" disabled={busy} onClick={() => void validateTemplate(version.id)}>{t('governance.validateTemplate')}</button></div>))}</div>{!templates.length && <div className="empty-state">{t('governance.noTemplates')}</div>}</section>}
      <section className="panel">
        <div className="panel-title"><h3>{t('governance.licenseTitle')}</h3><KeyRound /></div>
        {license ? <><div className={`license-state state-${license.state.toLowerCase()}`}><Shield size={18} /><strong>{t(`license.${license.state}` as TranslationKey)}</strong></div><p>{license.message}</p><dl className="governance-details"><div><dt>{t('governance.rightsholder')}</dt><dd>{license.rightsholder || t('common.noValue')}</dd></div><div><dt>{t('governance.client')}</dt><dd>{license.client_name || t('common.noValue')}</dd></div><div><dt>{t('governance.licenseId')}</dt><dd>{license.license_id || t('common.noValue')}</dd></div><div><dt>{t('governance.licenseType')}</dt><dd>{license.license_type || t('common.noValue')}</dd></div><div><dt>{t('governance.validUntil')}</dt><dd>{license.valid_until ? date(license.valid_until) : t('governance.unlimited')}</dd></div><div><dt>{t('governance.supportUntil')}</dt><dd>{license.support_until ? date(license.support_until) : t('common.noValue')}</dd></div><div><dt>{t('governance.installationId')}</dt><dd>{license.installation_id || t('common.noValue')}</dd></div><div><dt>{t('governance.lastChecked')}</dt><dd>{date(license.checked_at)}</dd></div><div><dt>{t('governance.modules')}</dt><dd>{license.modules.join(', ') || t('common.noValue')}</dd></div></dl></> : <p>{t('common.loading')}</p>}
        {isOwner && <div className="governance-form"><label>{t('governance.licenseFile')}<input type="file" accept="application/json,.json,.license" onChange={(event) => { void chooseLicense(event) }} /></label><p className="muted">{t('governance.licenseHint')}</p><button className="primary" onClick={installLicense} disabled={busy || !envelope}>{t('governance.installLicense')}</button></div>}
      </section>
      {error && <div className="error governance-message" role="alert">{error}</div>}
      {message && <div className="success governance-message" role="status">{message}</div>}
    </div>
  )
}
