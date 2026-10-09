import { useState } from 'react'
import { api } from '../../api'
import { useI18n } from '../../i18n'
import { hasPermission } from '../../permissions'
import type { SharedReference } from './catalogTypes'

export default function SharedReferences({ references, onChanged }: { references: SharedReference[]; onChanged: () => void }) {
  const { t, locale } = useI18n()
  const [reason, setReason] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(false)
  async function revoke(id: number) {
    setLoading(true); setError(false)
    try { await api(`/admin/catalog-builder/reference-associations/${id}/revoke`, { method: 'POST', body: JSON.stringify({ reason }) }); setReason(''); onChanged() }
    catch { setError(true) }
    finally { setLoading(false) }
  }
  if (!references.length) return null
  return <section className="panel shared-references"><h3>{t('ref.additional')}</h3>
    {references.map(reference => <article key={reference.id}><strong>{reference.source_id} · {reference.revision}</strong>
      <p>{t('ref.confirmedBy', { name: reference.confirmed_by || '—', date: new Date(reference.confirmed_at + (reference.confirmed_at.endsWith('Z') ? '' : 'Z')).toLocaleString(locale) })}</p><p>{reference.reason}</p>
      <p>{t('ref.partsCount', { count: reference.part_ids.length })}</p><small>{reference.evidence.parts.map(part => `${part.position} · ${part.part_number}`).join(' / ')}</small>
      {!reference.available && <p role="status">{t('ref.unavailable')}</p>}
      {hasPermission('parts.manage') && <button className="secondary compact" disabled={loading || reason.trim().length < 3} onClick={() => { void revoke(reference.id) }}>{t('ref.revoke')}</button>}
    </article>)}
    {hasPermission('parts.manage') && <label className="reference-reason">{t('ref.revokeReason')}<input value={reason} maxLength={4000} onChange={event => setReason(event.target.value)} /></label>}
    {error && <p role="alert">{t('errors.generic')}</p>}
  </section>
}
