import { type FormEvent, useEffect, useMemo, useState } from 'react'
import { Download, ExternalLink, FileCheck2, Plus, RefreshCw } from 'lucide-react'
import { api, ApiError, downloadApiFile } from './api'
import { useI18n, type TranslationKey } from './i18n'
import type { ExternalSigner, InternalParticipantCandidate, OfficialDocument, SignatureSlot } from './types'

export default function OfficialDocuments() {
  const { date, locale, t } = useI18n()
  const [documents, setDocuments] = useState<OfficialDocument[]>([])
  const [signers, setSigners] = useState<ExternalSigner[]>([])
  const [internalCandidates, setInternalCandidates] = useState<InternalParticipantCandidate[]>([])
  const [signatureSlots, setSignatureSlots] = useState<SignatureSlot[]>([])
  const [selected, setSelected] = useState<OfficialDocument | null>(null)
  const [assignments, setAssignments] = useState<Record<string, string>>({})
  const [showSigner, setShowSigner] = useState(false)
  const [link, setLink] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  const load = () => Promise.all([
    api<OfficialDocument[]>('/official-documents'),
    api<ExternalSigner[]>('/external-signers'),
    api<InternalParticipantCandidate[]>('/document-participants/internal-candidates'),
    api<SignatureSlot[]>('/signature-slots'),
  ]).then(([documentValues, signerValues, candidateValues, slotValues]) => {
    setDocuments(documentValues)
    setSigners(signerValues)
    setInternalCandidates(candidateValues)
    setSignatureSlots(slotValues)
    setSelected((current) => current ? documentValues.find((item) => item.id === current.id) || null : null)
    setError('')
  }).catch(() => setError(t('official.loadError')))

  useEffect(() => { void load() }, [t])

  const slots = selected ? signatureSlots.filter((slot) => slot.document_type === selected.document_type && slot.is_active && slot.required).sort((a, b) => a.sequence - b.sequence) : []
  const choices = useMemo(() => [
    ...internalCandidates.map((candidate) => ({ value: `internal:${candidate.id}`, label: `${candidate.display_name} · ${candidate.job_title || candidate.role}` })),
    ...signers.map((signer) => ({ value: `external:${signer.id}`, label: `${[signer.first_name, signer.middle_name, signer.last_name].filter(Boolean).join(' ')} · ${signer.company || signer.job_title}` })),
  ], [internalCandidates, signers])

  async function assign() {
    if (!selected || slots.some((slot) => !assignments[slot.code])) return setError(t('official.selectAllSigners'))
    setBusy(true)
    setError('')
    try {
      await api(`/official-documents/${selected.id}/participants`, {
        method: 'POST',
        body: JSON.stringify({ participants: slots.map((slot) => {
          const [kind, id] = assignments[slot.code].split(':')
          return { slot_code: slot.code, operation_role: slotLabel(slot, locale), user_id: kind === 'internal' ? Number(id) : null, external_signer_id: kind === 'external' ? Number(id) : null }
        }) }),
      })
      await load()
    } catch (caught) {
      setError(caught instanceof ApiError && caught.data.message ? caught.data.message : t('official.assignError'))
    } finally {
      setBusy(false)
    }
  }

  async function startSigning(participantId: number) {
    setBusy(true)
    setError('')
    setLink('')
    try {
      const result = await api<{ signing_token: string; signing_endpoint: string; expires_at: string }>('/signatures/sessions', { method: 'POST', body: JSON.stringify({ participant_id: participantId, expires_minutes: 30 }) })
      const fullLink = `${window.location.origin}/sign/${encodeURIComponent(result.signing_token)}`
      setLink(fullLink)
      await navigator.clipboard?.writeText(fullLink).catch(() => undefined)
    } catch (caught) {
      setError(caught instanceof ApiError && caught.data.message ? caught.data.message : t('official.sessionError'))
    } finally {
      setBusy(false)
    }
  }

  const download = (document: OfficialDocument, format: 'docx' | 'pdf') => downloadApiFile(`/official-documents/${document.id}/versions/${document.current_version.version}/download/${format}`, `${document.document_number}-v${document.current_version.version}.${format}`).catch(() => setError(t('official.downloadError')))

  return (
    <>
      <div className="toolbar"><div><h3>{t('official.title')}</h3><p className="muted">{t('official.subtitle')}</p></div><div className="toolbar-actions"><button className="secondary" onClick={() => { void load() }}><RefreshCw size={16} />{t('official.refresh')}</button><button className="primary" onClick={() => setShowSigner(true)}><Plus size={16} />{t('official.newExternal')}</button></div></div>
      {error && <div className="error" role="alert">{error}</div>}
      {link && <div className="success official-signing-link" role="status"><strong>{t('official.linkCreated')}</strong><input readOnly value={link} /><a href={link} target="_blank" rel="noreferrer"><ExternalLink size={16} />{t('official.openSigning')}</a></div>}
      <div className="official-layout">
        <div className="table-card"><table><thead><tr><th>{t('official.number')}</th><th>{t('official.type')}</th><th>{t('common.status')}</th><th>{t('official.progress')}</th><th>{t('official.created')}</th><th>{t('transfers.documents')}</th></tr></thead><tbody>{documents.map((document) => <tr key={document.id} className={selected?.id === document.id ? 'selected-row' : ''} onClick={() => { setSelected(document); setAssignments({}); setLink('') }}><td><strong>{document.document_number}</strong><small>v{document.current_version.version}</small></td><td>{t(documentTypeKey(document.document_type))}</td><td><span className="badge">{t(statusKey(document.current_version.status))}</span></td><td>{document.signed_count} / {document.required_count}</td><td>{date(document.created_at)}</td><td><button className="link" onClick={(event) => { event.stopPropagation(); void download(document, 'docx') }}><Download size={14} />{t('common.word')}</button> <button className="link" onClick={(event) => { event.stopPropagation(); void download(document, 'pdf') }}><Download size={14} />{t('common.pdf')}</button></td></tr>)}</tbody></table>{!documents.length && <div className="empty-state">{t('official.empty')}</div>}</div>
        {selected && <aside className="panel official-detail"><div className="panel-title"><h3>{selected.document_number}</h3><FileCheck2 /></div>{selected.current_version.status === 'DRAFT' ? <><p>{t('official.assignHint')}</p>{slots.map((slot) => <label key={slot.code}>{slotLabel(slot, locale)}<select value={assignments[slot.code] || ''} onChange={(event) => setAssignments((current) => ({ ...current, [slot.code]: event.target.value }))}><option value="">{t('common.notSpecified')}</option>{choices.map((choice) => <option key={`${slot.code}-${choice.value}`} value={choice.value}>{choice.label}</option>)}</select></label>)}<button className="primary" disabled={busy || !slots.length} onClick={assign}>{t('official.openForSigning')}</button></> : <><p>{t('official.participants')}</p><div className="participant-list">{selected.participants.map((participant) => <div key={participant.id}><div><strong>{String(participant.identity_snapshot.display_name || '')}</strong><span>{participant.operation_role} · {String(participant.identity_snapshot.job_title || '')}</span></div>{participant.signed ? <span className="badge success-badge">{t('official.signed')}</span> : <button className="secondary" disabled={busy} onClick={() => startSigning(participant.id)}>{t('official.createLink')}</button>}</div>)}</div>{selected.current_version.status === 'PARTIALLY_SIGNED' && <div className="notice">{t('official.partial')}</div>}{selected.current_version.status === 'SIGNED' && <div className="success">{t('official.fullySigned')}</div>}</>}</aside>}
      </div>
      {showSigner && <ExternalSignerDialog onClose={() => setShowSigner(false)} onCreated={(signer) => { setSigners((items) => [...items, signer]); setShowSigner(false) }} />}
    </>
  )
}

function ExternalSignerDialog({ onClose, onCreated }: { onClose: () => void; onCreated: (value: ExternalSigner) => void }) {
  const { t } = useI18n()
  const [form, setForm] = useState({ first_name: '', middle_name: '', last_name: '', job_title: '', company: '', participant_role: '', note: '', is_foreign_person: false, name_exception_reason: '' })
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  async function submit(event: FormEvent) {
    event.preventDefault(); setBusy(true); setError('')
    try { onCreated(await api<ExternalSigner>('/external-signers', { method: 'POST', body: JSON.stringify(form) })) } catch { setError(t('official.externalSaveError')) } finally { setBusy(false) }
  }
  return <div className="modal-backdrop" role="presentation"><div className="modal" role="dialog" aria-modal="true" aria-labelledby="external-title"><h3 id="external-title">{t('official.newExternal')}</h3><form onSubmit={submit}><div className="form-grid three-columns"><label>{t('profile.firstName')}<input required value={form.first_name} onChange={(e) => setForm({ ...form, first_name: e.target.value })} /></label><label>{t('profile.middleName')}<input required={!form.is_foreign_person} value={form.middle_name} onChange={(e) => setForm({ ...form, middle_name: e.target.value })} /></label><label>{t('profile.lastName')}<input required value={form.last_name} onChange={(e) => setForm({ ...form, last_name: e.target.value })} /></label></div><div className="form-grid"><label>{t('profile.jobTitle')}<input required value={form.job_title} onChange={(e) => setForm({ ...form, job_title: e.target.value })} /></label><label>{t('official.company')}<input value={form.company} onChange={(e) => setForm({ ...form, company: e.target.value })} /></label><label>{t('official.participantRole')}<input required value={form.participant_role} onChange={(e) => setForm({ ...form, participant_role: e.target.value })} /></label><label className="checkbox-row"><input type="checkbox" checked={form.is_foreign_person} onChange={(e) => setForm({ ...form, is_foreign_person: e.target.checked })} />{t('bulk.foreignPerson')}</label></div>{form.is_foreign_person && <label>{t('profile.exceptionReason')}<textarea required minLength={10} value={form.name_exception_reason} onChange={(e) => setForm({ ...form, name_exception_reason: e.target.value })} /></label>}<label>{t('common.notes')}<textarea value={form.note} onChange={(e) => setForm({ ...form, note: e.target.value })} /></label>{error && <div className="error">{error}</div>}<div className="modal-actions"><button type="button" className="secondary" onClick={onClose}>{t('common.cancel')}</button><button className="primary" disabled={busy}>{t('common.save')}</button></div></form></div></div>
}

function documentTypeKey(value: string): TranslationKey {
  return ({ TRANSFER_ISSUE: 'documentType.transferIssue', TRANSFER_RETURN: 'documentType.transferReturn', REPAIR_PROTOCOL: 'documentType.repairProtocol', PART_REQUEST: 'documentType.partRequest' } as Record<string, TranslationKey>)[value] || 'documentType.other'
}
function statusKey(value: string): TranslationKey {
  return ({ DRAFT: 'official.statusDraft', READY_FOR_SIGNATURE: 'official.statusReady', PARTIALLY_SIGNED: 'official.statusPartial', SIGNED: 'official.statusSigned', FINALIZED: 'official.statusSigned', SUPERSEDED: 'official.statusSuperseded', CANCELLED: 'official.statusCancelled' } as Record<string, TranslationKey>)[value] || 'common.status'
}
function slotLabel(slot: SignatureSlot, locale: 'bg' | 'en' | 'ru'): string {
  return (locale === 'en' ? slot.label_en : locale === 'ru' ? slot.label_ru : slot.label_bg) || slot.label_bg
}
