import { useEffect, useState } from 'react'
import { api, ApiError, uploadApiFile } from '../../api'
import { useI18n } from '../../i18n'
import { guidedError } from './guidedErrors'
import SourcePageViewer from './SourcePageViewer'
import { builderBase, type Document } from './wizardTypes'
import type { ReferencePage, Source } from './guidedTypes'

export default function GuidedSources({ revisionId, page, changed, onDirtyChange, contextLabel }: {
  revisionId: number; page: ReferencePage; changed: () => Promise<void>; onDirtyChange: (dirty: boolean) => void; contextLabel?: string
}) {
  const { t } = useI18n()
  const [documents, setDocuments] = useState<Document[]>([])
  const [documentId, setDocumentId] = useState<number | ''>('')
  const [start, setStart] = useState(1)
  const [intent, setIntent] = useState<Source['role'] | null>(null)
  const [percent, setPercent] = useState<number | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const document = documents.find(item => item.id === documentId)
  // The server creates per-reference aliases for a shared PDF. Match the
  // canonical document by its content identity, not its reference-local ID.
  const matchesDocument = (source: Source) => source.artifact_id === documentId ||
    !!source.sha256 && source.sha256 === document?.sha256
  async function load() {
    const rows = await api<Document[]>(`${builderBase}/revisions/${revisionId}/documents`)
    setDocuments(rows); setDocumentId(id => rows.some(item => item.id === id) ? id : rows[0]?.id || '')
  }
  useEffect(() => { void load().catch(() => setError(t('guided.error'))) }, [revisionId])
  useEffect(() => { onDirtyChange(busy); return () => onDirtyChange(false) }, [busy, onDirtyChange])
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
      await load(); setDocumentId(source.id); setStart(1)
    } catch (caught) { report(caught) } finally { setBusy(false); setPercent(null) }
  }
  async function assign(role: Source['role']) {
    if (!document || busy || hasRole(role)) return
    setBusy(true); setError('')
    try {
      await api(`${builderBase}/reference-pages/${page.id}/sources`, { method: 'POST', body: JSON.stringify({
        expected_version: page.version, artifact_id: document.id, page_numbers: [start], roles: [role],
      }) })
      await changed()
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
  const roleName = (role: Source['role']) => t(role === 'EXPLODED_SCHEME' ? 'guided.scheme' : 'guided.lists')
  const hasRole = (role: Source['role']) => page.sources.some(source => matchesDocument(source) && source.page_number === start && source.role === role)
  function open(role: Source['role']) { setIntent(role); setError('') }
  const summary = <div className="source-summary">{(['EXPLODED_SCHEME', 'SPARE_PARTS_LIST'] as const).map(role => <section key={role}>
    <div className="source-heading"><h4>{roleName(role)}</h4><button className={(!page.scheme_count && role === 'EXPLODED_SCHEME' || !!page.scheme_count && !page.spare_list_count && role === 'SPARE_PARTS_LIST') ? 'primary' : 'secondary'} disabled={busy} onClick={() => open(role)}>{t(role === 'EXPLODED_SCHEME' ? 'workspace.addScheme' : 'workspace.addList')}</button></div>
    <div className="source-chips">{page.sources.filter(source => source.role === role).map(source => <div key={source.id} className="source-chip">
      <button className="secondary" title={source.filename} disabled={busy} onClick={() => { setDocumentId(documents.find(item => item.sha256 && item.sha256 === source.sha256)?.id ?? source.artifact_id); setStart(source.page_number); open(role) }}>{t('guided.physicalPage', { number: source.page_number })}</button>
      <button className="secondary" aria-label={t('workspace.removeSource', { number: source.page_number, role: roleName(role) })} disabled={busy}
        onClick={() => { if (window.confirm(t('workspace.removeSourceConfirm'))) void remove(source.id) }}>×</button>
      <button className="secondary source-order" disabled={busy || page.sources[0]?.id === source.id} onClick={() => void move(source.id, -1)} aria-label={t('guided.moveUp')}>↑</button>
    </div>)}</div>
  </section>)}</div>
  return <section className={`guided-sources ${intent ? 'viewer-open' : ''}`} onKeyDown={event => { if (event.key === 'Escape' && !busy) setIntent(null) }}>
    {error && <p role="alert" className="error">{error}</p>}
    {summary}
    {intent && <section className="source-selection" aria-label={t('workspace.sourceSelection')}>
      <div className="source-heading"><strong>{contextLabel} · {roleName(intent)}</strong><button className="secondary" disabled={busy} onClick={() => setIntent(null)}>{t('common.close')}</button></div>
      <div className="reader-document-tools">
        <label>{t('guided.chooseSource')}<select disabled={busy} value={documentId} onChange={event => { setDocumentId(Number(event.target.value)); setStart(1) }}>
          <option value="">{t('guided.select')}</option>{documents.map(item => <option key={item.id} value={item.id}>{item.filename}</option>)}
        </select></label>
        <label>{t('guided.upload')}<input type="file" accept="application/pdf,.pdf" disabled={busy} onChange={event => {
          const file = event.target.files?.[0]; if (file) void upload(file); event.target.value = ''
        }} /></label>
      </div>
      {percent !== null && <p role="status">{t(percent >= 100 ? 'guided.validating' : 'guided.uploading', { percent })}</p>}
      {document && <>
        <SourcePageViewer artifactId={document.id} pageCount={document.page_count} number={start} onPage={setStart} />
        <div className="reader-assignment">
          <span role="status">{hasRole(intent) ? t('workspace.assigned', { number: start, role: roleName(intent) }) : t('guided.physicalPage', { number: start })}</span>
          <button className="primary" disabled={busy || hasRole(intent)} onClick={() => void assign(intent)}>{t(intent === 'EXPLODED_SCHEME' ? 'workspace.assignScheme' : 'workspace.assignList')}</button>
          {hasRole(intent) && !hasRole(intent === 'EXPLODED_SCHEME' ? 'SPARE_PARTS_LIST' : 'EXPLODED_SCHEME') && <button className="secondary" disabled={busy}
            onClick={() => void assign(intent === 'EXPLODED_SCHEME' ? 'SPARE_PARTS_LIST' : 'EXPLODED_SCHEME')}>{t(intent === 'EXPLODED_SCHEME' ? 'workspace.alsoList' : 'workspace.alsoScheme')}</button>}
        </div>
      </>}
    </section>}
  </section>
}
