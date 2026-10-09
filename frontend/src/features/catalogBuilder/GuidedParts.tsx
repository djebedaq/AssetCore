import { useEffect, useRef, useState } from 'react'
import { api } from '../../api'
import { useI18n } from '../../i18n'
import { guidedError } from './guidedErrors'
import usePagePreview from './usePagePreview'
import RevisionParts from './RevisionParts'
import DurableSourceReview from './DurableSourceReview'
import { builderBase } from './wizardTypes'
import type { PartValues, Preview, ReferencePage, ReviewSession, Source } from './guidedTypes'

type ReviewRow = { part: PartValues; selected: boolean; rejected: boolean; confirmed: boolean; reason: string }
type Review = { preview: Preview; rows: ReviewRow[] }
type SourceResult = { source: Source; state: 'pending' | 'processed' | 'failed'; error?: ReturnType<typeof guidedError> }
const fields = ['position', 'part_number', 'description', 'quantity', 'technical_notes', 'technical_specification'] as const
const roles = ['unknown', ...fields] as const

function Original({ artifactId, number }: { artifactId: number; number: number }) {
  const { t } = useI18n()
  const preview = usePagePreview(artifactId, number)
  return <div className="guided-original">{preview.error ? <div role="alert"><p>{t('builder.previewError')}</p><button className="secondary" onClick={preview.retry}>{t('wizard.retry')}</button></div> : preview.url ? <img src={preview.url} onError={preview.failed} alt={t('guided.physicalPage', { number })} /> : <p role="status">{t('builder.previewPending')}</p>}</div>
}

function Mapping({ preview, tableIndex, apply, busy }: { preview: Preview; tableIndex: number;
  apply: (mapping: Record<string, string>) => void; busy: boolean }) {
  const { t } = useI18n()
  const table = preview.tables[tableIndex]
  const [mapping, setMapping] = useState<Record<string, string>>(table.schema.mapping)
  return <section><h4>{t('guided.mapping')}</h4><div className="guided-column-grid">{table.headers.map((header, index) =>
    <label key={index}><b>{header || t('guided.column', { number: index + 1 })}</b>
      {table.sample_cells.slice(0, 3).map((cells, row) => <span key={row}>{cells[index] || t('common.noValue')}</span>)}
      <select disabled={busy} value={mapping[String(index)] || 'unknown'} onChange={event => setMapping(current => ({ ...current, [index]: event.target.value }))}>
        {roles.map(role => <option key={role} value={role}>{t(`guided.${role}`)}</option>)}
      </select></label>)}</div>
    <button className="secondary" disabled={busy} onClick={() => apply(Object.fromEntries(table.headers.map((_, index) => [String(index), mapping[String(index)] || 'unknown'])))}>{t('guided.reread')}</button>
  </section>
}

export default function GuidedParts({ page, changed, onDirtyChange, targetSourceId }: { page: ReferencePage; targetSourceId?: number;
  changed: () => Promise<void>; onDirtyChange: (dirty: boolean) => void }) {
  const { t } = useI18n()
  const [reviews, setReviews] = useState<Review[]>([])
  const [sourceResults, setSourceResults] = useState<SourceResult[]>([])
  const [accepted, setAccepted] = useState<Array<PartValues & { id: number }>>([])
  const [busy, setBusy] = useState(false)
  const [progress, setProgress] = useState<{ current: number; total: number } | null>(null)
  const [filter, setFilter] = useState<'all' | 'attention' | 'errors' | 'rejected' | 'clean' | 'accepted'>('all')
  const [search, setSearch] = useState('')
  const [sourceIndex, setSourceIndex] = useState<number | null>(null)
  const [error, setError] = useState('')
  const [advancedDirty, setAdvancedDirty] = useState(false)
  const [session, setSession] = useState<ReviewSession | null>(null)
  const [unsaved, setUnsaved] = useState(false)
  const saveQueue = useRef<Promise<void>>(Promise.resolve())
  const editGeneration = useRef(0)
  const candidateVersions = useRef(new Map<number, number>())
  const [pendingEdit, setPendingEdit] = useState<{ source: number; index: number } | null>(null)
  useEffect(() => {
    if (!pendingEdit) return
    const timer = setTimeout(() => saveRow(pendingEdit.source, pendingEdit.index), 600)
    return () => clearTimeout(timer)
  }, [pendingEdit])
  function review(preview: Preview): Review {
    return { preview, rows: preview.rows.map(row => ({ part: { ...row.payload },
      selected: !row.warnings.length && !['ACCEPTED', 'REJECTED', 'CONFLICT'].includes(row.candidate_state || ''),
      rejected: row.candidate_state === 'REJECTED', confirmed: row.candidate_state === 'ACCEPTED', reason: '' })) }
  }
  async function load() {
    const [parts, durable] = await Promise.all([
      api<Array<PartValues & { id: number }>>(`${builderBase}/reference-pages/${page.id}/parts`),
      api<ReviewSession>(`${builderBase}/reference-pages/${page.id}/review-session`, { method: 'POST' }),
    ])
    if (!Array.isArray(durable.sources)) throw new Error('review_session_invalid')
    setAccepted(parts); setSession(durable)
    candidateVersions.current = new Map(durable.sources.flatMap(source => source.preview?.rows || [])
      .flatMap(row => row.candidate_id && row.candidate_version ? [[row.candidate_id, row.candidate_version] as const] : []))
    setReviews(durable.sources.flatMap(source => source.preview ? [review(source.preview)] : []))
  }
  useEffect(() => { void load().catch(() => setError(t('guided.error'))) }, [page.id, page.version])
  useEffect(() => { onDirtyChange(busy || unsaved || advancedDirty); return () => onDirtyChange(false) }, [busy, unsaved, advancedDirty, onDirtyChange])
  const sources = page.sources.filter(source => source.role === 'SPARE_PARTS_LIST')
    .sort((a, b) => (a.sort_order ?? 0) - (b.sort_order ?? 0))
  async function extractSource(source: Source, previous: string | null): Promise<string | null> {
    try {
      const result = await api<Preview>(`${builderBase}/reference-pages/${page.id}/extract`, { method: 'POST', body: JSON.stringify({
        visual_page_id: source.id, continuation_token: previous,
      }) })
      setReviews(current => [...current.filter(item => item.preview.source.visual_page_id !== source.id), review(result)]
        .sort((a, b) => sources.findIndex(s => s.id === a.preview.source.visual_page_id) - sources.findIndex(s => s.id === b.preview.source.visual_page_id)))
      setSourceResults(current => current.map(item => item.source.id === source.id ? { source, state: 'processed' } : item))
      return result.token
    } catch (caught) {
      setSourceResults(current => current.map(item => item.source.id === source.id ? { source, state: 'failed', error: guidedError(caught) } : item))
      return null
    }
  }
  async function retrySource(source: Source) {
    setBusy(true)
    const prior = sources[sources.findIndex(item => item.id === source.id) - 1]
    try { await extractSource(source, reviews.find(item => item.preview.source.visual_page_id === prior?.id)?.preview.token ?? null) }
    finally {
      try { await load() } catch (caught) { setError(t(guidedError(caught))) }
      setBusy(false)
    }
  }
  async function extract() {
    if (busy || !sources.length) return
    setBusy(true); setError(''); setReviews([])
    setSourceResults(sources.map(source => ({ source, state: 'pending' })))
    let previous: string | null = null
    try {
      for (const [index, source] of sources.entries()) {
        setProgress({ current: index + 1, total: sources.length })
        previous = await extractSource(source, previous)
      }
    } catch (caught) { setError(t(guidedError(caught))) } finally {
      try { await load() } catch (caught) { setError(t(guidedError(caught))) }
      setBusy(false); setProgress(null)
    }
  }
  function edit(source: number, index: number, values: Partial<ReviewRow>) {
    if (values.part) { setUnsaved(true); editGeneration.current += 1; setPendingEdit({ source, index }) }
    setReviews(current => current.map((item, sourceIndex) => sourceIndex !== source ? item : {
      ...item, rows: item.rows.map((row, rowIndex) => rowIndex !== index ? row : { ...row, ...values }),
    }))
  }
  function saveRow(source: number, index: number, action = 'SAVE') {
    setPendingEdit(null)
    const item = reviews[source], row = item.rows[index], candidate = item.preview.rows[index]
    if (!candidate.candidate_id) return
    const generation = editGeneration.current
    saveQueue.current = saveQueue.current.catch(() => {}).then(async () => {
      setError('')
      const result = await api<{ version: number; state: string }>(`${builderBase}/extraction-candidates/${candidate.candidate_id}`, { method: 'PATCH', body: JSON.stringify({
        expected_version: candidateVersions.current.get(candidate.candidate_id!) ?? candidate.candidate_version, action, ...(action === 'SAVE' ? { values: row.part } : { reason: row.reason }),
      }) })
      candidateVersions.current.set(candidate.candidate_id!, result.version)
      setReviews(current => current.map(value => ({ ...value,
        preview: { ...value.preview, rows: value.preview.rows.map(value => value.candidate_id === candidate.candidate_id
          ? { ...value, candidate_version: result.version, candidate_state: result.state } : value) },
        rows: value.rows.map((row, i) => value.preview.rows[i]?.candidate_id === candidate.candidate_id
          ? { ...row, rejected: result.state === 'REJECTED' } : row),
      })))
      if (editGeneration.current === generation) setUnsaved(false)
      setSession(await api<ReviewSession>(`${builderBase}/reference-pages/${page.id}/review-session`, { method: 'POST' }))
    })
    void saveQueue.current.catch(caught => setError(t(guidedError(caught))))
  }
  async function remap(index: number, tableIndex: number, mapping: Record<string, string>) {
    setBusy(true); setError('')
    try {
      const result: Preview = await api<Preview>(`${builderBase}/reference-pages/${page.id}/extraction/mapping`, {
        method: 'POST', body: JSON.stringify({ token: reviews[index].preview.token, table_index: tableIndex, mapping }),
      })
      setReviews(current => current.map((item, source) => source === index ? {
        ...review(result), rows: result.rows.map((row, resultIndex) => {
          const box = item.preview.tables[tableIndex].bbox
          const inMappedTable = box && row.bbox && box[0] <= row.bbox[0] && box[1] <= row.bbox[1] && row.bbox[2] <= box[2] && row.bbox[3] <= box[3]
          const prior = !inMappedTable && item.preview.rows.findIndex(old => old.raw_text === row.raw_text && JSON.stringify(old.bbox) === JSON.stringify(row.bbox))
          return typeof prior === 'number' && prior >= 0 ? item.rows[prior] : review(result).rows[resultIndex]
        }),
      } : item))
    } catch (caught) { setError(t(guidedError(caught))) } finally { setBusy(false) }
  }
  async function confirm() {
    if (busy) return
    setBusy(true); setError('')
    try {
      await saveQueue.current
      for (const [source, item] of reviews.entries()) {
        const rows = item.rows.flatMap((row, index) => row.selected && !row.rejected && !row.confirmed ? [{ index, part: row.part,
          expected_version: candidateVersions.current.get(item.preview.rows[index].candidate_id!) ?? item.preview.rows[index].candidate_version }] : [])
        if (!rows.length) continue
        await api(`${builderBase}/reference-pages/${page.id}/extraction/confirm`, { method: 'POST', body: JSON.stringify({
          token: item.preview.token, rows, confirm_warnings: true,
        }) })
        setReviews(current => current.map((value, index) => index !== source ? value : {
          ...value, rows: value.rows.map(row => row.selected && !row.rejected ? { ...row, selected: false, confirmed: true } : row),
        }))
      }
      setUnsaved(false); await load(); await changed()
    } catch (caught) { setError(t(guidedError(caught))) } finally { setBusy(false) }
  }
  return <section className="guided-parts">
    {error && <p role="alert" className="error">{error}</p>}
    {!page.spare_list_count && <p role="status">{t('guided.noLists')}</p>}
    <details><summary>{t('guided.advanced')}</summary><RevisionParts assemblyId={page.assembly_id} referencePageId={page.id} editable onChanged={async () => { await load(); await changed() }} onDirtyChange={setAdvancedDirty} /></details>
    {unsaved && <p role="status">{t('guided.savingChanges')}</p>}
    <DurableSourceReview session={session} targetSourceId={targetSourceId} reload={async () => { await load(); await changed() }} parts={accepted} busy={busy || unsaved} />
    <button className="primary" disabled={busy || unsaved || !!sourceResults.length || !page.spare_list_count} onClick={() => void extract()}>{t('guided.extract')}</button>
    {progress && <p role="status">{t('guided.extracting', progress)}</p>}
    {!!sourceResults.length && <div className="guided-source-results" aria-label={t('guided.lists')}>
      {sourceResults.map(result => {
        const item = reviews.find(value => value.preview.source.visual_page_id === result.source.id)
        const attention = result.state === 'failed' || !!item && (!item.rows.length || item.preview.warnings.length > 0
          || item.preview.tables.some(table => table.schema.state !== 'RESOLVED') || item.preview.rows.some(row => row.warnings.length))
        return <div key={result.source.id} role={attention ? 'alert' : 'status'}>
          <b>{result.source.filename} · {t('guided.physicalPage', { number: result.source.page_number })}</b>
          {' · '}{t(result.state === 'pending' ? 'builder.previewPending' : attention ? 'guided.NEEDS_ATTENTION' : 'guided.clean')}
          {item && <> · {t('guided.sourceRows', { count: item.rows.length })}</>}
          {result.error && <p>{t(result.error)}</p>}
          {result.state === 'failed' && <button className="secondary" disabled={busy || unsaved} onClick={() => void retrySource(result.source)}>{t('wizard.retry')}</button>}
        </div>
      })}
      <p role="status">{t('guided.sourceTotal', { count: reviews.reduce((total, item) => total + item.rows.length, 0), processed: sourceResults.filter(item => item.state !== 'pending').length, total: sourceResults.length })}</p>
      {!reviews.length && !busy && <button className="secondary" onClick={() => setSourceResults([])}>{t('common.close')}</button>}
    </div>}
    {accepted.length > 0 && <details><summary>{t('guided.review')} ({accepted.length})</summary>
      {accepted.map(part => <p key={part.id}>{part.position} · {part.part_number} · {part.description} · {part.quantity}</p>)}</details>}
    {!!reviews.length && <>
      <h4>{t('guided.review')}</h4>
      <p role="status">{t('guided.summary', { count: reviews.reduce((total, item) => total + item.rows.length, 0), selected: reviews.reduce((total, item) => total + item.rows.filter(row => row.selected).length, 0) })}</p>
      <div className="actions"><label>{t('guided.filter')}<select value={filter} onChange={event => setFilter(event.target.value as typeof filter)}>
        {(['attention', 'all', 'clean', 'errors', 'accepted', 'rejected'] as const).map(value => <option value={value} key={value}>{t(`guided.${value}`)}</option>)}
      </select></label><label>{t('common.search')}<input value={search} onChange={event => setSearch(event.target.value)} /></label>
        <button className="secondary" disabled={busy} onClick={() => setReviews(current => current.map(item => ({ ...item,
          rows: item.rows.map((row, index) => ({ ...row, selected: !row.rejected && !row.confirmed && !item.preview.rows[index].warnings.length })),
        })))}>{t('guided.selectClean')}</button>
      </div>
      {reviews.map((item, source) => <section key={source}>
        <h4>{item.preview.source.filename} · {t('guided.physicalPage', { number: item.preview.source.page_number })} ({item.rows.length})</h4>
        {(['OCR_UNAVAILABLE', 'OCR_DISABLED', 'OCR_PIXEL_LIMIT', 'TABLE_DETECTION_FAILED', 'CONTINUATION_UNRESOLVED'] as const)
          .filter(warning => item.preview.warnings.includes(warning)).map(warning => <p role="alert" key={warning}>{t(`guided.${warning}`)}</p>)}
        {!item.rows.length && <p role="status">{t('guided.noRows')}</p>}
        {item.preview.tables.map((table, tableIndex) => table.schema.state !== 'RESOLVED' ? <Mapping
          key={`${item.preview.token.slice(-12)}-${tableIndex}`} preview={item.preview} tableIndex={tableIndex} busy={busy || unsaved} apply={mapping => void remap(source, tableIndex, mapping)} /> : <details key={`${item.preview.token.slice(-12)}-${tableIndex}`}><summary>{t('guided.mapping')}</summary><Mapping
          preview={item.preview} tableIndex={tableIndex} busy={busy || unsaved || item.rows.some(row => row.confirmed)} apply={mapping => void remap(source, tableIndex, mapping)} /></details>)}
        <button className="secondary" onClick={() => setSourceIndex(sourceIndex === source ? null : source)}>{t('guided.sourceView')}</button>
        {sourceIndex === source && <Original artifactId={item.preview.source.artifact_id} number={item.preview.source.page_number} />}
        <div className="table-wrap"><table><thead><tr><th>{t('guided.selected', { count: item.rows.filter(row => row.selected).length })}</th>
          {fields.slice(0, 4).map(field => <th key={field}>{t(`guided.${field}`)}</th>)}<th>{t('guided.review')}</th></tr></thead>
          <tbody>{item.rows.map((row, index) => {
            const warnings = item.preview.rows[index].warnings
            if ((filter === 'attention' && !warnings.length || filter === 'errors' && row.part.position && row.part.part_number && row.part.description
              || filter === 'clean' && !!warnings.length || filter === 'accepted' && !row.confirmed
              || filter === 'rejected' && !row.rejected || filter !== 'rejected' && row.rejected
              || filter !== 'accepted' && filter !== 'all' && row.confirmed)
              || !Object.values(row.part).join(' ').toLocaleLowerCase().includes(search.toLocaleLowerCase())) return null
            return <tr key={index} className={warnings.length && !row.confirmed ? 'part-attention' : ''}><td><input type="checkbox" aria-label={t('guided.position') + ' ' + row.part.position} disabled={busy || row.rejected || row.confirmed}
              checked={row.selected} onChange={event => edit(source, index, { selected: event.target.checked })} /></td>
              {fields.slice(0, 4).map(field => <td key={field}><input aria-label={t(`guided.${field}`) + ' ' + (index + 1)} disabled={busy || row.rejected || row.confirmed}
                value={row.part[field] ?? ''} onChange={event => edit(source, index, { part: { ...row.part, [field]: event.target.value || null } })} onBlur={() => { if (unsaved) void saveRow(source, index) }} /></td>)}
              <td><details><summary>{t('guided.advanced')}</summary>{fields.slice(4).map(field => <label key={field}>{t(`guided.${field}`)}<input aria-label={t(`guided.${field}`) + ' ' + (index + 1)} value={row.part[field] ?? ''} disabled={busy || row.confirmed || row.rejected} onChange={event => edit(source, index, { part: { ...row.part, [field]: event.target.value || null } })} onBlur={() => { if (unsaved) void saveRow(source, index) }} /></label>)}</details><span>{t(row.confirmed ? 'guided.accepted' : warnings.length ? 'guided.attention' : 'guided.clean')}</span>
                <label>{t('guided.reviewReason')}<input value={row.reason} onChange={event => edit(source, index, { reason: event.target.value })} /></label>
                <button className="secondary" disabled={busy || row.confirmed || !row.rejected && row.reason.trim().length < 10} onClick={() => void saveRow(source, index, row.rejected ? 'RESTORE' : 'REJECT')}>{t(row.rejected ? 'guided.restore' : 'guided.reject')}</button></td></tr>
          })}</tbody></table></div>
      </section>)}
      <div className="actions"><button className="primary" disabled={busy || unsaved || !reviews.some(item => item.rows.some(row => row.selected && !row.rejected))} onClick={() => void confirm()}>{t('guided.confirm')}</button>
        <button className="secondary" disabled={busy || unsaved} onClick={() => { setReviews([]); setSourceResults([]); setSourceIndex(null) }}>{t('common.close')}</button></div>
    </>}
  </section>
}
