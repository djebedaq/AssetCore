import { useEffect, useState } from 'react'
import { api, createApiObjectUrl } from '../../api'
import { useI18n } from '../../i18n'
import { guidedError } from './guidedErrors'
import type { PartValues, ReviewSession, ReviewSource } from './guidedTypes'
import { builderBase } from './wizardTypes'

export default function DurableSourceReview({ session, reload, parts, busy, targetSourceId }: {
  targetSourceId?: number;
  session: ReviewSession | null; reload: () => Promise<void>; parts: Array<PartValues & { id: number }>; busy: boolean
}) {
  const { t } = useI18n()
  const [selected, setSelected] = useState<number | null>(null)
  const [original, setOriginal] = useState<{ url: string; receipt: string | null; source: ReviewSource } | null>(null)
  const [loaded, setLoaded] = useState(false)
  const [reason, setReason] = useState('')
  const [manual, setManual] = useState(false)
  const [working, setWorking] = useState(false)
  const [error, setError] = useState('')
  const [link, setLink] = useState('')
  useEffect(() => () => { if (original) URL.revokeObjectURL(original.url) }, [original])
  const source = session?.sources?.find(item => item.visual_page_id === selected)
  useEffect(() => {
    const target = targetSourceId && document.getElementById(`source-review-${targetSourceId}`)
    if (target) { target.focus(); target.scrollIntoView?.({ block: 'nearest' }) }
  }, [targetSourceId, session?.id])
  async function inspect(item: ReviewSource) {
    setWorking(true); setError(''); setLoaded(false); setOriginal(null); setSelected(item.visual_page_id); setReason(''); setManual(false)
    try {
      const result = await createApiObjectUrl(`${builderBase}/visual-pages/${item.visual_page_id}/review-original`)
      setOriginal({ url: result.url, receipt: result.reviewReceipt || null, source: item })
    } catch (caught) { setError(t(guidedError(caught))) } finally { setWorking(false) }
  }
  async function verify(correction = false) {
    if (!original?.receipt || !loaded) return
    setWorking(true); setError('')
    try {
      await api(`${builderBase}/visual-pages/${original.source.visual_page_id}/${correction ? 'selection-correction' : 'review'}`, { method: 'POST', body: JSON.stringify({
        expected_version: original.source.version, fingerprint: original.source.fingerprint,
        inspection_token: original.receipt, reason, manual_transcription: manual,
      }) })
      await reload(); setOriginal(null); setSelected(null)
    } catch (caught) { setError(t(guidedError(caught))) } finally { setWorking(false) }
  }
  async function resolve(id: number, version: number, action: string) {
    setWorking(true); setError('')
    try {
      await api(`${builderBase}/extraction-candidates/${id}`, { method: 'PATCH', body: JSON.stringify({
        expected_version: version, action, reason, ...(action === 'LINK_EXISTING' ? { part_id: Number(link) } : {}),
      }) })
      setOriginal(null); await reload()
    } catch (caught) { setError(t(guidedError(caught))) } finally { setWorking(false) }
  }
  return <section className="guided-source-results" aria-label={t('guided.sourceReview')}>
    <h4>{t('guided.sourceReview')}</h4><p>{t('guided.sourceReviewHelp')}</p>
    {error && <p role="alert" className="error">{error}</p>}
    {session?.sources?.map(item => <div key={item.id}>
      <b>{item.source.filename} · {t('guided.physicalPage', { number: item.source.page_number })}</b>
      {' · '}{t(`guided.processing.${item.processing_state}`)}{' · '}{t(`guided.reviewState.${item.review_state}`)}
      <details><summary>{t('guided.attemptCount', { count: item.attempts.length })}</summary>
        {item.attempts.map(attempt => <p key={attempt.id}>{t(`guided.processing.${attempt.state}`)} · {t('guided.sourceRows', { count: attempt.row_count })}</p>)}
      </details>
      <button id={`source-review-${item.visual_page_id}`} className="secondary" disabled={busy || working || item.processing_state === 'RUNNING'} onClick={() => void inspect(item)}>{t('guided.sourceView')}</button>
    </div>)}
    {source && <section>
      {original && <><div className="guided-original"><a href={original.url} target="_blank" rel="noopener noreferrer" aria-label={t('guided.zoomOriginal')}>
        <img src={original.url} alt={t('guided.physicalPage', { number: source.source.page_number })}
          onLoad={() => setLoaded(true)} onError={() => { setLoaded(false); setError(t('builder.previewError')) }} /></a></div>
        <p className="muted">{t('guided.zoomOriginal')}</p></>}
      <label>{t('guided.reviewReason')}<textarea value={reason} maxLength={2000} onChange={event => setReason(event.target.value)} /></label>
      {source.candidates.filter(candidate => candidate.state === 'CONFLICT').map(candidate => <div key={candidate.id} role="alert">
        <p>{t('guided.rowConflict')} · {candidate.original.payload.position} · {candidate.original.payload.part_number}</p>
        <label>{t('guided.linkExisting')}<select value={link} onChange={event => setLink(event.target.value)}>
          <option value="">{t('guided.select')}</option>{parts.map(part => <option key={part.id} value={part.id}>{part.position} · {part.part_number}</option>)}
        </select></label>
        <button className="secondary" disabled={working || reason.trim().length < 10 || !link} onClick={() => void resolve(candidate.id, candidate.version, 'LINK_EXISTING')}>{t('guided.linkExisting')}</button>
        <button className="secondary" disabled={working || reason.trim().length < 10} onClick={() => void resolve(candidate.id, candidate.version, 'NEW_VARIANT')}>{t('guided.newVariant')}</button>
        <button className="secondary" disabled={working || reason.trim().length < 10} onClick={() => void resolve(candidate.id, candidate.version, 'REJECT')}>{t('guided.reject')}</button>
      </div>)}
      <label><input type="checkbox" checked={manual} onChange={event => setManual(event.target.checked)} />{t('guided.manualTranscription')}</label>
      <button className="primary" disabled={busy || working || !loaded || !original?.receipt || reason.trim().length < 10
        || source.candidates.some(candidate => ['PENDING', 'CONFLICT'].includes(candidate.state))}
        onClick={() => void verify()}>{t('guided.verifySource')}</button>
      {source.candidates.every(candidate => candidate.state === 'REJECTED') && <button className="secondary"
        disabled={busy || working || !loaded || !original?.receipt || reason.trim().length < 10}
        onClick={() => void verify(true)}>{t('guided.correctSelection')}</button>}
    </section>}
  </section>
}
