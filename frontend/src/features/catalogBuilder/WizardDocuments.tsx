import { useEffect, useState } from 'react'
import { api, ApiError } from '../../api'
import { filePayload } from '../../industrialUi'
import { useI18n } from '../../i18n'
import DocumentThumbnail from './DocumentThumbnail'
import useDraftGuard from './useDraftGuard'
import { builderBase, problemKeys, type Document, type Group, type Role } from './wizardTypes'

type Choice = 'scheme' | 'list' | 'both' | 'ignore'
const roles: Record<Choice, Role[]> = { scheme: ['EXPLODED_SCHEME'], list: ['SPARE_PARTS_LIST'],
  both: ['EXPLODED_SCHEME', 'SPARE_PARTS_LIST'], ignore: [] }

export function parsePageRange(value: string, pageCount: number): number[] {
  const selected = new Set<number>()
  for (const token of value.split(',')) {
    const match = token.trim().match(/^(\d+)(?:\s*-\s*(\d+))?$/)
    if (!match) throw Error('invalid_range')
    const first = Number(match[1]); const last = Number(match[2] || match[1])
    if (first < 1 || last < first || last > pageCount || last - first > 499) throw Error('invalid_range')
    for (let number = first; number <= last; number++) selected.add(number)
    if (selected.size > 500) throw Error('invalid_range')
  }
  return [...selected]
}

export default function WizardDocuments({ revisionId, groups, onChanged, onDirtyChange, targetPage, targetArtifactId }: {
  revisionId: number; groups: Group[]; onChanged: () => Promise<void>; onDirtyChange: (dirty: boolean) => void
  targetPage?: number
  targetArtifactId?: number
}) {
  const { locale, t } = useI18n()
  const [documents, setDocuments] = useState<Document[]>([])
  const [documentId, setDocumentId] = useState<number | null>(null)
  const [groupId, setGroupId] = useState<number | null>(null)
  const [name, setName] = useState('')
  const [file, setFile] = useState<File | null>(null)
  const [selected, setSelected] = useState<number[]>([])
  const [range, setRange] = useState('')
  const [choice, setChoice] = useState<Choice>('scheme')
  const [offset, setOffset] = useState(0)
  const [suggestions, setSuggestions] = useState<{ pages: Array<{ page_number: number; suggested_role: Role | null }>; group_names: string[] } | null>(null)
  const [selectedSuggestions, setSelectedSuggestions] = useState<number[]>([])
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const source = documents.find(item => item.id === documentId) || documents[0]
  const targetId = groupId && groups.some(group => group.id === groupId) ? groupId : groups[0]?.id
  const label = (group: Group) => group[`name_${locale}`] || group.name_bg
  useDraftGuard(!!name.trim() || !!file || busy, onDirtyChange)
  async function load() { setDocuments(await api<Document[]>(`${builderBase}/revisions/${revisionId}/documents`)) }
  useEffect(() => { void load().catch(report) }, [revisionId])
  useEffect(() => { if (targetPage && source && targetPage <= source.page_count) {
    setOffset(Math.floor((targetPage - 1) / 24) * 24); setSelected([targetPage])
  } }, [targetPage, source?.id])
  useEffect(() => {
    if (!targetArtifactId) return
    const document = documents.find(item => item.id === targetArtifactId || item.artifact_ids?.includes(targetArtifactId))
    if (document) { setDocumentId(document.id); setOffset(0) }
  }, [targetArtifactId, documents])
  function report(caught: unknown) { setError(t(caught instanceof ApiError && caught.code ? problemKeys[caught.code] || 'builder.error.generic' : 'builder.error.generic')) }
  async function run(action: () => Promise<void>) {
    if (busy) return
    setBusy(true); setError('')
    try { await action(); await onChanged() } catch (caught) { report(caught) } finally { setBusy(false) }
  }
  async function addGroup(groupName: string, suggestionIndex?: number) {
    await run(async () => {
      const group = await api<Group>(`${builderBase}/revisions/${revisionId}/groups`, { method: 'POST', body: JSON.stringify({ name: groupName }) })
      setGroupId(group.id); setName('')
      if (suggestionIndex !== undefined) { setSelectedSuggestions([]); setSuggestions(current => current ? { ...current, group_names: current.group_names.filter((_, index) => index !== suggestionIndex) } : null) }
    })
  }
  async function classify(numbers: number[], nextChoice: Choice, assemblyId = targetId) {
    if (!source || !assemblyId) return
    await run(async () => {
      setDocuments(await api<Document[]>(`${builderBase}/artifacts/${source.id}/classify`, {
        method: 'POST', body: JSON.stringify({ assembly_id: assemblyId, page_numbers: numbers, roles: roles[nextChoice] }),
      }))
      setSelected([])
    })
  }
  function pageChoice(number: number): Choice {
    const assignments = source?.assignments.filter(item => item.page_number === number) || []
    const scheme = assignments.some(item => item.role === 'EXPLODED_SCHEME')
    const list = assignments.some(item => item.role === 'SPARE_PARTS_LIST')
    return scheme && list ? 'both' : scheme ? 'scheme' : list ? 'list' : 'ignore'
  }
  const groupSelect = (id: number | undefined, change: (id: number) => void) => <select value={id || ''} disabled={busy || !groups.length} onChange={event => change(Number(event.target.value))}>
    {!groups.length && <option value="">{t('wizard.noGroups')}</option>}
    {groups.map(group => <option key={group.id} value={group.id}>{label(group)}</option>)}
  </select>
  return <div className="builder-workspace">
    <p>{t('wizard.documentHelp')}</p>
    {error && <p className="error" role="alert">{error}</p>}
    <form className="actions" onSubmit={event => { event.preventDefault(); void addGroup(name) }}>
      <label>{t('wizard.groupName')}<input value={name} maxLength={255} required onChange={event => setName(event.target.value)} /></label>
      <button className="secondary" disabled={busy || !name.trim()}>{t('wizard.addGroup')}</button>
    </form>
    {!groups.length && <p>{t('wizard.noGroups')}</p>}
    <div className="wizard-groups">{groups.map(group => <article key={group.id}>
      <strong>{label(group)}</strong>
    </article>)}</div>
    <div className="wizard-upload">
      <label>{t('wizard.uploadGroup')}{groupSelect(targetId, setGroupId)}</label>
      <label>{t('wizard.upload')}<input type="file" accept=".pdf,application/pdf" disabled={busy} onChange={event => setFile(event.target.files?.[0] || null)} /></label>
      <button className="primary" disabled={busy || !file || !targetId} onClick={() => void run(async () => {
        const payload = await filePayload(file!)
        const created = await api<Document>(`${builderBase}/assemblies/${targetId}/artifacts`, {
          method: 'POST', body: JSON.stringify({ ...payload, title: file!.name }),
        })
        setFile(null); await load(); setDocumentId(created.id); setOffset(0)
      })}>{t('wizard.upload')}</button>
    </div>
    {!source && <p>{t('wizard.noDocuments')}</p>}
    {source && <>
      <label>{t('wizard.documents')}<select value={source.id} disabled={busy} onChange={event => {
        setDocumentId(Number(event.target.value)); setSelected([]); setOffset(0); setSuggestions(null)
      }}>{documents.map(document => <option key={document.id} value={document.id}>{document.filename}</option>)}</select></label>
      <p>{t('wizard.pageHelp')}</p>
      <button className="secondary" disabled={busy} onClick={() => void run(async () => setSuggestions(await api(`${builderBase}/artifacts/${source.id}/suggestions`)))}>{t('wizard.suggest')}</button>
      {suggestions && <><p className="muted">{t('wizard.suggestionHelp')}</p>
        {!suggestions.pages.length && !suggestions.group_names.length && <p>{t('wizard.noSuggestions')}</p>}
        {suggestions.group_names.map((heading, index) => <div className="actions" key={index}>
          <input type="checkbox" aria-label={t('wizard.selectSuggestion', { name: heading })} checked={selectedSuggestions.includes(index)}
            onChange={() => setSelectedSuggestions(values => values.includes(index) ? values.filter(value => value !== index) : [...values, index].sort((a, b) => a - b))} />
          <label>{t('wizard.suggestedGroup', { name: heading })}<input value={heading} maxLength={255} onChange={event => setSuggestions({
            ...suggestions, group_names: suggestions.group_names.map((value, i) => i === index ? event.target.value : value),
          })} /></label>
          <button className="secondary" disabled={busy || !heading.trim()} onClick={() => void addGroup(heading, index)}>{t('wizard.addGroup')}</button>
          <button className="secondary" onClick={() => { setSelectedSuggestions([]); setSuggestions({ ...suggestions, group_names: suggestions.group_names.filter((_, i) => i !== index) }) }}>{t('common.remove')}</button>
        </div>)}
        {suggestions.group_names.length > 1 && <button className="secondary" disabled={selectedSuggestions.length < 2} onClick={() => {
          const removed = selectedSuggestions.slice(1)
          setSuggestions({ ...suggestions, group_names: suggestions.group_names.filter((_, index) => !removed.includes(index)) })
          setSelectedSuggestions([])
        }}>{t('wizard.mergeSuggestions')}</button>}
      </>}
      <div className="wizard-page-tools">
        <label>{t('wizard.range')}<input value={range} onChange={event => setRange(event.target.value)} /></label>
        <button className="secondary" disabled={busy || !range} onClick={() => { try { setSelected(parsePageRange(range, source.page_count)); setError('') } catch { setError(t('wizard.invalidRange')) } }}>{t('wizard.selectRange')}</button>
        <label>{t('wizard.classification')}<select value={choice} onChange={event => setChoice(event.target.value as Choice)}>
          {(Object.keys(roles) as Choice[]).map(value => <option key={value} value={value}>{t(`wizard.${value}`)}</option>)}
        </select></label>
        <label>{t('wizard.group')}{groupSelect(targetId, setGroupId)}</label>
        <button className="primary" disabled={busy || !selected.length || !targetId} onClick={() => void classify(selected, choice)}>{t('wizard.apply')}</button>
        <span>{t('wizard.selected', { count: selected.length })}</span>
      </div>
      <div className="builder-page-grid">{Array.from({ length: Math.min(24, source.page_count - offset) }, (_, index) => offset + index + 1).map(number => {
        const assignments = source.assignments.filter(item => item.page_number === number)
        const assignedId = assignments[0]?.assembly_id || targetId
        const hint = suggestions?.pages.find(page => page.page_number === number)?.suggested_role
        return <article className="builder-page-card" key={`${source.id}-${number}`}>
          <label><input type="checkbox" aria-label={t('wizard.selectPage', { number })} checked={selected.includes(number)}
            onChange={() => setSelected(values => values.includes(number) ? values.filter(value => value !== number) : [...values, number])} />
            <b>{t('wizard.physicalPage', { number })}</b></label>
          <DocumentThumbnail artifactId={source.id} pageNumber={number} />
          {hint && <small>{t('wizard.suggestion', { role: t(hint === 'EXPLODED_SCHEME' ? 'wizard.scheme' : 'wizard.list') })}</small>}
          <label>{t('wizard.classification')}<select disabled={busy} value={pageChoice(number)} onChange={event => void classify([number], event.target.value as Choice, assignedId)}>
            {(Object.keys(roles) as Choice[]).map(value => <option key={value} value={value}>{t(`wizard.${value}`)}</option>)}
          </select></label>
          <label>{t('wizard.group')}{groupSelect(assignedId, id => void classify([number], pageChoice(number), id))}</label>
        </article>
      })}</div>
      <div className="actions wizard-pagination">
        <button className="secondary" disabled={offset === 0} onClick={() => setOffset(value => Math.max(0, value - 24))}>{t('wizard.back')}</button>
        <span>{offset + 1}–{Math.min(offset + 24, source.page_count)} / {source.page_count}</span>
        <button className="secondary" disabled={offset + 24 >= source.page_count} onClick={() => setOffset(value => value + 24)}>{t('wizard.continue')}</button>
      </div>
    </>}
  </div>
}
