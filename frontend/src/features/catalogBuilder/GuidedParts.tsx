import { useEffect, useRef, useState } from 'react'
import { api, ApiError, downloadApiFile } from '../../api'
import { useI18n } from '../../i18n'
import { guidedError } from './guidedErrors'
import SourcePageViewer from './SourcePageViewer'
import { evidenceRegion } from './evidenceGeometry'
import Modal from './CatalogDialog'
import RevisionParts from './RevisionParts'
import DurableSourceReview from './DurableSourceReview'
import { builderBase } from './wizardTypes'
import type { PartValues, Preview, ReferencePage, ReviewSession, ReviewSource, Source } from './guidedTypes'

type ReviewRow = { part: PartValues; selected: boolean; rejected: boolean; confirmed: boolean; reason: string }
type Review = { preview: Preview; rows: ReviewRow[] }
type SourceResult = { source: Source; state: 'pending' | 'processed' | 'failed'; error?: ReturnType<typeof guidedError> }
const fields = ['position', 'part_number', 'description', 'quantity', 'technical_notes', 'technical_specification'] as const
const roles = ['unknown', ...fields] as const

// A failed retry can retain durable candidates without a confirmable preview.
// Display those values, but never invent an actor-bound confirmation token.
function retainedPreview(source: ReviewSource, parts: Array<PartValues & { id: number }>): Preview | null {
  return source.preview || (source.candidates.length ? {
    token: '', source: source.source, tables: [], warnings: [], method: '',
    rows: source.candidates.map(candidate => ({ payload: candidate.state === 'ACCEPTED' ? parts.find(part => part.id === candidate.part_id) || candidate.values : candidate.values,
      raw_text: candidate.original.raw_text || '', bbox: candidate.original.bbox, warnings: candidate.original.warnings || [],
      candidate_id: candidate.id, candidate_version: candidate.version, candidate_state: candidate.state })),
  } : null)
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

export default function GuidedParts({ page, changed, onDirtyChange, targetSourceId, targetPartId, stage = 'parts', onContinue }: { page: ReferencePage; targetSourceId?: number; targetPartId?: number; stage?: 'extract' | 'parts'; onContinue?: () => void;
  changed: () => Promise<void>; onDirtyChange: (dirty: boolean) => void }) {
  const { t } = useI18n()
  const [reviews, setReviews] = useState<Review[]>([])
  const [sourceResults, setSourceResults] = useState<SourceResult[]>([])
  const [accepted, setAccepted] = useState<Array<PartValues & { id: number }>>([])
  const [busy, setBusy] = useState(false)
  const [progress, setProgress] = useState<{ current: number; total: number } | null>(null)
  const [filter, setFilter] = useState<'all' | 'attention' | 'errors' | 'rejected' | 'clean' | 'accepted'>('all')
  const [search, setSearch] = useState('')
  const [activeRow, setActiveRow] = useState<string | null | undefined>(undefined)
  const [tools, setTools] = useState(false)
  const [editPartId, setEditPartId] = useState<number | undefined>()
  const editorTitle = useRef<HTMLHeadingElement>(null)
  useEffect(() => { if (activeRow) editorTitle.current?.focus() }, [activeRow])
  const [error, setError] = useState('')
  const [advancedDirty, setAdvancedDirty] = useState(false)
  const [sourceReviewDirty, setSourceReviewDirty] = useState(false)
  const [session, setSession] = useState<ReviewSession | null>(null)
  const [unsaved, setUnsaved] = useState(false)
  const saveQueue = useRef<Promise<void>>(Promise.resolve())
  const candidateVersions = useRef(new Map<number, number>())
  const currentReviews = useRef<Review[]>([])
  const generations = useRef(new Map<number, number>())
  const timers = useRef(new Map<number, ReturnType<typeof setTimeout>>())
  const pending = useRef(new Map<number, { source: number; index: number }>())
  const [saveStates, setSaveStates] = useState<Record<number, 'saving' | 'saved' | 'saveError' | 'conflict'>>({})
  const dirtyIds = useRef(new Set<number>())
  const loadGeneration = useRef(0)
  const scope = useRef(page.id)
  scope.current = page.id
  currentReviews.current = reviews
  useEffect(() => () => { timers.current.forEach(clearTimeout) }, [])
  function review(preview: Preview): Review {
    return { preview, rows: preview.rows.map(row => ({ part: { ...row.payload },
      selected: !!preview.token && valid({ part: row.payload }) && !row.warnings.length && !['ACCEPTED', 'REJECTED', 'CONFLICT'].includes(row.candidate_state || ''),
      rejected: row.candidate_state === 'REJECTED', confirmed: row.candidate_state === 'ACCEPTED', reason: '' })) }
  }
  async function load() {
    const generation = ++loadGeneration.current
    const [parts, durable] = await Promise.all([
      api<Array<PartValues & { id: number }>>(`${builderBase}/reference-pages/${page.id}/parts`),
      api<ReviewSession>(`${builderBase}/reference-pages/${page.id}/review-session`, { method: 'POST' }),
    ])
    if (!Array.isArray(durable.sources)) throw new Error('review_session_invalid')
    if (scope.current !== page.id || dirtyIds.current.size || generation !== loadGeneration.current) return
    setAccepted(parts); setSession(durable)
    candidateVersions.current = new Map(durable.sources.flatMap(source => [
      ...source.candidates.map(candidate => [candidate.id, candidate.version] as const),
      ...(source.preview?.rows || []).flatMap(row => row.candidate_id && row.candidate_version ? [[row.candidate_id, row.candidate_version] as const] : []),
    ]))
    setReviews(durable.sources.flatMap(source => {
      const preview = retainedPreview(source, parts)
      return preview ? [review(preview)] : []
    })
      .sort((a, b) => sources.findIndex(source => source.id === a.preview.source.visual_page_id)
        - sources.findIndex(source => source.id === b.preview.source.visual_page_id)))
  }
  useEffect(() => { void load().catch(() => setError(t('guided.error'))) }, [page.id, page.version])
  useEffect(() => { onDirtyChange(busy || unsaved || advancedDirty || sourceReviewDirty); return () => onDirtyChange(false) }, [busy, unsaved, advancedDirty, sourceReviewDirty, onDirtyChange])
  useEffect(() => {
    const target = session?.sources.flatMap(source => source.candidates).find(candidate => candidate.part_id === targetPartId)
    if (target) setActiveRow(String(target.id))
  }, [session?.id, targetPartId])
  const sources = page.sources.filter(source => source.role === 'SPARE_PARTS_LIST')
    .sort((a, b) => (a.sort_order ?? 0) - (b.sort_order ?? 0))
  async function extractSource(source: Source, previous: string | null, groupContext = false, contextOnly = false): Promise<Preview | null> {
    try {
      const result = await api<Preview>(`${builderBase}/reference-pages/${page.id}/extract`, { method: 'POST', body: JSON.stringify({
        visual_page_id: source.id, continuation_token: previous,
        expected_version: page.version, group_context: groupContext,
        context_only: contextOnly,
      }) })
      setReviews(current => [...current.filter(item => item.preview.source.visual_page_id !== source.id), review(result)]
        .sort((a, b) => sources.findIndex(s => s.id === a.preview.source.visual_page_id) - sources.findIndex(s => s.id === b.preview.source.visual_page_id)))
      setSourceResults(current => current.map(item => item.source.id === source.id ? { source, state: 'processed' } : item))
      return result
    } catch (caught) {
      setSourceResults(current => current.map(item => item.source.id === source.id ? { source, state: 'failed', error: guidedError(caught) } : item))
      return null
    }
  }
  async function retrySource(source: Source) {
    setBusy(true)
    const prior = sources[sources.findIndex(item => item.id === source.id) - 1]
    try { await extractSource(source, reviews.find(item => item.preview.source.visual_page_id === prior?.id)?.preview.token ?? null, true) }
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
    const contextRetry: Source[] = []
    try {
      for (const [index, source] of sources.entries()) {
        setProgress({ current: index + 1, total: sources.length })
        const result = await extractSource(source, previous)
        previous = result?.token ?? null
        if (result?.quality?.needs_context) contextRetry.push(source)
      }
      // The later successful pages may supply semantic roles to an earlier
      // headerless list. The server derives context from the exact ledger scope.
      for (const [index, source] of contextRetry.entries()) {
        setProgress({ current: index + 1, total: contextRetry.length })
        await extractSource(source, null, true, true)
      }
    } catch (caught) { setError(t(guidedError(caught))) } finally {
      try { await load() } catch (caught) { setError(t(guidedError(caught))) }
      setBusy(false); setProgress(null)
    }
  }
  function edit(source: number, index: number, values: Partial<ReviewRow>) {
    const candidate = currentReviews.current[source]?.preview.rows[index]
    if (values.part && candidate?.candidate_id) {
      const id = candidate.candidate_id
      loadGeneration.current += 1
      dirtyIds.current.add(id); setUnsaved(true)
      generations.current.set(id, (generations.current.get(id) || 0) + 1)
      setSaveStates(current => ({ ...current, [id]: 'saving' }))
      pending.current.set(id, { source, index }); clearTimeout(timers.current.get(id))
      timers.current.set(id, setTimeout(() => saveRow(source, index), 600))
    }
    const next = currentReviews.current.map((item, sourceIndex) => sourceIndex !== source ? item : {
      ...item, rows: item.rows.map((row, rowIndex) => rowIndex !== index ? row : { ...row, ...values }),
    })
    currentReviews.current = next; setReviews(next)
  }
  function saveRow(source: number, index: number, action = 'SAVE') {
    const item = currentReviews.current[source], row = item?.rows[index], candidate = item?.preview.rows[index]
    if (!candidate?.candidate_id || !row) return
    const id = candidate.candidate_id
    if (action === 'SAVE' && !pending.current.has(id)) return
    clearTimeout(timers.current.get(id)); pending.current.delete(id)
    const generation = generations.current.get(id) || 0, values = { ...row.part }, reason = row.reason
    const pageId = page.id
    dirtyIds.current.add(id); setUnsaved(true)
    setSaveStates(current => ({ ...current, [id]: 'saving' }))
    saveQueue.current = saveQueue.current.catch(() => {}).then(async () => {
      try {
        const result = await api<{ version: number; state: string }>(`${builderBase}/extraction-candidates/${id}`, { method: 'PATCH', body: JSON.stringify({
          expected_version: candidateVersions.current.get(id) ?? candidate.candidate_version, action, ...(action === 'SAVE' ? { values } : { reason }),
        }) })
        if (scope.current !== pageId) return
        candidateVersions.current.set(id, result.version)
        setReviews(current => current.map(value => ({ ...value,
          preview: { ...value.preview, rows: value.preview.rows.map(value => value.candidate_id === id
            ? { ...value, candidate_version: result.version, candidate_state: result.state } : value) },
          rows: value.rows.map((row, i) => value.preview.rows[i]?.candidate_id === id
            ? { ...row, rejected: result.state === 'REJECTED', confirmed: result.state === 'ACCEPTED' } : row),
        })))
        if ((generations.current.get(id) || 0) === generation) {
          dirtyIds.current.delete(id); setUnsaved(dirtyIds.current.size > 0)
          setSaveStates(current => ({ ...current, [id]: 'saved' }))
        }
        setSession(await api<ReviewSession>(`${builderBase}/reference-pages/${pageId}/review-session`, { method: 'POST' }))
      } catch (caught) {
        if (scope.current === pageId) {
          setSaveStates(current => ({ ...current, [id]: caught instanceof ApiError && caught.status === 409 ? 'conflict' : 'saveError' }))
          setError(t(guidedError(caught)))
        }
        throw caught
      }
    })
    void saveQueue.current.catch(() => {})
  }
  async function reloadRow(id: number) {
    if (!window.confirm(t('catalogUx.reloadConfirm'))) return
    setBusy(true)
    try {
      const durable = await api<ReviewSession>(`${builderBase}/reference-pages/${page.id}/review-session`, { method: 'POST' })
      const source = durable.sources.find(source => source.candidates.some(candidate => candidate.id === id) || source.preview?.rows.some(row => row.candidate_id === id))
      const preview = source ? retainedPreview(source, accepted) : null
      const candidate = preview?.rows.find(row => row.candidate_id === id)
      if (!preview || !candidate) { setError(t('guided.stale')); return }
      clearTimeout(timers.current.get(id)); pending.current.delete(id); loadGeneration.current += 1
      candidateVersions.current.set(id, candidate.candidate_version!)
      setReviews(current => current.map(item => ({ ...item,
        preview: { ...item.preview, rows: item.preview.rows.map(row => row.candidate_id === id ? candidate : row) },
        rows: item.rows.map((row, index) => item.preview.rows[index].candidate_id === id ? review(preview).rows[preview.rows.indexOf(candidate)] : row),
      })))
      dirtyIds.current.delete(id); setUnsaved(dirtyIds.current.size > 0); setError('')
      setSaveStates(current => ({ ...current, [id]: 'saved' })); setSession(durable)
    } catch (caught) { setError(t(guidedError(caught))) } finally { setBusy(false) }
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
    if (busy || unsaved || dirtyIds.current.size) return
    setBusy(true); setError('')
    try {
      await saveQueue.current
      const fresh = await api<ReviewSession>(`${builderBase}/reference-pages/${page.id}/review-session`, { method: 'POST' })
      for (const [source, item] of reviews.entries()) {
        const rows = item.rows.flatMap((row, index) => !!item.preview.token && row.selected && !row.rejected && !row.confirmed && valid(row) && item.preview.rows[index].candidate_state !== 'CONFLICT' ? [{ index, part: row.part,
          expected_version: candidateVersions.current.get(item.preview.rows[index].candidate_id!) ?? item.preview.rows[index].candidate_version }] : [])
        if (!rows.length) continue
        const current = fresh.sources.find(value => value.visual_page_id === item.preview.source.visual_page_id)?.preview
        const conflicting = rows.filter(row => {
          const candidate = item.preview.rows[row.index], latest = current?.rows[row.index]
          return !current || latest?.candidate_id !== candidate.candidate_id || latest?.candidate_version !== row.expected_version
        })
        if (!current || conflicting.length) {
          for (const row of conflicting) {
            const id = item.preview.rows[row.index].candidate_id
            if (id) { dirtyIds.current.add(id); setSaveStates(value => ({ ...value, [id]: 'conflict' })) }
          }
          setUnsaved(true); setError(t('guided.stale')); return
        }
        await api(`${builderBase}/reference-pages/${page.id}/extraction/confirm`, { method: 'POST', body: JSON.stringify({
          token: current.token, rows, confirm_warnings: true,
        }) })
        setReviews(current => current.map((value, index) => index !== source ? value : {
          ...value, rows: value.rows.map((row, index) => rows.some(submitted => submitted.index === index) ? { ...row, selected: false, confirmed: true } : row),
        }))
      }
      setUnsaved(false); await load(); await changed()
    } catch (caught) { setError(t(guidedError(caught))) } finally { setBusy(false) }
  }
  const allRows = reviews.flatMap((item, source) => item.rows.map((row, index) => ({ item, row, source, index,
    candidate: item.preview.rows[index], key: String(item.preview.rows[index].candidate_id ?? `${item.preview.source.visual_page_id}:${index}`) })))
  function valid(row: Pick<ReviewRow, 'part'>) {
    return !!row.part.position?.trim() && !!row.part.part_number?.trim() && !!row.part.description?.trim()
      && row.part.quantity !== null && row.part.quantity !== '' && Number.isFinite(Number(row.part.quantity)) && Number(row.part.quantity) >= 0 && /^\d{1,10}(?:\.\d{1,4})?$/.test(String(row.part.quantity))
  }
  const visible = allRows.filter(({ row, candidate }) => {
    const attention = !valid(row) || candidate.warnings.length > 0 || candidate.candidate_state === 'CONFLICT'
    return (filter === 'all' || filter === 'attention' && attention && !row.confirmed || filter === 'accepted' && row.confirmed
      || filter === 'errors' && !valid(row) || filter === 'clean' && !attention || filter === 'rejected' && row.rejected)
      && (filter === 'rejected' || !row.rejected)
      && [row.part.position, row.part.part_number, row.part.description].join(' ').toLocaleLowerCase().includes(search.toLocaleLowerCase())
  })
  const active = activeRow === undefined ? allRows[0] : allRows.find(row => row.key === activeRow)
  const canSelect = (entry: typeof allRows[number]) => !!entry.item.preview.token && valid(entry.row) && !entry.row.rejected && !entry.row.confirmed && entry.candidate.candidate_state !== 'CONFLICT'
  return <section className="guided-parts" aria-busy={busy}>
    {error && <p role="alert" className="error">{error}</p>}
    {!page.spare_list_count && <p role="status">{t('guided.noLists')}</p>}
    {stage === 'extract' && <>
      <p>{t('catalogUx.recognizeHelp')}</p>
      <button className={allRows.length ? "secondary" : "primary"} disabled={busy || unsaved || !page.spare_list_count} onClick={() => void extract()}>{t('guided.extract')}</button>
      {progress && <p role="status">{t('guided.extracting', progress)}</p>}
      <div className="guided-source-results" aria-label={t('guided.lists')}>
        {sources.map(source => {
          const result = sourceResults.find(value => value.source.id === source.id)
          const item = reviews.find(value => value.preview.source.visual_page_id === source.id)
          const durable = session?.sources.find(value => value.visual_page_id === source.id)
          const failed = result?.state === 'failed' || durable?.processing_state === 'FAILED' || durable?.processing_state === 'CANCELLED'
          const unstarted = !item && durable?.processing_state !== 'RUNNING' && reviews.length > 0
          return <div key={source.id}><b>{source.filename} · {t('guided.physicalPage', { number: source.page_number })}</b>
            {' · '}{t(failed ? 'guided.processing.FAILED' : durable?.review_state === 'VERIFIED' ? 'guided.reviewState.VERIFIED' : item ? 'guided.attention' : 'guided.processing.QUEUED')}
            {item && <> · {t('guided.sourceRows', { count: item.rows.length })}</>}
            {result?.error && <p role="alert">{t(result.error)}</p>}
            {(failed || unstarted || item?.preview.quality?.state === 'NEEDS_REVIEW') && <button className="secondary" disabled={busy || unsaved} onClick={() => void retrySource(source)}>{t('wizard.retry')}</button>}
          </div>
        })}
        <p role="status">{t('guided.sourceTotal', { count: allRows.length, processed: sourceResults.length ? sourceResults.filter(item => item.state !== 'pending').length : session?.sources.filter(item => item.attempts.length).length || 0, total: sources.length })}</p>
      </div>
      {onContinue && <button className="primary" disabled={busy || unsaved || !allRows.length} onClick={onContinue}>{t('catalogUx.step.parts')}</button>}
    </>}
    {stage === 'parts' && <>
      <p role="status">{t('guided.sourceTotal', { count: allRows.length, processed: sourceResults.length ? sourceResults.filter(item => item.state !== 'pending').length : session?.sources.filter(item => item.attempts.length).length || 0, total: sources.length })}</p>
      <div aria-label={t('guided.lists')}>{sources.filter(source => sourceResults.some(result => result.source.id === source.id && result.state === 'failed') || session?.sources.some(item => item.visual_page_id === source.id && ['FAILED', 'CANCELLED'].includes(item.processing_state))).map(source => <div key={source.id} role="alert">
        <b>{source.filename} · {t('guided.physicalPage', { number: source.page_number })}</b><p>{t(sourceResults.find(result => result.source.id === source.id)?.error || 'guided.processing.FAILED')}</p>
        <button className="secondary" disabled={busy || unsaved} onClick={() => void retrySource(source)}>{t('wizard.retry')}</button>
      </div>)}</div>
      <button className={allRows.length ? 'secondary' : 'primary'} disabled={busy || unsaved || !sources.length} onClick={() => void extract()}>{t('guided.extract')}</button>
      {progress && <p role="status">{t('guided.extracting', progress)}</p>}
      <div className="parts-toolbar"><label>{t('guided.filter')}<select value={filter} onChange={event => setFilter(event.target.value as typeof filter)}>
        {(['all', 'attention', 'accepted'] as const).map(value => <option value={value} key={value}>{t(`guided.${value}`)}</option>)}
      </select></label><label>{t('common.search')}<input value={search} onChange={event => setSearch(event.target.value)} /></label>
        <button className="secondary" disabled={busy || unsaved || !visible.some(canSelect)} onClick={() => visible.filter(canSelect).forEach(({ source, index }) => edit(source, index, { selected: true }))}>{t('catalogUx.selectVisible')}</button>
        <button className="secondary" disabled={busy || unsaved} onClick={() => { setEditPartId(undefined); setTools(true) }}>{t('catalogUx.partTools')}</button>
      </div>
      <p className="muted">{t('catalogUx.selectHelp')}</p>
      <p role="status">{t('guided.summary', { count: allRows.length, selected: allRows.filter(entry => entry.row.selected && canSelect(entry)).length })}</p>
      <div className="unified-parts table-wrap"><table><thead><tr>
        <th>{t('guided.selected', { count: allRows.filter(entry => entry.row.selected).length })}</th>
        {fields.slice(0, 4).map(field => <th key={field}>{t(`guided.${field}`)}</th>)}<th>{t('catalogUx.source')}</th>
      </tr></thead><tbody>{visible.map(entry => {
        const { row, item, source, index, candidate, key } = entry
        return <tr key={key} aria-selected={activeRow === key} className={candidate.warnings.length || !valid(row) || candidate.candidate_state === 'CONFLICT' ? 'part-attention' : ''}>
          <td><input type="checkbox" aria-label={`${t('guided.position')} ${row.part.position} · ${item.preview.source.filename} · ${item.preview.source.page_number}`} disabled={busy || unsaved || !canSelect(entry)} checked={row.selected} onChange={event => edit(source, index, { selected: event.target.checked })} /></td>
          <td><button className="secondary part-open" aria-label={t('catalogUx.openPart', { position: row.part.position, number: row.part.part_number, page: item.preview.source.page_number })} onClick={() => {
            pending.current.forEach(value => saveRow(value.source, value.index)); setActiveRow(key)
          }}>{row.part.position || '—'}<small>{t(row.confirmed ? 'guided.accepted' : candidate.candidate_state === 'CONFLICT' ? 'guided.rowConflict' : 'guided.attention')}</small></button></td>
          <td>{row.part.part_number || '—'}</td><td>{row.part.description || '—'}</td><td>{row.part.quantity ?? '—'}</td>
          <td><span title={item.preview.source.filename}>{t('guided.physicalPage', { number: item.preview.source.page_number })}</span><small>{item.preview.source.filename}</small></td>
        </tr>
      })}</tbody></table></div>
      {active ? <section className="part-comparison" aria-label={t('catalogUx.editPart')}>
        <div className="part-original"><SourcePageViewer artifactId={active.item.preview.source.artifact_id} number={active.item.preview.source.page_number} pageCount={active.item.preview.source.page_number} fixed onPage={() => {}} region={evidenceRegion(active.item.preview, active.candidate.bbox)} /><p className="muted">{t('catalogUx.originalHint')}</p><button className="secondary" disabled={busy} onClick={() => {
          setBusy(true); void downloadApiFile(`${builderBase}/artifacts/${active.item.preview.source.artifact_id}/download`, active.item.preview.source.filename).catch(caught => setError(t(guidedError(caught)))).finally(() => setBusy(false))
        }}>{t('builder.downloadSource')}</button></div>
        <div className="part-edit"><div className="source-heading"><h4 ref={editorTitle} tabIndex={-1}>{t('catalogUx.editPart')} · {active.row.part.position}</h4><button className="secondary" onClick={() => { saveRow(active.source, active.index); setActiveRow(null) }}>{t('common.close')}</button></div>
          <p>{active.item.preview.source.filename} · {t('guided.physicalPage', { number: active.item.preview.source.page_number })}</p>
          {fields.slice(0, 4).map(field => <label key={field}>{t(`guided.${field}`)}<input aria-label={t(`guided.${field}`)} disabled={busy || active.row.rejected || active.row.confirmed || active.candidate.candidate_state === 'CONFLICT'} value={active.row.part[field] ?? ''} onChange={event => edit(active.source, active.index, { part: { ...active.row.part, [field]: event.target.value || null } })} onBlur={() => saveRow(active.source, active.index)} /></label>)}
          {active.candidate.candidate_id && saveStates[active.candidate.candidate_id] && <p role={['conflict', 'saveError'].includes(saveStates[active.candidate.candidate_id]) ? 'alert' : 'status'}>{t(`catalogUx.${saveStates[active.candidate.candidate_id]}`)}</p>}
          {active.candidate.candidate_id && saveStates[active.candidate.candidate_id] === 'saveError' && <button className="secondary" onClick={() => { pending.current.set(active.candidate.candidate_id!, active); saveRow(active.source, active.index) }}>{t('wizard.retry')}</button>}
          {active.candidate.candidate_id && saveStates[active.candidate.candidate_id] === 'conflict' && <button className="secondary" disabled={busy} onClick={() => void reloadRow(active.candidate.candidate_id!)}>{t('catalogUx.reloadRow')}</button>}
          {active.row.confirmed && <button className="secondary" disabled={busy || unsaved} onClick={() => {
            setEditPartId(session?.sources.flatMap(source => source.candidates).find(candidate => candidate.id === active.candidate.candidate_id)?.part_id || undefined); setTools(true)
          }}>{t('common.edit')}</button>}
          {!valid(active.row) && <p role="alert">{t('catalogUx.invalidRow')}</p>}
          {active.candidate.warnings.length > 0 && !active.row.confirmed && <p role="status">{t('guided.attention')}</p>}
          {active.candidate.candidate_state === 'CONFLICT' && <p role="alert">{t('guided.rowConflict')}</p>}
          <details><summary>{t('catalogUx.rowTools')}</summary>
            {fields.slice(4).map(field => <label key={field}>{t(`guided.${field}`)}<input value={active.row.part[field] ?? ''} disabled={busy || active.row.confirmed || active.row.rejected || active.candidate.candidate_state === 'CONFLICT'} onChange={event => edit(active.source, active.index, { part: { ...active.row.part, [field]: event.target.value || null } })} onBlur={() => saveRow(active.source, active.index)} /></label>)}
            <label>{t('guided.reviewReason')}<input value={active.row.reason} onChange={event => edit(active.source, active.index, { reason: event.target.value })} /></label>
            <button className="secondary" disabled={busy || unsaved || active.row.confirmed || active.candidate.candidate_state === 'CONFLICT' || !active.row.rejected && active.row.reason.trim().length < 10} onClick={() => saveRow(active.source, active.index, active.row.rejected ? 'RESTORE' : 'REJECT')}>{t(active.row.rejected ? 'guided.restore' : 'guided.reject')}</button>
            <pre className="raw-evidence">{active.candidate.raw_text}</pre><pre className="raw-evidence">{JSON.stringify({ source: active.item.preview.source, geometry: active.item.preview.page_geometry, row: active.candidate, method: active.item.preview.method, quality: active.item.preview.quality, warnings: active.item.preview.warnings, version: active.item.preview.pipeline_version }, null, 2)}</pre>
          </details>
          <details><summary>{t('catalogUx.sourceTools')}</summary>
            {active.item.preview.tables.map((_, tableIndex) => <Mapping key={`${active.item.preview.token.slice(-12)}-${tableIndex}`} preview={active.item.preview} tableIndex={tableIndex} busy={busy || unsaved || active.item.rows.some(row => row.confirmed)} apply={mapping => void remap(active.source, tableIndex, mapping)} />)}
          </details>
        </div>
      </section> : <p>{t('catalogUx.pickRow')}</p>}
      {reviews.filter(item => !item.rows.length || item.preview.quality?.state === 'NEEDS_REVIEW').map(item => <div key={item.preview.source.visual_page_id} role="alert">
        <b>{item.preview.source.filename} · {t('guided.physicalPage', { number: item.preview.source.page_number })}</b><p>{t('guided.coverageIncomplete')}</p>
        {item.preview.tables.some(table => table.schema.state !== 'RESOLVED') && <details><summary>{t('guided.mapping')}</summary>{item.preview.tables.map((_, index) => <Mapping key={index} preview={item.preview} tableIndex={index} busy={busy || unsaved} apply={mapping => void remap(reviews.indexOf(item), index, mapping)} />)}</details>}
        <button className="secondary" disabled={busy || unsaved} onClick={() => void retrySource(sources.find(source => source.id === item.preview.source.visual_page_id)!)}>{t('wizard.retry')}</button>
      </div>)}
      <div className="actions"><button className="primary" disabled={busy || unsaved || !allRows.some(entry => entry.row.selected && canSelect(entry))} onClick={() => void confirm()}>{t('guided.confirm')}</button></div>
      <DurableSourceReview session={session} targetSourceId={targetSourceId} reload={async () => { await load(); await changed() }} parts={accepted} busy={busy || unsaved} onDirtyChange={setSourceReviewDirty} />
      {onContinue && !!session?.sources.length && session.sources.every(source => source.review_state === 'VERIFIED') && <button className="primary" disabled={busy || unsaved} onClick={onContinue}>{t('catalogUx.step.hotspots')}</button>}
    </>}
    {tools && <Modal wide title={t('catalogUx.partTools')} onClose={() => { if (!advancedDirty || window.confirm(t('wizard.unsaved'))) setTools(false) }}>
      <RevisionParts initialPartId={editPartId} assemblyId={page.assembly_id} referencePageId={page.id} editable onChanged={async () => { await load(); await changed() }} onDirtyChange={setAdvancedDirty} />
    </Modal>}
  </section>
}
