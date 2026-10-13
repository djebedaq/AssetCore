import { useEffect, useRef, useState } from 'react'
import { api, ApiError, uploadApiFile } from '../../api'
import { useI18n } from '../../i18n'
import { guidedError } from './guidedErrors'
import { useDialogFocus } from './CatalogDialog'
import SourcePageViewer from './SourcePageViewer'
import DraftDeleteButton from './DraftDeleteButton'
import DocumentThumbnail from './DocumentThumbnail'
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
  const selection = useRef<HTMLElement>(null)
  useDialogFocus(selection, !!intent, closeSelection)
  const [selected, setSelected] = useState<Array<{ page_number: number; roles: Source['role'][] }>>([])
  const [percent, setPercent] = useState<number | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const document = documents.find(item => item.id === documentId)
  function closeSelection() {
    if (busy || selected.length > 0 && !window.confirm(t('wizard.unsaved'))) return
    setSelected([]); setIntent(null)
  }
  // The server creates per-reference aliases for a shared PDF. Match the
  // canonical document by its content identity, not its reference-local ID.
  const matchesDocument = (source: Source) => source.artifact_id === documentId ||
    !!source.sha256 && source.sha256 === document?.sha256
  async function load() {
    const rows = await api<Document[]>(`${builderBase}/revisions/${revisionId}/documents`)
    setDocuments(rows); setDocumentId(id => rows.some(item => item.id === id) ? id : rows[0]?.id || '')
  }
  useEffect(() => { void load().catch(() => setError(t('guided.error'))) }, [revisionId])
  useEffect(() => { onDirtyChange(busy || selected.length > 0); return () => onDirtyChange(false) }, [busy, selected.length, onDirtyChange])
  function report(caught: unknown) {
    if (caught instanceof ApiError && caught.data?.configurable_setting) setError(t('catalogUx.limit', {
      limit: Number(caught.data.limit), setting: String(caught.data.configurable_setting),
    }))
    else setError(t(caught instanceof ApiError && caught.code === 'catalog_source_encrypted' ? 'guided.encrypted' : guidedError(caught)))
  }
  async function upload(file: File) {
    setBusy(true); setError(''); setPercent(0)
    try {
      const source = await uploadApiFile<Document>(`${builderBase}/revisions/${revisionId}/pdf`, file, setPercent)
      await load(); setDocumentId(source.id); setStart(1); setSelected([])
    } catch (caught) { report(caught) } finally { setBusy(false); setPercent(null) }
  }
  async function assign() {
    if (!document || busy || !selected.length) return
    setBusy(true); setError('')
    try {
      await api(`${builderBase}/reference-pages/${page.id}/sources`, { method: 'POST', body: JSON.stringify({
        expected_version: page.version, artifact_id: document.id, selections: selected,
      }) })
      setSelected([]); setIntent(null); await changed()
    } catch (caught) { report(caught) } finally { setBusy(false) }
  }
  function toggle(number: number, role: Source['role']) {
    setSelected(current => {
      const row = current.find(item => item.page_number === number)
      if (!row) return [...current, { page_number: number, roles: [role] }]
      const roles = row.roles.includes(role) ? row.roles.filter(value => value !== role) : [...row.roles, role]
      return roles.length ? current.map(item => item === row ? { ...item, roles } : item) : current.filter(item => item !== row)
    })
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
  function open(role: Source['role']) { setIntent(role); setSelected([]); setError('') }
  const summary = <><p role="status">{t('catalogUx.sourceSummary', { schemes: page.scheme_count, lists: page.spare_list_count })}</p><div className="source-summary">{(['EXPLODED_SCHEME', 'SPARE_PARTS_LIST'] as const).map(role => <section key={role}>
    <div className="source-heading"><h4>{roleName(role)}</h4><button className={(!page.scheme_count && role === 'EXPLODED_SCHEME' || !!page.scheme_count && !page.spare_list_count && role === 'SPARE_PARTS_LIST') ? 'primary' : 'secondary'} disabled={busy} onClick={() => open(role)}>{t(role === 'EXPLODED_SCHEME' ? 'workspace.addScheme' : 'workspace.addList')}</button></div>
    <div className="source-chips">{page.sources.filter(source => source.role === role).map(source => <div key={source.id} className="source-chip">
      <button className="secondary" title={source.filename} disabled={busy} onClick={() => { setDocumentId(documents.find(item => item.sha256 && item.sha256 === source.sha256)?.id ?? source.artifact_id); setStart(source.page_number); open(role) }}>{t('guided.physicalPage', { number: source.page_number })}</button>
      <DraftDeleteButton kind="source" identity={source.id} label={t('workspace.removeSource', { number: source.page_number, role: roleName(role) })} disabled={busy} onDeleted={changed} />
      <details className="source-options"><summary aria-label={t('catalogUx.pageTools')}>⋯</summary><button className="secondary source-order" disabled={busy || page.sources[0]?.id === source.id} onClick={() => void move(source.id, -1)} aria-label={t('guided.moveUp')}>↑</button></details>
    </div>)}</div>
  </section>)}</div></>
  return <section className={`guided-sources ${intent ? 'viewer-open' : ''}`}>
    {error && <p role="alert" className="error">{error}</p>}
    {summary}
    {intent && <section ref={selection} role="dialog" aria-modal="true" tabIndex={-1} className="source-selection" aria-label={t('workspace.sourceSelection')}>
      <div className="source-heading"><strong>{contextLabel}</strong><button className="secondary" disabled={busy} onClick={closeSelection}>{t('common.close')}</button></div>
      <div className="reader-document-tools">
        <label>{t('guided.chooseSource')}<select disabled={busy} value={documentId} onChange={event => { setDocumentId(Number(event.target.value)); setStart(1); setSelected([]) }}>
          <option value="">{t('guided.select')}</option>{documents.map(item => <option key={item.id} value={item.id}>{item.filename}</option>)}
        </select></label>
        <label>{t('guided.upload')}<input type="file" accept="application/pdf,.pdf" disabled={busy} onChange={event => {
          const file = event.target.files?.[0]; if (file) void upload(file); event.target.value = ''
        }} /></label>
      </div>
      {percent !== null && <p role="status">{t(percent >= 100 ? 'guided.validating' : 'guided.uploading', { percent })}</p>}
      {document && <>
        <SourcePageViewer artifactId={document.id} pageCount={document.page_count} number={start} onPage={setStart} />
        <p>{t('ux04.selectionHelp')}</p>
        <div className="pdf-page-picker" aria-label={t('ux04.selectPages')}>
          {Array.from({ length: document.page_count }, (_, index) => index + 1).map(number => <article key={number}>
            <button className="secondary" aria-current={start === number ? 'page' : undefined} onClick={() => setStart(number)}>
              <DocumentThumbnail artifactId={document.id} pageNumber={number} />{t('guided.physicalPage', { number })}
            </button>
            {(['EXPLODED_SCHEME', 'SPARE_PARTS_LIST'] as const).map(role => {
              const assigned = page.sources.some(source => matchesDocument(source) && source.page_number === number && source.role === role)
              return <label key={role}><input type="checkbox" disabled={busy || assigned}
                checked={assigned || !!selected.find(item => item.page_number === number)?.roles.includes(role)}
                onChange={() => toggle(number, role)} />{roleName(role)}</label>
            })}
          </article>)}
        </div>
        <button className="primary" disabled={busy || !selected.length} onClick={() => void assign()}>{t('ux04.addSelected', { count: selected.length })}</button>
        {(page.sources.find(matchesDocument)?.artifact_id || document.assembly_id === page.assembly_id) && <DraftDeleteButton kind="document" identity={page.sources.find(matchesDocument)?.artifact_id || document.id} disabled={busy} label={t('guided.delete')} onDeleted={async () => { setIntent(null); await load(); await changed() }} />}
      </>}
    </section>}
  </section>
}
