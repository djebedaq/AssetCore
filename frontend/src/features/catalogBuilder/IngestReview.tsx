import { useEffect, useState } from 'react'
import { api, ApiError } from '../../api'
import { useI18n } from '../../i18n'
import { ingestBg } from './ingestTranslations'
import CandidateSource from './CandidateSource'
import type { Analysis, Candidate, CandidatePage, Kind } from './ingestTypes'
import { builderBase, problemKeys, type Group } from './wizardTypes'
import useDraftGuard from './useDraftGuard'

export default function IngestReview({ revisionId, kind, groups = [], refreshKey = 0, onChanged, onDirtyChange, blocked = false }: {
  revisionId: number; kind: Kind; groups?: Group[]; refreshKey?: number; onChanged: () => Promise<void>;
  onDirtyChange?: (dirty: boolean) => void; blocked?: boolean
}) {
  const { t, locale } = useI18n()
  const tx = (key: string) => t(key in ingestBg ? key as keyof typeof ingestBg : 'builder.error.generic')
  const [runs, setRuns] = useState<Analysis[]>([])
  const [runId, setRunId] = useState<number | null>(null)
  const [rows, setRows] = useState<Candidate[]>([])
  const [groupRows, setGroupRows] = useState<Candidate[]>([])
  const [next, setNext] = useState<number | null>(null)
  const [total, setTotal] = useState(0)
  const [filter, setFilter] = useState('all')
  const [search, setSearch] = useState('')
  const [after, setAfter] = useState(0)
  const [selected, setSelected] = useState<number[]>([])
  const [source, setSource] = useState<Candidate | null>(null)
  const [locationIndex, setLocationIndex] = useState(0)
  const [chosenLocations, setChosenLocations] = useState<number[]>([])
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [editing, setEditing] = useState<Candidate | null>(null)
  const [edit, setEdit] = useState<Record<string, string>>({})
  const [reload, setReload] = useState(0)
  useDraftGuard(!!editing || busy, onDirtyChange)
  const activeRun = runs.find(run => run.id === runId) || runs[0]
  const report = (caught: unknown) => {
    const code = caught instanceof ApiError ? caught.code || '' : ''
    const key = `ingest.error.${code}`
    setError(key in ingestBg ? tx(key) : t(problemKeys[code] || 'builder.error.generic'))
  }
  useEffect(() => {
    let active = true
    void api<Analysis[]>(`${builderBase}/revisions/${revisionId}/analyses`).then(items => {
      if (active) setRuns(items.filter(item => item.status === 'COMPLETED'))
    }).catch(report)
    return () => { active = false }
  }, [revisionId, refreshKey, reload])
  useEffect(() => {
    let active = true
    setRows([]); setSelected([])
    if (!activeRun) return
    const params = new URLSearchParams({ kind, after: String(after), search })
    if (filter === 'high') params.set('high_confidence', 'true')
    else if (filter === 'errors') params.set('errors', 'true')
    else if (['EXACT', 'MULTIPLE_CANDIDATES', 'NOT_FOUND', 'LOW_CONFIDENCE'].includes(filter)) params.set('match', filter)
    else if (['verified', 'unverified'].includes(filter)) params.set('verified', String(filter === 'verified'))
    else if (filter !== 'all') params.set('state', filter)
    void api<CandidatePage>(`${builderBase}/analyses/${activeRun.id}/candidates?${params}`).then(result => {
      if (active) { setRows(result.items); setNext(result.next_after); setTotal(result.total) }
    }).catch(report)
    // Group options are paged too; source names remain untranslated.
    async function loadGroups() {
      const result: Candidate[] = []
      let cursor = 0
      do {
        const page = await api<CandidatePage>(`${builderBase}/analyses/${activeRun!.id}/candidates?kind=GROUP&limit=100&after=${cursor}`)
        result.push(...page.items); cursor = page.next_after || 0
      } while (cursor && active)
      if (active) setGroupRows(result)
    }
    void loadGroups().catch(report)
    return () => { active = false }
  }, [activeRun?.id, kind, filter, search, after, reload, refreshKey])
  async function perform(action: () => Promise<unknown>) {
    if (busy) return
    if (blocked) { setError(t('ingest.finishDraft')); return }
    setBusy(true); setError('')
    try { await action(); setEditing(null); setSelected([]); setReload(value => value + 1); await onChanged() }
    catch (caught) { report(caught) }
    finally { setBusy(false) }
  }
  const review = (row: Candidate, action: string, extra = {}) => api(`${builderBase}/analyses/${activeRun!.id}/candidates/${row.id}/review`, {
    method: 'POST', body: JSON.stringify({ expected_version: row.version, action, ...extra }),
  })
  async function bulk(action: string, high = false) {
    if (!activeRun) return
    await perform(async () => {
      if (!high) {
        await api(`${builderBase}/analyses/${activeRun.id}/bulk-review`, { method: 'POST', body: JSON.stringify({
          action, items: rows.filter(row => selected.includes(row.id) && eligible(row, action)).map(row => ({ id: row.id, expected_version: row.version })),
        }) })
      } else {
        // Query again after every commit: each batch is atomic and optimistic.
        while (true) {
          const page = await api<CandidatePage>(`${builderBase}/analyses/${activeRun.id}/candidates?kind=${kind}&high_confidence=true&limit=100`)
          if (!page.items.length) break
          await api(`${builderBase}/analyses/${activeRun.id}/bulk-review`, { method: 'POST', body: JSON.stringify({
            action, items: page.items.map(row => ({ id: row.id, expected_version: row.version })),
          }) })
        }
      }
    })
  }
  function eligible(row: Candidate, action: string) {
    return action === 'VERIFY' ? row.state === 'ACCEPTED' && !row.payload.verified
      : row.state === 'PROPOSED' || row.state === 'NEEDS_REVIEW'
  }
  const hasEligible = (action: string) => rows.some(row => selected.includes(row.id) && eligible(row, action))
  function beginEdit(row: Candidate) {
    if (editing && !window.confirm(t('wizard.unsaved'))) return
    setEditing(row)
    setEdit(Object.fromEntries(['name', 'group_key', 'role', 'merge_into_key', 'assembly_id', 'position', 'part_number', 'description', 'quantity', 'quantity_raw']
      .map(key => [key, String(row.payload[key as keyof Candidate['payload']] ?? '')])))
  }
  async function saveEdit() {
    if (!editing) return
    const changes = kind === 'GROUP' ? { name: edit.name, merge_into_key: edit.merge_into_key || null,
      assembly_id: edit.assembly_id ? Number(edit.assembly_id) : null }
      : kind === 'PAGE' ? { role: edit.role, ...(edit.group_key ? { group_key: edit.group_key } : {}) }
        : { group_key: edit.group_key, part: { position: edit.position, part_number: edit.part_number,
          description: edit.description || null, quantity: edit.quantity || null, quantity_raw: edit.quantity_raw || null } }
    await perform(() => review(editing, 'EDIT', { edit: changes }))
  }
  if (!activeRun) return <p>{t('ingest.noAnalysis')}</p>
  return <section className="ingest-review" aria-label={t(`ingest.kind.${kind}`)}>
    <h4>{t(`ingest.kind.${kind}`)} · {total}</h4>
    <p>{t('ingest.reviewHelp')}</p>
    {error && <p className="error" role="alert">{error}</p>}
    {runs.length > 1 && <label>{t('wizard.documents')}<select value={activeRun.id} onChange={event => { setRunId(Number(event.target.value)); setAfter(0) }}>
      {runs.map(run => <option key={run.id} value={run.id}>{t('ingest.document', { count: run.page_count })}</option>)}
    </select></label>}
    <div className="actions">
      {kind === 'HOTSPOT' && <button className="secondary" disabled={busy} onClick={() => void perform(() => api(`${builderBase}/analyses/${activeRun.id}/match-hotspots`, { method: 'POST' }))}>{t('ingest.rematch')}</button>}
      <label>{t('ingest.filter')}<select value={filter} onChange={event => { setFilter(event.target.value); setAfter(0) }}>
        {['all', 'high', ...(kind === 'PART' ? ['errors'] : []), 'NEEDS_REVIEW', 'PROPOSED', 'ACCEPTED', 'REJECTED', ...(kind === 'HOTSPOT' ? ['EXACT', 'MULTIPLE_CANDIDATES', 'NOT_FOUND', 'LOW_CONFIDENCE', 'unverified', 'verified'] : [])].map(value =>
          <option value={value} key={value}>{tx(`ingest.filter.${value}`)}</option>)}
      </select></label>
      <label>{t('ingest.search')}<input value={search} onChange={event => { setSearch(event.target.value); setAfter(0) }} /></label>
      <button className="primary" disabled={busy} onClick={() => void bulk('ACCEPT', true)}>{t('ingest.acceptHigh')}</button>
      <button className="secondary" disabled={busy || !hasEligible('ACCEPT')} onClick={() => void bulk('ACCEPT')}>{t('ingest.acceptSelected')}</button>
      <button className="secondary" disabled={busy || !hasEligible('REJECT')} onClick={() => void bulk('REJECT')}>{t('ingest.rejectSelected')}</button>
      {kind === 'HOTSPOT' && <button className="secondary" disabled={busy || !hasEligible('VERIFY')} onClick={() => void bulk('VERIFY')}>{t('ingest.verifySelected')}</button>}
    </div>
    <div className="ingest-review-layout"><div className="builder-parts-table"><table><thead><tr>
      <th><input type="checkbox" aria-label={t('ingest.selectAll')} checked={!!rows.length && selected.length === rows.length}
        onChange={event => setSelected(event.target.checked ? rows.map(row => row.id) : [])} /></th>
      <th>{t('ingest.value')}</th><th>{t('ingest.state')}</th><th>{t('ingest.source')}</th><th>{t('ingest.actions')}</th>
    </tr></thead><tbody>{rows.map(row => <tr key={row.id}>
      <td><input type="checkbox" aria-label={t('ingest.select', { value: row.payload.position || row.payload.name || row.page_number || '' })}
        checked={selected.includes(row.id)} onChange={event => setSelected(values => event.target.checked ? [...values, row.id] : values.filter(id => id !== row.id))} /></td>
      <td>{kind === 'GROUP' ? row.payload.name : kind === 'PAGE' ? tx(`ingest.role.${row.payload.role}`) : <>
        <b>{row.payload.position}</b> {row.payload.part_number} {row.payload.description} {row.payload.quantity}
      </>}<small>{groupRows.find(group => group.source_key === row.payload.group_key)?.payload.name}</small>
      {row.payload.match && <p>{tx(`ingest.filter.${row.payload.match}`)}</p>}</td>
      <td>{t(`ingest.filter.${row.state}`)} · {Math.round(row.confidence * 100)}%
        {row.warnings.map(warning => <p key={warning}>⚠ {tx(`ingest.warning.${warning}`)}</p>)}
        {row.payload.verified && <p>{t('ingest.filter.verified')}</p>}</td>
      <td><button className="secondary" onClick={() => { setSource(row); setLocationIndex(0); setChosenLocations([0]) }}>{t('ingest.source')}</button></td>
      <td><div className="actions">
        {row.state !== 'ACCEPTED' && <>
          {row.state !== 'REJECTED' && <button className="primary" disabled={busy || row.payload.match === 'NOT_FOUND' || row.payload.match === 'MULTIPLE_CANDIDATES' || row.payload.match === 'LOW_CONFIDENCE'} onClick={() => void perform(() => review(row, 'ACCEPT'))}>{t('ingest.accept')}</button>}
          {kind !== 'HOTSPOT' && <button className="secondary" disabled={busy} onClick={() => beginEdit(row)}>{t('ingest.edit')}</button>}
          <button className="secondary" disabled={busy} onClick={() => void perform(() => review(row, row.state === 'REJECTED' ? 'RESTORE' : 'REJECT'))}>{t(row.state === 'REJECTED' ? 'ingest.restore' : 'ingest.reject')}</button>
        </>}
        {kind === 'HOTSPOT' && row.state === 'ACCEPTED' && !row.payload.verified && <button className="primary" disabled={busy} onClick={() => void perform(() => review(row, 'VERIFY'))}>{t('ingest.verify')}</button>}
      </div></td>
    </tr>)}</tbody></table>
    <div className="actions"><button className="secondary" disabled={!after || busy} onClick={() => setAfter(0)}>{t('wizard.back')}</button>
      <button className="secondary" disabled={next === null || busy} onClick={() => setAfter(next!)}>{t('wizard.continue')}</button></div>
    </div>
    {source && <div><CandidateSource candidate={source} location={source.payload.locations?.[locationIndex]} onClose={() => setSource(null)} />
      {!!source.payload.locations?.length && <>
        <label>{t('ingest.location')}<select value={locationIndex} onChange={event => setLocationIndex(Number(event.target.value))}>
          {source.payload.locations.map((location, index) => <option key={index} value={index}>{index + 1} · {t('wizard.physicalPage', { number: location.page_number })}</option>)}
        </select></label>
        <label><input type="checkbox" checked={chosenLocations.includes(locationIndex)} onChange={event => setChosenLocations(values => event.target.checked ? [...values, locationIndex] : values.filter(index => index !== locationIndex))} />{t('ingest.includeLocation')}</label>
        {source.state !== 'ACCEPTED' && source.state !== 'REJECTED' && <button className="primary" disabled={busy || !chosenLocations.length} onClick={() => void perform(async () => { await review(source, 'ACCEPT', { locations: chosenLocations }); setSource(null) })}>{t('ingest.chooseLocation')}</button>}
      </>}
    </div>}
    </div>
    {editing && <form className="form-grid" onSubmit={event => { event.preventDefault(); void saveEdit() }}>
      {kind === 'GROUP' ? <>
        <label>{t('wizard.groupName')}<input required value={edit.name} maxLength={255} onChange={event => setEdit({ ...edit, name: event.target.value })} /></label>
        <label>{t('ingest.merge')}<select value={edit.merge_into_key || ''} onChange={event => setEdit({ ...edit, merge_into_key: event.target.value })}>
          <option value="">{t('common.noValue')}</option>{groupRows.filter(group => group.id !== editing.id && group.state === 'ACCEPTED').map(group => <option key={group.id} value={group.source_key}>{group.payload.name}</option>)}
        </select></label>
        <label>{t('ingest.existingGroup')}<select value={edit.assembly_id || ''} onChange={event => setEdit({ ...edit, assembly_id: event.target.value })}>
          <option value="">{t('common.noValue')}</option>{groups.map(group => <option key={group.id} value={group.id}>{group[`name_${locale}`] || group.name_bg}</option>)}
        </select></label>
      </> : <>
        <label>{t('wizard.group')}<select required={kind !== 'PAGE' || edit.role !== 'OTHER'} value={edit.group_key} onChange={event => setEdit({ ...edit, group_key: event.target.value })}>
          <option value="">{t('common.noValue')}</option>{groupRows.filter(group => group.state !== 'REJECTED').map(group => <option key={group.id} value={group.source_key}>{group.payload.name}</option>)}
        </select></label>
        {kind === 'PAGE' ? <label>{t('wizard.classification')}<select value={edit.role} onChange={event => setEdit({ ...edit, role: event.target.value })}>
          {['EXPLODED_SCHEME', 'SPARE_PARTS_LIST', 'BOTH', 'OTHER', 'AMBIGUOUS'].map(role => <option key={role} value={role}>{tx(`ingest.role.${role}`)}</option>)}
        </select></label> : ['position', 'part_number', 'description', 'quantity', 'quantity_raw'].map(field => <label key={field}>{tx(`ingest.field.${field}`)}
          <input value={edit[field]} required={field !== 'quantity' && field !== 'quantity_raw'} maxLength={field === 'description' ? 4000 : 120} onChange={event => setEdit({ ...edit, [field]: event.target.value })} />
        </label>)}
      </>}
      <button className="primary" disabled={busy}>{t('common.save')}</button>
      <button type="button" className="secondary" disabled={busy} onClick={() => setEditing(null)}>{t('common.cancel')}</button>
    </form>}
  </section>
}
