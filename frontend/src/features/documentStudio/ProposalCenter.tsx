import { useCallback, useEffect, useState } from 'react'
import { api, createApiObjectUrl } from '../../api'
import { Modal } from '../../industrialUi'
import { useI18n, type TranslationKey } from '../../i18n'
import { hasPermission } from '../../permissions'
import { studioError, type Draft, type StudioTemplate } from './shared'

type Status = 'PENDING' | 'ACCEPTED' | 'REJECTED'
type Proposal = {
  id: number; template_id: number; target_version_id: number; target_version: number; language: 'bg' | 'en' | 'ru';
  template_name: { bg: string; en: string | null; ru: string | null }; author_name: string;
  title: string; description: string; status: Status; revision: number; created_at: string; newer_published: boolean;
  decision_reason: string | null; decided_at: string | null; decided_by_name: string | null;
  attachments?: { id: number; download_endpoint: string }[];
  events_before?: number | null;
  events?: { version_number: number | null; id: number; kind: 'CREATED' | 'COMMENT' | 'ACCEPTED' | 'REJECTED' | 'DRAFT_CREATED' | 'PUBLISHED'; body: string; author_name: string; created_at: string; draft_id: number | null; version_id: number | null }[];
  drafts?: { draft_id: number; base_version_id: number }[];
}
type Page = { items: Proposal[]; total: number; pending_count: number }

function EvidenceImage({ path, number }: { path: string; number: number }) {
  const { t } = useI18n(), [url, setUrl] = useState(''), [failed, setFailed] = useState(false), [enlarged, setEnlarged] = useState(false)
  useEffect(() => {
    let live = true, object = ''
    void createApiObjectUrl(path).then(value => { object = value.url; if (live) setUrl(object); else URL.revokeObjectURL(object) }).catch(() => { if (live) setFailed(true) })
    return () => { live = false; if (object) URL.revokeObjectURL(object) }
  }, [path])
  const label = t('proposal.evidence', { number })
  return <>{failed ? <p role="alert">{t('proposal.imageError')}</p> : url && <button className="studio-evidence" onClick={() => setEnlarged(true)}><img src={url} alt={label} /><span>{label}</span></button>}{enlarged && <Modal title={label} onClose={() => setEnlarged(false)} wide><img className="studio-evidence-full" src={url} alt={label} /></Modal>}</>
}

export function ProposalCenter({ initialId, pendingChanged, openTemplate, openDraft, onDirty }: {
  initialId: number | null; pendingChanged: (count: number) => void; openTemplate: (id: number) => void;
  openDraft: (draft: Draft) => void; onDirty: (dirty: boolean) => void
}) {
  const { t, locale } = useI18n(), manage = hasPermission('templates.manage')
  const [page, setPage] = useState<Page>({ items: [], total: 0, pending_count: 0 }), [selected, setSelected] = useState<number | null>(initialId)
  const [detail, setDetail] = useState<Proposal | null>(null), [templates, setTemplates] = useState<StudioTemplate[]>([])
  const [status, setStatus] = useState(''), [language, setLanguage] = useState(''), [query, setQuery] = useState(''), [templateFilter, setTemplateFilter] = useState(''), [offset, setOffset] = useState(0)
  const [comment, setComment] = useState(''), [reason, setReason] = useState(''), [draftTitle, setDraftTitle] = useState(''), [baseId, setBaseId] = useState('')
  const [busy, setBusy] = useState(false), [loading, setLoading] = useState(true), [error, setError] = useState<TranslationKey | null>(null)
  const dirty = !!(comment || reason || draftTitle)
  useEffect(() => { onDirty(dirty || busy); return () => onDirty(false) }, [dirty, busy, onDirty])
  const load = useCallback(async (signal?: AbortSignal) => {
    const params = new URLSearchParams({ limit: '20', offset: String(offset) })
    if (status) params.set('status', status)
    if (language) params.set('language', language)
    if (templateFilter) params.set('template_id', templateFilter)
    if (query) params.set('q', query)
    const rows = await api<Page>(`/studio/proposals?${params}`, { signal })
    if (!signal?.aborted) { setPage(rows); pendingChanged(rows.pending_count) }
  }, [status, language, templateFilter, query, offset, pendingChanged])
  useEffect(() => {
    let live = true
    const controller = new AbortController()
    const timer = window.setTimeout(() => { if (live) void load(controller.signal).catch(e => { if (live) setError(studioError(e)) }).finally(() => { if (live) setLoading(false) }) }, 200)
    return () => { live = false; controller.abort(); clearTimeout(timer) }
  }, [load])
  useEffect(() => { let live = true; void api<StudioTemplate[]>('/studio/templates').then(rows => { if (live) setTemplates(rows) }).catch(e => { if (live) setError(studioError(e)) }); return () => { live = false } }, [])
  useEffect(() => {
    let live = true; setDetail(null); setComment(''); setReason(''); setDraftTitle(''); setBaseId(''); setError(null)
    if (selected !== null) void api<Proposal>(`/studio/proposals/${selected}`).then(p => { if (live) setDetail(p) }).catch(e => { if (live) setError(studioError(e)) })
    return () => { live = false }
  }, [selected])
  const date = (value: string) => new Intl.DateTimeFormat(locale, { dateStyle: 'medium', timeStyle: 'short', timeZone: 'UTC' }).format(new Date(/[Z+]$|[+-]\d{2}:\d{2}$/.test(value) ? value : value + 'Z'))
  async function action(kind: 'comments' | 'decision' | 'drafts', decision?: Status) {
    if (!detail) return
    setBusy(true); setError(null)
    try {
      const payload = kind === 'comments' ? { body: comment } : kind === 'decision' ? { status: decision, reason } : { title: draftTitle, base_version_id: baseId ? Number(baseId) : null }
      const result = await api<Proposal | Draft>(`/studio/proposals/${detail.id}/${kind}`, { method: 'POST', body: JSON.stringify({ expected_revision: detail.revision, ...payload }) })
      setComment(''); setReason(''); setDraftTitle('')
      if (kind === 'drafts') { openDraft(result as Draft); return }
      setDetail(result as Proposal); await load()
    } catch (e) { setError(studioError(e)) } finally { setBusy(false) }
  }
  const template = templates.find(row => row.id === detail?.template_id)
  const target = template?.versions.find(row => row.id === detail?.target_version_id)
  const candidates = template?.versions.filter(v => v.studio && v.status === 'PUBLISHED' && v.language === detail?.language && v.version > detail.target_version) || []
  const canDraft = !!baseId || !!target?.studio
  return <section aria-label={t('proposal.center')}>
    <div className="panel"><div className="panel-title"><h3>{t('proposal.center')}</h3><span className="badge">{t('proposal.pendingCount', { count: page.pending_count })}</span></div>
      {!manage && <p>{t('proposal.own')}</p>}
      <div className="studio-fields"><label>{t('studio.search')}<input type="search" maxLength={200} value={query} onChange={e => { setQuery(e.target.value); setOffset(0) }} /></label>
        <label>{t('proposal.status')}<select value={status} onChange={e => { setStatus(e.target.value); setOffset(0) }}><option value="">{t('studio.all')}</option>{(['PENDING', 'ACCEPTED', 'REJECTED'] as const).map(s => <option key={s} value={s}>{t(`proposal.${s}`)}</option>)}</select></label>
        <label>{t('admin.templateLanguage')}<select value={language} onChange={e => { setLanguage(e.target.value); setOffset(0) }}><option value="">{t('studio.all')}</option>{(['bg', 'en', 'ru'] as const).map(l => <option key={l} value={l}>{t(`language.${l}`)}</option>)}</select></label>
        <label>{t('studio.library')}<select value={templateFilter} onChange={e => { setTemplateFilter(e.target.value); setOffset(0) }}><option value="">{t('studio.all')}</option>{templates.map(row => <option key={row.id} value={row.id}>{row[`name_${locale}`] || row.name_bg}</option>)}</select></label></div>
    </div>
    {error && <p className="error" role="alert">{t(error)} <button disabled={busy} className="secondary" onClick={async () => { try { await load(); if (selected) setDetail(await api<Proposal>(`/studio/proposals/${selected}`)); setError(null) } catch (e) { setError(studioError(e)) } }}>{t('studio.reload')}</button></p>}
    <div className="studio-proposals-grid"><div className="panel studio-proposal-list">
      {loading ? <p role="status">{t('studio.loading')}</p> : !page.items.length && <p>{t('proposal.empty')}</p>}
      {page.items.map(p => <button disabled={busy} className="studio-proposal-card" aria-current={p.id === selected ? 'page' : undefined} key={p.id} onClick={() => { if (!dirty || window.confirm(t('studio.leave'))) setSelected(p.id) }}><b>#{p.id} · {p.title}</b><span className={`studio-status ${p.status}`}>{t(`proposal.${p.status}`)}</span><small>{p.template_name[locale] || p.template_name.bg} · {t('studio.version', { number: p.target_version })} · {t(`language.${p.language}`)}</small><small>{p.author_name} · {date(p.created_at)}</small><span className="studio-proposal-excerpt">{p.description}</span></button>)}
      <div className="studio-proposal-pager"><button className="secondary" disabled={!offset || busy} onClick={() => setOffset(n => n - 20)}>{t('proposal.previous')}</button><small>{t('proposal.count', { count: page.total })}</small><button className="secondary" disabled={offset + 20 >= page.total || busy} onClick={() => setOffset(n => n + 20)}>{t('proposal.next')}</button></div>
    </div>{detail && <article className="panel studio-proposal-detail">
      <div className="panel-title"><h3>#{detail.id} · {detail.title}</h3><span className={`studio-status ${detail.status}`}>{t(`proposal.${detail.status}`)}</span></div>
      <p>{t('proposal.author')}: {detail.author_name} · {date(detail.created_at)}</p>
      <p><strong>{t('proposal.target')}</strong><br />{detail.template_name[locale] || detail.template_name.bg} · {t('studio.version', { number: detail.target_version })} · {t(`language.${detail.language}`)}</p>
      {detail.newer_published && <p className="studio-notice">{t('proposal.newer')}</p>}
      <p className="studio-proposal-body">{detail.description}</p><button disabled={busy} className="secondary" onClick={() => { if (!dirty || window.confirm(t('studio.leave'))) openTemplate(detail.template_id) }}>{t('proposal.openTemplate')}</button>
      <div className="studio-proposal-images">{detail.attachments?.map((image, i) => <EvidenceImage key={image.id} path={image.download_endpoint} number={i + 1} />)}</div>
      {detail.decision_reason && <div className="studio-notice"><strong>{t('proposal.decision')}</strong><p>{detail.decided_by_name} · {detail.decided_at && date(detail.decided_at)}</p><p className="studio-proposal-body">{detail.decision_reason}</p></div>}
      <h4>{t('proposal.history')}</h4>{detail.events_before && <button className="secondary" disabled={busy} onClick={async () => { setBusy(true); try { const older = await api<Proposal>(`/studio/proposals/${detail.id}?before_revision=${detail.events_before}`); setDetail(current => current?.id === older.id ? { ...current, events: [...(older.events || []), ...(current.events || [])], events_before: older.events_before } : current) } catch (e) { setError(studioError(e)) } finally { setBusy(false) } }}>{t('proposal.olderHistory')}</button>}<ol className="studio-proposal-timeline">{detail.events?.map(event => <li key={event.id}><strong>{t(`proposal.${event.kind}`)}</strong><small>{event.author_name} · {date(event.created_at)}</small><p className="studio-proposal-body">{event.body}</p>{event.version_id && <span>{t('studio.version', { number: event.version_number || event.version_id })} </span>}{event.draft_id && (manage ? <button className="secondary compact" disabled={busy} onClick={async () => { if (dirty && !window.confirm(t('studio.leave'))) return; try { openDraft(await api<Draft>(`/studio/drafts/${event.draft_id}`)) } catch (e) { setError(studioError(e)) } }}>{t('proposal.draft', { id: event.draft_id })}</button> : <span>{t('proposal.draft', { id: event.draft_id })}</span>)}</li>)}</ol>
      <form className="studio-inline-form" onSubmit={e => { e.preventDefault(); void action('comments') }}><label>{t('proposal.commentText')}<textarea required minLength={3} maxLength={5000} value={comment} disabled={busy} onChange={e => setComment(e.target.value)} /></label><button className="secondary" disabled={busy || comment.trim().length < 3}>{t('proposal.comment')}</button></form>
      {manage && detail.status === 'PENDING' && <div className="studio-inline-form"><label>{t('proposal.reason')}<textarea required minLength={3} maxLength={5000} disabled={busy} value={reason} onChange={e => setReason(e.target.value)} /></label><p>{t('proposal.decisionHint')}</p><div className="studio-proposal-actions"><button className="primary" disabled={busy || reason.trim().length < 3} onClick={() => void action('decision', 'ACCEPTED')}>{t('proposal.accept')}</button><button className="secondary" disabled={busy || reason.trim().length < 3} onClick={() => void action('decision', 'REJECTED')}>{t('proposal.reject')}</button></div></div>}
      {manage && detail.status === 'ACCEPTED' && <form className="studio-inline-form" onSubmit={e => { e.preventDefault(); void action('drafts') }}><h4>{t('proposal.createDraft')}</h4>{!target?.studio && <p className="studio-notice">{t('proposal.referenceOnly')}</p>}<fieldset disabled={busy} className="studio-proposal-fields"><label>{t('proposal.base')}<select value={baseId} onChange={e => setBaseId(e.target.value)}><option value="">{t('proposal.exact')} · {t('studio.version', { number: detail.target_version })}</option>{candidates.map(v => <option key={v.id} value={v.id}>{t('proposal.explicitNewer')} · {t('studio.version', { number: v.version })}</option>)}</select></label><label>{t('studio.draftTitle')}<input required maxLength={255} value={draftTitle} onChange={e => setDraftTitle(e.target.value)} /></label></fieldset><button className="primary" disabled={busy || !canDraft || !draftTitle.trim()}>{t('proposal.createDraft')}</button></form>}
    </article>}</div>
  </section>
}
