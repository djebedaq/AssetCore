import { useEffect, useRef, useState, type FormEvent } from 'react'
import { api, ApiError, createApiObjectUrl } from '../../api'
import { filePayload, Modal } from '../../industrialUi'
import { useI18n, type TranslationKey } from '../../i18n'
import useDraftGuard from './useDraftGuard'

type Page = { visual_page_id: number; artifact_id: number; artifact_title: string; filename: string; sha256: string; page_number: number }
type Map = Page & { id: number }
type PartForm = { position: string; part_number: string; name_bg: string; name_en: string; name_ru: string;
  description: string; description_2: string; quantity: string; quantity_raw: string; unit: string;
  manufacturer: string; category: string; replaced_by_part_number: string; alternative_part_number: string;
  technical_specification: string; technical_notes: string; supplier: string; supplier_code: string }
type Part = Omit<PartForm, 'quantity'> & { id: number; quantity: number | null; source_pages: Map[]; validation_status: 'READY' | 'INCOMPLETE' }
type PreviewRow = { row_number: number; normalized: Record<string, string | number | null>; status: 'VALID' | 'WARNING' | 'ERROR';
  errors: string[]; warnings: string[]; resolved_visual_page_ids: number[] }
type Preview = { token: string; source_digest: string; rows: PreviewRow[];
  summary: { total_rows: number; valid_rows: number; warning_rows: number; error_rows: number; duplicate_rows: number } }

const blank: PartForm = { position: '', part_number: '', name_bg: '', name_en: '', name_ru: '', description: '',
  description_2: '', quantity: '', quantity_raw: '', unit: '', manufacturer: '', category: '',
  replaced_by_part_number: '', alternative_part_number: '', technical_specification: '', technical_notes: '',
  supplier: '', supplier_code: '' }
const fields = Object.keys(blank) as (keyof PartForm)[]
const problemKeys: Record<string, TranslationKey> = {
  catalog_part_invalid: 'builder.part.error.invalid', catalog_part_required: 'builder.part.error.required',
  catalog_part_name_required: 'builder.part.error.name', catalog_part_duplicate: 'builder.part.error.duplicate',
  catalog_part_page_invalid: 'builder.part.error.page', catalog_part_page_duplicate: 'builder.part.error.duplicate',
  catalog_part_import_unmapped: 'builder.part.warning.unmapped',
  catalog_part_import_page_required: 'builder.part.error.page',
  catalog_part_import_page_invalid: 'builder.part.error.page',
  catalog_part_import_page_ambiguous: 'builder.part.error.ambiguous',
  catalog_part_import_page_missing: 'builder.part.error.page',
  catalog_part_import_sha_invalid: 'builder.part.error.page',
  catalog_part_import_duplicate_row: 'builder.part.error.duplicate',
  catalog_part_import_invalid_file: 'builder.part.error.file',
  catalog_part_import_conflict: 'builder.part.error.conflict',
  catalog_part_import_warning_confirmation: 'builder.part.error.warningConfirm',
  catalog_part_import_token_invalid: 'builder.part.error.token',
  catalog_part_position_in_use: 'builder.mapping.error.positionInUse',
  catalog_part_in_repair_kit: 'builder.kit.error.partInKit',
}

function PagePreview({ page }: { page: Page }) {
  const { t } = useI18n()
  const ref = useRef<HTMLDivElement>(null)
  const [url, setUrl] = useState('')
  useEffect(() => {
    let active = true
    let objectUrl = ''
    const node = ref.current
    if (!node) return
    const observer = new IntersectionObserver(entries => {
      if (!entries[0]?.isIntersecting) return
      observer.disconnect()
      void createApiObjectUrl(`/admin/catalog-builder/artifacts/${page.artifact_id}/pages/${page.page_number}/preview`)
        .then(result => { if (active) { objectUrl = result.url; setUrl(result.url) } else URL.revokeObjectURL(result.url) })
        .catch(() => { if (active) setUrl('error') })
    }, { rootMargin: '160px' })
    observer.observe(node)
    return () => { active = false; observer.disconnect(); if (objectUrl) URL.revokeObjectURL(objectUrl) }
  }, [page.artifact_id, page.page_number])
  return <div ref={ref} className="builder-thumbnail">{url && url !== 'error' ?
    <img src={url} alt={t('builder.pageNumber', { count: page.page_number })} loading="lazy" /> :
    <span>{t(url === 'error' ? 'builder.previewError' : 'builder.previewPending')}</span>}</div>
}

export default function RevisionParts({ assemblyId, editable, simple = false, incompleteOnly = false, onDirtyChange, onChanged, referencePageId }: { assemblyId: number; referencePageId?: number; editable: boolean; simple?: boolean; incompleteOnly?: boolean; onDirtyChange?: (dirty: boolean) => void; onChanged?: () => Promise<void> }) {
  const { locale, t } = useI18n()
  const scope = referencePageId ? `/admin/catalog-builder/reference-pages/${referencePageId}` : `/admin/catalog-builder/assemblies/${assemblyId}`
  const [parts, setParts] = useState<Part[]>([])
  const [pages, setPages] = useState<Page[]>([])
  const [editing, setEditing] = useState<Part | 'new' | null>(null)
  const [form, setForm] = useState<PartForm>(blank)
  const [mapping, setMapping] = useState<Part | null>(null)
  const [selected, setSelected] = useState<number[]>([])
  const [importOpen, setImportOpen] = useState(false)
  const [file, setFile] = useState<File | null>(null)
  const [preview, setPreview] = useState<Preview | null>(null)
  const [search, setSearch] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  useDraftGuard(!!editing || !!mapping || busy, onDirtyChange)
  const visibleFields = simple ? (['position', 'part_number', `name_${locale}`, 'description', 'quantity', 'unit'] as (keyof PartForm)[]) : fields
  const problem = (code: string) => t(problemKeys[code] || 'builder.error.generic')
  const message = (caught: unknown) => problem(caught instanceof ApiError ? caught.code || '' : '')
  async function load() {
    const [rows, options] = await Promise.all([
      api<Part[]>(`${scope}/parts`),
      api<Page[]>(`${scope}/spare-list-pages`),
    ])
    setParts(rows); setPages(options)
  }
  useEffect(() => { void load().catch(caught => setError(message(caught))) }, [assemblyId, referencePageId])
  function openForm(part: Part | 'new') {
    setEditing(part)
    setForm(part === 'new' ? blank : Object.fromEntries(fields.map(key => [key, String(part[key] ?? '')])) as PartForm)
  }
  async function save(event: FormEvent) {
    event.preventDefault()
    if (!editing || busy) return
    setBusy(true)
    try {
      const name = form[`name_${locale}`]
      const payload = { ...form, quantity: form.quantity.trim() ? Number(form.quantity) : null,
        ...(simple && !referencePageId ? { name_bg: form.name_bg || name, name_en: form.name_en || name, name_ru: form.name_ru || name } : {}) }
      await api(editing === 'new' ? `${scope}/parts` :
        `/admin/catalog-builder/parts/${editing.id}`, { method: editing === 'new' ? 'POST' : 'PATCH', body: JSON.stringify(payload) })
      setEditing(null); setError(''); await load(); await onChanged?.()
    } catch (caught) { setError(message(caught)) } finally { setBusy(false) }
  }
  async function remove(part: Part) {
    if (!window.confirm(t('builder.part.deleteConfirm'))) return
    try { await api(`/admin/catalog-builder/parts/${part.id}`, { method: 'DELETE' }); await load(); await onChanged?.() }
    catch (caught) { setError(message(caught)) }
  }
  async function saveMapping() {
    if (!mapping || !selected.length || busy) return
    setBusy(true)
    try {
      await api(`/admin/catalog-builder/parts/${mapping.id}/source-pages`,
        { method: 'POST', body: JSON.stringify({ visual_page_ids: selected }) })
      setMapping(null); setSelected([]); await load(); await onChanged?.()
    } catch (caught) { setError(message(caught)) } finally { setBusy(false) }
  }
  async function removeMapping(id: number) {
    try { await api(`/admin/catalog-builder/part-page-maps/${id}`, { method: 'DELETE' }); await load(); await onChanged?.() }
    catch (caught) { setError(message(caught)) }
  }
  async function previewFile() {
    if (!file || busy) return
    setBusy(true)
    try {
      const payload = await filePayload(file)
      const result = await api<Preview>(`${scope}/parts/import-preview`,
        { method: 'POST', body: JSON.stringify({ filename: payload.filename, content_base64: payload.content_base64 }) })
      setPreview(result); setError('')
    } catch (caught) { setError(message(caught)) } finally { setBusy(false) }
  }
  async function confirmImport() {
    if (!preview || preview.summary.error_rows || busy) return
    setBusy(true)
    try {
      await api(`${scope}/parts/import-confirm`,
        { method: 'POST', body: JSON.stringify({ token: preview.token, confirm_warnings: true }) })
      setImportOpen(false); setFile(null); setPreview(null); setError(''); await load()
    } catch (caught) { setError(message(caught)) } finally { setBusy(false) }
  }
  const filtered = parts.filter(part => (!incompleteOnly || part.validation_status === 'INCOMPLETE') && [part.position, part.part_number, part.name_bg, part.name_en,
    part.name_ru, part.description].some(value => String(value || '').toLocaleLowerCase().includes(search.toLocaleLowerCase())))
  const partName = (part: Part) => part[`name_${locale}`] || part.name_bg || part.name_en || part.name_ru || part.description
  return <div className="builder-workspace">
    {error && <p className="error" role="alert">{error}</p>}
    <div className="actions">{editable && <><button className="primary compact" onClick={() => openForm('new')}>{t('builder.part.add')}</button>
      {!simple && <button className="secondary compact" onClick={() => { setImportOpen(true); setPreview(null) }}>{t('builder.part.import')}</button>}</>}</div>
    <input aria-label={t('builder.part.search')} placeholder={t('builder.part.search')} value={search} onChange={event => setSearch(event.target.value)} />
    {!filtered.length && <p>{t('builder.part.empty')}</p>}
    <div className="builder-parts-table"><table><thead><tr>{(['position', 'partNumber', 'name', 'quantity', 'unit', 'sourcePages', 'state', 'actions'] as const)
      .map(key => <th key={key}>{t(`builder.part.${key}`)}</th>)}</tr></thead><tbody>{filtered.map(part => <tr key={part.id}>
        <td>{part.position}</td><td>{part.part_number}</td><td>{partName(part)}</td><td>{part.quantity ?? part.quantity_raw ?? ''}</td><td>{part.unit}</td>
        <td>{part.source_pages.map(page => <div key={page.id}>{page.filename} · {t('builder.pageNumber', { count: page.page_number })}
          {editable && <button className="secondary compact" onClick={() => void removeMapping(page.id)}>{t('common.remove')}</button>}</div>)}</td>
        <td>{t(part.validation_status === 'READY' ? 'builder.part.ready' : 'builder.part.incomplete')}</td>
        <td><div className="actions">{editable && <><button className="secondary compact" onClick={() => openForm(part)}>{t('common.edit')}</button>
          <button className="secondary compact" onClick={() => { setMapping(part); setSelected([]) }}>{t('builder.part.map')}</button>
          <button className="secondary compact" onClick={() => void remove(part)}>{t('common.remove')}</button></>}</div></td>
      </tr>)}</tbody></table></div>
    {editing && <Modal title={t(editing === 'new' ? 'builder.part.add' : 'common.edit')} onClose={() => setEditing(null)} wide>
      <form className="form-grid" onSubmit={event => void save(event)}>{visibleFields.map(key => <label key={key} className={['description', 'description_2', 'technical_specification', 'technical_notes'].includes(key) ? 'wide' : ''}>
        {t(`builder.part.field.${key}` as TranslationKey)}
        {['description', 'description_2', 'technical_specification', 'technical_notes'].includes(key) ?
          <textarea value={form[key]} onChange={event => setForm({ ...form, [key]: event.target.value })} /> :
          <input required={key === 'position' || key === 'part_number'} type={key === 'quantity' ? 'number' : 'text'}
            min={key === 'quantity' ? 0 : undefined} step={key === 'quantity' ? 'any' : undefined}
            value={form[key]} onChange={event => setForm({ ...form, [key]: event.target.value })} />}</label>)}
        <p className="wide muted">{t('builder.part.nameRule')}</p>
        <div className="actions wide"><button type="button" className="secondary" onClick={() => setEditing(null)}>{t('common.cancel')}</button><button className="primary" disabled={busy}>{t('common.save')}</button></div>
      </form></Modal>}
    {mapping && <Modal title={t('builder.part.map')} onClose={() => setMapping(null)} wide>
      <div className="builder-page-grid">{pages.map(page => <label className="builder-page-card" key={page.visual_page_id}>
        <PagePreview page={page} /><b>{page.artifact_title} · {t('builder.pageNumber', { count: page.page_number })}</b>
        {!simple && <small>{page.filename} · {page.sha256}</small>}
        <input type="checkbox" checked={selected.includes(page.visual_page_id) || mapping.source_pages.some(item => item.visual_page_id === page.visual_page_id)}
          disabled={mapping.source_pages.some(item => item.visual_page_id === page.visual_page_id)}
          onChange={() => setSelected(ids => ids.includes(page.visual_page_id) ? ids.filter(id => id !== page.visual_page_id) : [...ids, page.visual_page_id])} />
      </label>)}</div><div className="actions"><button className="primary" disabled={!selected.length || busy} onClick={() => void saveMapping()}>{t('common.save')}</button></div>
    </Modal>}
    {importOpen && <Modal title={t('builder.part.import')} onClose={() => { setImportOpen(false); setPreview(null) }} wide>
      <label>{t('builder.part.csvFile')}<input type="file" accept=".csv,text/csv" onChange={event => { setFile(event.target.files?.[0] || null); setPreview(null) }} /></label>
      <p className="muted">{t('builder.part.csvHelp')}</p>
      <div className="actions"><button className="secondary" disabled={!file || busy} onClick={() => void previewFile()}>{t('builder.part.preview')}</button></div>
      {preview && <><p>{t('builder.part.summary', preview.summary)}</p>
        <div className="builder-parts-table"><table><thead><tr><th>{t('builder.part.row')}</th><th>{t('builder.part.position')}</th><th>{t('builder.part.partNumber')}</th><th>{t('builder.part.state')}</th><th>{t('builder.part.sourcePages')}</th><th>{t('builder.part.problems')}</th></tr></thead>
          <tbody>{preview.rows.map(row => <tr key={row.row_number}><td>{row.row_number}</td><td>{row.normalized.position}</td><td>{row.normalized.part_number}</td>
            <td>{t(`builder.part.import.${row.status}`)}</td><td>{row.resolved_visual_page_ids.map(id => { const page = pages.find(item => item.visual_page_id === id); return page ? `${page.filename} · ${page.page_number}` : id }).join(', ')}</td>
            <td>{[...row.errors, ...row.warnings].map(problem).join('; ')}</td></tr>)}</tbody></table></div>
        {preview.summary.warning_rows > 0 && <p className="muted">{t('builder.part.warningConfirm')}</p>}
        <button className="primary" disabled={preview.summary.error_rows > 0 || busy} onClick={() => void confirmImport()}>{t('builder.part.confirm')}</button></>}
    </Modal>}
  </div>
}
