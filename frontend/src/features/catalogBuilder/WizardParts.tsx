import { useEffect, useState } from 'react'
import { api, ApiError, downloadApiFile } from '../../api'
import { filePayload } from '../../industrialUi'
import { useI18n } from '../../i18n'
import RevisionParts from './RevisionParts'
import IngestReview from './IngestReview'
import useDraftGuard from './useDraftGuard'
import { builderBase, problemKeys, type Document, type Group } from './wizardTypes'

type Preview = { token: string; summary: Record<string, number>; rows: Array<{
  row_number: number; source_page?: string; assembly_code: string; assembly_id: number | null; status: 'VALID' | 'ERROR' | 'WARNING';
  normalized: Record<string, string | number | null>; errors: string[]; warnings: string[];
}> }

export default function WizardParts({ revisionId, groups, groupId, setGroupId, onChanged,
  incompleteOnly, onDirtyChange, onEditorDirtyChange, onDocumentProblem, editorDirty }: {
  revisionId: number; groups: Group[]; groupId: number | null; setGroupId: (id: number) => void;
  onChanged: () => Promise<void>; incompleteOnly: boolean; onDirtyChange: (dirty: boolean) => void;
  onEditorDirtyChange: (dirty: boolean) => void; onDocumentProblem: (page: number) => void
  editorDirty: boolean
}) {
  const { locale, t } = useI18n()
  const [file, setFile] = useState<File | null>(null)
  const [preview, setPreview] = useState<Preview | null>(null)
  const [filter, setFilter] = useState<'all' | 'errors' | 'warnings'>('all')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [documents, setDocuments] = useState<Document[]>([])
  const [sourceId, setSourceId] = useState<number | null>(null)
  const [reviewDirty, setReviewDirty] = useState(false)
  useDraftGuard(!!file || busy || reviewDirty, onDirtyChange)
  const problem = (code: string) => t(problemKeys[code] || 'builder.error.generic')
  const report = (caught: unknown) => setError(problem(caught instanceof ApiError ? caught.code || '' : ''))
  useEffect(() => { void api<Document[]>(`${builderBase}/revisions/${revisionId}/documents`).then(setDocuments).catch(report) }, [revisionId, groups])
  async function previewFile() {
    if (!file || busy) return
    setBusy(true); setError(''); setPreview(null)
    try {
      const payload = await filePayload(file)
      setPreview(await api<Preview>(`${builderBase}/revisions/${revisionId}/parts/import-preview`, {
        method: 'POST', body: JSON.stringify({ filename: payload.filename, content_base64: payload.content_base64 }),
      }))
    } catch (caught) { report(caught) } finally { setBusy(false) }
  }
  async function confirm() {
    if (!preview || busy || editorDirty || preview.summary.error_rows) return
    setBusy(true); setError('')
    try {
      await api(`${builderBase}/revisions/${revisionId}/parts/import-confirm`, {
        method: 'POST', body: JSON.stringify({ token: preview.token, confirm_warnings: true }),
      })
      setFile(null); setPreview(null); await onChanged()
    } catch (caught) { report(caught); setPreview(null) } finally { setBusy(false) }
  }
  const rows = preview?.rows.filter(row => filter === 'all' || filter === 'errors' && row.errors.length || filter === 'warnings' && row.warnings.length) || []
  const source = documents.find(item => item.id === sourceId) || documents[0]
  return <div className="builder-workspace">
    {error && <p className="error" role="alert">{error}</p>}
    <IngestReview revisionId={revisionId} kind="PART" groups={groups} onChanged={onChanged} onDirtyChange={setReviewDirty} blocked={editorDirty} />
    <details><summary>{t('ingest.advanced')}</summary>
    <h4>{t('wizard.import')}</h4><p>{t('wizard.csvHelp')}</p>
    <p className="muted">{t('wizard.csvExampleHelp')}</p>
    <div className="wizard-groups">{groups.map(group => <article key={group.id}>
      <strong>{group[`name_${locale}`] || group.name_bg}</strong><small>{t('wizard.groupCode', { code: group.code })}</small>
    </article>)}</div>
    <button className="secondary" onClick={() => void downloadApiFile(`${builderBase}/revisions/${revisionId}/parts/template`, 'catalog-parts.csv').catch(report)}>{t('wizard.template')}</button>
    <label>{t('builder.part.csvFile')}<input type="file" accept=".csv,text/csv" disabled={busy} onChange={event => { setFile(event.target.files?.[0] || null); setPreview(null) }} /></label>
    <button className="secondary" disabled={busy || !file} onClick={() => void previewFile()}>{t('builder.part.preview')}</button>
    {preview && <>
      <p role="status">{t('builder.part.summary', preview.summary)}</p>
      <div className="actions">{(['all', 'errors', 'warnings'] as const).map(value => <button className={filter === value ? 'primary' : 'secondary'} key={value} aria-pressed={filter === value} onClick={() => setFilter(value)}>{t(`wizard.${value}`)}</button>)}</div>
      {!rows.length && <p>{t('wizard.noPreviewRows')}</p>}
      <div className="builder-parts-table"><table><thead><tr>
        <th>{t('builder.part.row')}</th><th>{t('wizard.group')}</th><th>{t('builder.part.position')}</th>
        <th>{t('builder.part.partNumber')}</th><th>{t('builder.part.state')}</th><th>{t('builder.part.problems')}</th>
      </tr></thead><tbody>{rows.map(row => <tr key={row.row_number}>
        <td>{row.row_number}</td><td>{groups.find(group => group.id === row.assembly_id)?.[`name_${locale}`] || row.assembly_code}</td>
        <td>{row.normalized.position}</td><td>{row.normalized.part_number}</td><td>{t(`builder.part.import.${row.status}`)}</td>
        <td>{[...row.errors, ...row.warnings].map(problem).join('; ')}
          {row.errors.some(code => code.includes('page')) && Number(row.source_page || row.normalized.source_page) > 0 &&
            <button className="secondary compact" onClick={() => onDocumentProblem(Number(row.source_page || row.normalized.source_page))}>{t('wizard.physicalPage', { number: Number(row.source_page || row.normalized.source_page) })}</button>}
        </td>
      </tr>)}</tbody></table></div>
      {preview.rows.some(row => row.errors.includes('catalog_part_import_page_ambiguous')) && source && <div>
        <p>{t('wizard.csvAmbiguityHelp')}</p>
        <label>{t('wizard.documents')}<select value={source.id} onChange={event => setSourceId(Number(event.target.value))}>
          {documents.map(document => <option key={document.id} value={document.id}>{document.filename}</option>)}
        </select></label><p>{t('wizard.chooseSource', { filename: source.filename })}</p><code>{source.sha256}</code>
      </div>}
      <button className="primary" disabled={busy || editorDirty || preview.summary.error_rows > 0} onClick={() => void confirm()}>{t('builder.part.confirm')}</button>
    </>}
    </details>
    <label>{t('wizard.group')}<select value={groupId ?? ''} onChange={event => setGroupId(Number(event.target.value))}>
      {!groups.length && <option value="">{t('wizard.noGroups')}</option>}
      {groups.map(group => <option key={group.id} value={group.id}>{group[`name_${locale}`] || group.name_bg}</option>)}
    </select></label>
    {groupId && <RevisionParts key={`${groupId}-${groups.find(group => group.id === groupId)?.part_count}`} assemblyId={groupId} editable simple incompleteOnly={incompleteOnly} onDirtyChange={onEditorDirtyChange} onChanged={onChanged} />}
  </div>
}
