import { useEffect, useState } from 'react'
import { api, ApiError, uploadApiFile } from '../../api'
import { useI18n } from '../../i18n'
import { guidedError } from './guidedErrors'
import DocumentThumbnail from './DocumentThumbnail'
import { builderBase, type Document } from './wizardTypes'
import type { ReferencePage, Source } from './guidedTypes'

export default function GuidedSources({ revisionId, page, changed, onDirtyChange }: {
  revisionId: number; page: ReferencePage; changed: () => Promise<void>; onDirtyChange: (dirty: boolean) => void
}) {
  const { t } = useI18n()
  const [documents, setDocuments] = useState<Document[]>([])
  const [documentId, setDocumentId] = useState<number | ''>('')
  const [start, setStart] = useState(1)
  const [selected, setSelected] = useState<number[]>([])
  const [roles, setRoles] = useState<Source['role'][]>(['EXPLODED_SCHEME'])
  const [percent, setPercent] = useState<number | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const document = documents.find(item => item.id === documentId)
  async function load() {
    const rows = await api<Document[]>(`${builderBase}/revisions/${revisionId}/documents`)
    setDocuments(rows); setDocumentId(id => rows.some(item => item.id === id) ? id : rows[0]?.id || '')
  }
  useEffect(() => { void load().catch(() => setError(t('guided.error'))) }, [revisionId])
  useEffect(() => { setSelected([]); setStart(1) }, [documentId, page.id])
  useEffect(() => { onDirtyChange(busy || selected.length > 0); return () => onDirtyChange(false) }, [busy, selected.length, onDirtyChange])
  function report(caught: unknown) {
    if (caught instanceof ApiError && caught.data?.configurable_setting) setError(t('guided.limit', {
      limit: Number(caught.data.limit), setting: String(caught.data.configurable_setting),
    }))
    else setError(t(caught instanceof ApiError && caught.code === 'catalog_source_encrypted' ? 'guided.encrypted' : guidedError(caught)))
  }
  async function upload(file: File) {
    setBusy(true); setError(''); setPercent(0)
    try {
      const source = await uploadApiFile<Document>(`${builderBase}/revisions/${revisionId}/pdf`, file, setPercent)
      await load(); setDocumentId(source.id)
    } catch (caught) { report(caught) } finally { setBusy(false); setPercent(null) }
  }
  async function assign() {
    if (!document || !selected.length || !roles.length || busy) return
    setBusy(true); setError('')
    try {
      await api(`${builderBase}/reference-pages/${page.id}/sources`, { method: 'POST', body: JSON.stringify({
        expected_version: page.version, artifact_id: document.id, page_numbers: selected, roles,
      }) })
      setSelected([]); await changed()
    } catch (caught) { report(caught) } finally { setBusy(false) }
  }
  async function remove(sourceId: number) {
    setBusy(true); setError('')
    try {
      await api(`${builderBase}/reference-pages/${page.id}/sources/${sourceId}?expected_version=${page.version}`, { method: 'DELETE' })
      await changed()
    } catch (caught) { report(caught) } finally { setBusy(false) }
  }
  async function move(sourceId: number, direction: number) {
    const ordered = page.sources.map(source => source.id); const index = ordered.indexOf(sourceId)
    const next = index + direction
    if (next < 0 || next >= ordered.length || busy) return
    ;[ordered[index], ordered[next]] = [ordered[next], ordered[index]]
    setBusy(true); setError('')
    try {
      await api(`${builderBase}/reference-pages/${page.id}/sources/reorder`, { method: 'POST', body: JSON.stringify({
        expected_version: page.version, ordered_ids: ordered,
      }) }); await changed()
    } catch (caught) { report(caught) } finally { setBusy(false) }
  }
  return <section className="guided-sources">
    {error && <p role="alert" className="error">{error}</p>}
    {(['EXPLODED_SCHEME', 'SPARE_PARTS_LIST'] as const).map(role => <section key={role}>
      <h4>{t(role === 'EXPLODED_SCHEME' ? 'guided.scheme' : 'guided.lists')}</h4>
      <div className="builder-list">{page.sources.filter(source => source.role === role).map(source => <article key={source.id} className="builder-list-item">
        <span>{source.filename} · {t('guided.physicalPage', { number: source.page_number })}</span>
        <button className="secondary" disabled={busy || page.sources[0]?.id === source.id} onClick={() => void move(source.id, -1)}>{t('guided.moveUp')}</button>
        <button className="secondary" disabled={busy} onClick={() => void remove(source.id)}>{t('guided.delete')}</button>
      </article>)}</div>
    </section>)}
    <h4>{t('guided.addSource')}</h4>
    <label>{t('guided.upload')}<input type="file" accept="application/pdf,.pdf" disabled={busy} onChange={event => {
      const file = event.target.files?.[0]; if (file) void upload(file); event.target.value = ''
    }} /></label>
    {percent !== null && <p role="status">{t(percent >= 100 ? 'guided.validating' : 'guided.uploading', { percent })}</p>}
    <label>{t('guided.chooseSource')}<select disabled={busy} value={documentId} onChange={event => setDocumentId(Number(event.target.value))}>
      <option value="">{t('guided.select')}</option>{documents.map(item => <option key={item.id} value={item.id}>{item.filename}</option>)}
    </select></label>
    {document && <>
      <div className="actions"><label>{t('guided.jump')}<input type="number" min={1} max={document.page_count} value={start}
        onChange={event => setStart(Math.max(1, Math.min(document.page_count, Number(event.target.value) || 1)))} /></label>
        <button className="secondary" disabled={busy || start <= 1} onClick={() => setStart(Math.max(1, start - 8))}>{t('wizard.back')}</button>
        <button className="secondary" disabled={busy || start + 8 > document.page_count} onClick={() => setStart(start + 8)}>{t('wizard.continue')}</button></div>
      <div className="guided-source-grid">{Array.from({ length: Math.min(8, document.page_count - start + 1) }, (_, index) => start + index).map(number =>
        <label key={`${document.id}-${number}`} className="guided-source-choice"><DocumentThumbnail artifactId={document.id} pageNumber={number} />
          <span><input type="checkbox" aria-label={t('guided.physicalPage', { number })} disabled={busy} checked={selected.includes(number)} onChange={event => setSelected(current => event.target.checked ? [...current, number] : current.filter(value => value !== number))} />
            {t('guided.physicalPage', { number })}</span></label>)}</div>
      <div className="actions">{(['EXPLODED_SCHEME', 'SPARE_PARTS_LIST'] as const).map(role => <label key={role}>
        <input type="checkbox" checked={roles.includes(role)} disabled={busy} onChange={event => setRoles(current => event.target.checked ? [...current, role] : current.filter(value => value !== role))} />
        {t(role === 'EXPLODED_SCHEME' ? 'guided.scheme' : 'guided.lists')}</label>)}</div>
      <p role="status">{t('guided.selected', { count: selected.length })}</p>
      <button className="primary" disabled={busy || !selected.length || !roles.length} onClick={() => void assign()}>{t('guided.assign')}</button>
    </>}
  </section>
}
