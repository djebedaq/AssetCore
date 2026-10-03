import { useEffect, useState } from 'react'
import { api } from '../../api'
import { useI18n } from '../../i18n'
import { guidedError } from './guidedErrors'
import usePagePreview from './usePagePreview'
import RevisionParts from './RevisionParts'
import { builderBase } from './wizardTypes'
import type { PartValues, Preview, ReferencePage } from './guidedTypes'

type ReviewRow = { part: PartValues; selected: boolean; rejected: boolean; confirmed: boolean }
type Review = { preview: Preview; rows: ReviewRow[] }
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

export default function GuidedParts({ page, changed, onDirtyChange }: { page: ReferencePage;
  changed: () => Promise<void>; onDirtyChange: (dirty: boolean) => void }) {
  const { t } = useI18n()
  const [reviews, setReviews] = useState<Review[]>([])
  const [accepted, setAccepted] = useState<Array<PartValues & { id: number }>>([])
  const [busy, setBusy] = useState(false)
  const [progress, setProgress] = useState<{ current: number; total: number } | null>(null)
  const [filter, setFilter] = useState<'all' | 'attention' | 'errors' | 'rejected' | 'clean' | 'accepted'>('all')
  const [search, setSearch] = useState('')
  const [sourceIndex, setSourceIndex] = useState<number | null>(null)
  const [error, setError] = useState('')
  const [advancedDirty, setAdvancedDirty] = useState(false)
  function review(preview: Preview): Review {
    return { preview, rows: preview.rows.map(row => ({ part: { ...row.payload }, selected: !row.warnings.length, rejected: false, confirmed: false })) }
  }
  async function load() { setAccepted(await api(`${builderBase}/reference-pages/${page.id}/parts`)) }
  useEffect(() => { void load().catch(() => setError(t('guided.error'))) }, [page.id])
  useEffect(() => { onDirtyChange(busy || reviews.length > 0 || advancedDirty); return () => onDirtyChange(false) }, [busy, reviews.length, advancedDirty, onDirtyChange])
  async function extract() {
    const sources = page.sources.filter(source => source.role === 'SPARE_PARTS_LIST')
    if (busy || !sources.length) return
    setBusy(true); setError(''); setReviews([])
    let previous: string | null = null
    try {
      for (const [index, source] of sources.entries()) {
        setProgress({ current: index + 1, total: sources.length })
        const result: Preview = await api<Preview>(`${builderBase}/reference-pages/${page.id}/extract`, { method: 'POST', body: JSON.stringify({
          visual_page_id: source.id, continuation_token: previous,
        }) })
        previous = result.token
        setReviews(current => [...current, review(result)])
      }
    } catch (caught) { setError(t(guidedError(caught))) } finally { setBusy(false); setProgress(null) }
  }
  function edit(source: number, index: number, values: Partial<ReviewRow>) {
    setReviews(current => current.map((item, sourceIndex) => sourceIndex !== source ? item : {
      ...item, rows: item.rows.map((row, rowIndex) => rowIndex !== index ? row : { ...row, ...values }),
    }))
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
      for (const [source, item] of reviews.entries()) {
        const rows = item.rows.flatMap((row, index) => row.selected && !row.rejected && !row.confirmed ? [{ index, part: row.part }] : [])
        if (!rows.length) continue
        await api(`${builderBase}/reference-pages/${page.id}/extraction/confirm`, { method: 'POST', body: JSON.stringify({
          token: item.preview.token, rows, confirm_warnings: true,
        }) })
        setReviews(current => current.map((value, index) => index !== source ? value : {
          ...value, rows: value.rows.map(row => row.selected && !row.rejected ? { ...row, selected: false, confirmed: true } : row),
        }))
      }
      await load(); await changed()
    } catch (caught) { setError(t(guidedError(caught))) } finally { setBusy(false) }
  }
  return <section className="guided-parts">
    {error && <p role="alert" className="error">{error}</p>}
    {!page.spare_list_count && <p role="status">{t('guided.noLists')}</p>}
    <details><summary>{t('guided.advanced')}</summary><RevisionParts assemblyId={page.assembly_id} referencePageId={page.id} editable onChanged={async () => { await load(); await changed() }} onDirtyChange={setAdvancedDirty} /></details>
    <button className="primary" disabled={busy || !!reviews.length || !page.spare_list_count} onClick={() => void extract()}>{t('guided.extract')}</button>
    {progress && <p role="status">{t('guided.extracting', progress)}</p>}
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
        {item.preview.warnings.includes('OCR_UNAVAILABLE') && <p role="alert">{t('guided.OCR_UNAVAILABLE')}</p>}
        {!item.rows.length && <p role="status">{t('guided.noRows')}</p>}
        {item.preview.tables.map((table, tableIndex) => table.schema.state !== 'RESOLVED' ? <Mapping
          key={`${item.preview.token.slice(-12)}-${tableIndex}`} preview={item.preview} tableIndex={tableIndex} busy={busy} apply={mapping => void remap(source, tableIndex, mapping)} /> : <details key={`${item.preview.token.slice(-12)}-${tableIndex}`}><summary>{t('guided.mapping')}</summary><Mapping
          preview={item.preview} tableIndex={tableIndex} busy={busy || item.rows.some(row => row.confirmed)} apply={mapping => void remap(source, tableIndex, mapping)} /></details>)}
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
                value={row.part[field] ?? ''} onChange={event => edit(source, index, { part: { ...row.part, [field]: event.target.value || null } })} /></td>)}
              <td><details><summary>{t('guided.advanced')}</summary>{fields.slice(4).map(field => <label key={field}>{t(`guided.${field}`)}<input aria-label={t(`guided.${field}`) + ' ' + (index + 1)} value={row.part[field] ?? ''} disabled={busy || row.confirmed || row.rejected} onChange={event => edit(source, index, { part: { ...row.part, [field]: event.target.value || null } })} /></label>)}</details><span>{t(row.confirmed ? 'guided.accepted' : warnings.length ? 'guided.attention' : 'guided.clean')}</span>
                <button className="secondary" disabled={busy || row.confirmed} onClick={() => edit(source, index, { rejected: !row.rejected, selected: false })}>{t(row.rejected ? 'guided.restore' : 'guided.reject')}</button></td></tr>
          })}</tbody></table></div>
      </section>)}
      <div className="actions"><button className="primary" disabled={busy || !reviews.some(item => item.rows.some(row => row.selected && !row.rejected))} onClick={() => void confirm()}>{t('guided.confirm')}</button>
        <button className="secondary" disabled={busy} onClick={() => { setReviews([]); setSourceIndex(null) }}>{t('common.close')}</button></div>
    </>}
  </section>
}
