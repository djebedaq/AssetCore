import { type FormEvent, useEffect, useRef, useState } from 'react'
import {
  Archive,
  BookOpen,
  ChevronRight,
  Download,
  FileText,
  ImagePlus,
  PackageCheck,
  Plus,
  Search,
  ShieldCheck,
  Upload,
  Wrench,
  X,
} from 'lucide-react'
import { api, downloadApiFile } from './api'
import AuthenticatedImage from './AuthenticatedImage'
import {
  AttachmentList,
  DOCUMENT_KEYS,
  DocumentButtons,
  DownloadButton,
  Modal,
  filePayload,
  friendlyError,
  translatedCode,
  translatedEventCode,
} from './industrialUi'
import { statusText, useI18n, type TranslationKey } from './i18n'
import type { Locale } from './locale'
import { hasPermission } from './permissions'
import type {
  AssetCategory,
  Department,
  GlobalSearchResults,
  Location,
  MachinePassport,
  TechnicalLibraryDocument,
} from './types'

export { IndustrialRepairs } from './features/repairs/IndustrialRepairs'
export { IndustrialCatalog } from './features/catalog/IndustrialCatalog'

function optionalJson(text: string, shape: 'object' | 'array'): Record<string, unknown> | unknown[] | null {
  if (!text.trim()) return null
  const value = JSON.parse(text) as unknown
  const valid = shape === 'array'
    ? Array.isArray(value)
    : Boolean(value) && typeof value === 'object' && !Array.isArray(value)
  if (!valid) throw new Error(`invalid_${shape}`)
  return value as Record<string, unknown> | unknown[]
}


export function GlobalSearchBox({ onMachine }: { onMachine: (machineId: number) => void }) {
  const { t } = useI18n()
  const [query, setQuery] = useState('')
  const [results, setResults] = useState<GlobalSearchResults | null>(null)
  const [open, setOpen] = useState(false)

  useEffect(() => {
    if (query.trim().length < 2) {
      setResults(null)
      return
    }
    const timer = window.setTimeout(() => {
      void api<GlobalSearchResults>(`/search?q=${encodeURIComponent(query.trim())}`)
        .then((data) => { setResults(data); setOpen(true) })
        .catch(() => setResults(null))
    }, 250)
    return () => window.clearTimeout(timer)
  }, [query])

  const total = results
    ? results.machines.length + results.parts.length + results.documents.length + results.repairs.length + results.part_requests.length + results.transfers.length + results.generated_documents.length
    : 0
  return (
    <div className="global-search">
      <Search size={17} />
      <input aria-label={t('global.search')} placeholder={t('global.placeholder')} value={query} onChange={(event) => setQuery(event.target.value)} onFocus={() => setOpen(true)} />
      {open && query.trim().length >= 2 && (
        <div className="global-results">
          <div className="global-results-head"><b>{t('global.results', { count: total })}</b><button onClick={() => setOpen(false)} aria-label={t('common.close')}><X size={16} /></button></div>
          {!total && <div className="empty-state">{t('global.empty')}</div>}
          {results?.machines.map((item) => <button key={`m-${item.id}`} onClick={() => { onMachine(item.id); setOpen(false) }}><span><b>{item.name}</b><small>{item.brand} · №{item.inventory_number}</small></span><span className="badge">{statusText(t, item.status)}</span></button>)}
          {results?.parts.map((item) => <div className="global-result-row" key={`p-${item.id}`}><PackageCheck size={17} /><span><b>{item.part_number}</b><small>{item.description}</small></span>{item.is_verified && <ShieldCheck size={16} />}</div>)}
          {results?.documents.map((item) => <button key={`d-${item.id}`} onClick={() => { void downloadApiFile(item.download_endpoint, item.title); setOpen(false) }}><FileText size={17} /><span><b>{item.title}</b><small>{item.brand} · {item.category}</small></span></button>)}
          {results?.repairs.map((item) => <div className="global-result-row" key={`r-${item.id}`}><Wrench size={17} /><span><b>{item.repair_reference}</b><small>№{item.machine_number} · {item.reported_problem}</small></span><span className="badge">{statusText(t, item.status, 'repair')}</span></div>)}
          {results?.part_requests.map((item) => <div className="global-result-row" key={`q-${item.id}`}><Archive size={17} /><span><b>{item.request_reference}</b><small>{item.part_name}</small></span><span className="badge">{statusText(t, item.status, 'part')}</span></div>)}
          {results?.transfers.map((item) => <div className="global-result-row" key={`t-${item.id}`}><ChevronRight size={17} /><span><b>{item.protocol_number}</b><small>№{item.machine_number} · {item.batch_reference || item.location_text || item.company_unit || t('common.notSpecified')}</small></span><span className="badge">{item.is_active ? t('global.activeTransfer') : t('global.closedTransfer')}</span></div>)}
          {results?.generated_documents.map((item) => <button key={`g-${item.id}`} onClick={() => { void downloadApiFile(item.download_endpoint, item.filename); setOpen(false) }}><FileText size={17} /><span><b>{item.document_number}</b><small>{translatedCode(t, item.document_type, DOCUMENT_KEYS)} · {item.format.toUpperCase()}</small></span></button>)}
        </div>
      )}
    </div>
  )
}

export function MachinePassportModal({ machineId, onClose, onOpenCatalog }: { machineId: number; onClose: () => void; onOpenCatalog?: () => void }) {
  const { date, locale, t } = useI18n()
  const [passport, setPassport] = useState<MachinePassport | null>(null)
  const [tab, setTab] = useState<'passport' | 'history' | 'repairs' | 'parts' | 'transfers' | 'requests' | 'files' | 'documents' | 'audit'>('passport')
  const [error, setError] = useState('')
  const [uploading, setUploading] = useState(false)
  const [customValues, setCustomValues] = useState<Record<number, string>>({})
  const fileRef = useRef<HTMLInputElement>(null)

  const load = () => api<MachinePassport>(`/machines/${machineId}/passport`)
    .then((data) => {
      setPassport(data)
      setCustomValues(Object.fromEntries(data.custom_fields.map((field) => [field.field_id, field.value || ''])))
      setError('')
    })
    .catch((caught) => setError(friendlyError(caught, t('passport.loadError'))))
  useEffect(() => { void load() }, [machineId])

  async function upload(file?: File) {
    if (!file) return
    setUploading(true)
    try {
      await api(`/machines/${machineId}/attachments`, { method: 'POST', body: JSON.stringify({ ...(await filePayload(file)), kind: file.type.startsWith('image/') ? 'PHOTO' : 'DOCUMENT' }) })
      await load()
      setTab('files')
    } catch (caught) {
      setError(friendlyError(caught, t('passport.uploadError')))
    } finally {
      setUploading(false)
      if (fileRef.current) fileRef.current.value = ''
    }
  }

  async function saveCustomFields() {
    try {
      await api(`/machines/${machineId}/custom-fields`, { method: 'PUT', body: JSON.stringify({ values: Object.entries(customValues).map(([fieldId, value]) => ({ field_id: Number(fieldId), value: value || null })) }) })
      await load()
    } catch (caught) {
      setError(friendlyError(caught, t('passport.saveFieldsError')))
    }
  }

  function customFieldControl(field: MachinePassport['custom_fields'][number]) {
    const value = customValues[field.field_id] || ''
    const update = (nextValue: string) => setCustomValues((current) => ({ ...current, [field.field_id]: nextValue }))
    const disabled = !hasPermission('assets.edit')
    if (field.field_type === 'BOOLEAN') {
      return <select disabled={disabled} required={field.is_required} value={value} onChange={(event) => update(event.target.value)}><option value="">{t('common.notSpecified')}</option><option value="true">{t('common.yes')}</option><option value="false">{t('common.no')}</option></select>
    }
    if (field.field_type === 'SELECT') {
      return <select disabled={disabled} required={field.is_required} value={value} onChange={(event) => update(event.target.value)}><option value="">{t('common.notSpecified')}</option>{(field.options || []).map((option) => <option value={option} key={option}>{option}</option>)}</select>
    }
    const inputType = field.field_type === 'DATE' ? 'date' : ['INTEGER', 'DECIMAL'].includes(field.field_type) ? 'number' : 'text'
    return <input disabled={disabled} required={field.is_required} type={inputType} step={field.field_type === 'DECIMAL' ? 'any' : undefined} value={value} onChange={(event) => update(event.target.value)} />
  }

  return (
    <Modal title={passport ? t('passport.title', { number: passport.machine.inventory_number }) : t('passport.loadingTitle')} onClose={onClose} wide>
      {error && <div className="error" role="alert">{error}</div>}
      {!passport ? <div className="loading">{t('common.loading')}</div> : passport.limited_view ? (
        <div className="passport-grid observer-passport">
          <section>
            <h4>{t('passport.currentState')}</h4>
            <dl className="detail-grid">
              <div><dt>{t('machines.inventoryNumber')}</dt><dd>{passport.machine.inventory_number}</dd></div>
              <div><dt>{t('machines.brand')}</dt><dd>{passport.machine.brand}</dd></div>
              <div><dt>{t('common.status')}</dt><dd>{statusText(t, passport.machine.status)}</dd></div>
              <div><dt>{t('common.location')}</dt><dd>{passport.machine.location?.name || t('common.notSpecified')}</dd></div>
              <div><dt>{t('passport.availability')}</dt><dd>{passport.current_state.available ? t('bulk.available') : t('bulk.unavailable')}</dd></div>
            </dl>
          </section>
        </div>
      ) : <>
        <div className="passport-hero">
          <AuthenticatedImage src={`/machines/${machineId}/qr`} alt={t('machines.qrAlt', { number: passport.machine.inventory_number })} />
          <div><span className="eyebrow">{passport.machine.category_definition?.[`name_${locale}` as 'name_bg'] || passport.machine.category}</span><h2>{passport.machine.name}</h2><p>{passport.machine.brand} {passport.machine.model} · {passport.machine.pressure_bar} bar</p><span className="badge">{statusText(t, passport.machine.status)}</span></div>
          <div className="passport-trace"><small>{t('machines.serialNumber')}</small><b>{passport.machine.serial_number || t('common.noValue')}</b><small>{t('common.location')}</small><b>{passport.machine.location?.name || t('common.notSpecified')}</b></div>
        </div>
        <div className="tabs" role="tablist">
          {(['passport', 'history', 'repairs', 'parts', 'transfers', 'requests', 'files', 'documents', ...(passport.audit_visible ? ['audit' as const] : [])] as const).map((value) => <button key={value} className={tab === value ? 'active' : ''} onClick={() => setTab(value)}>{t(`passport.tab.${value}`)}</button>)}
        </div>
        {tab === 'passport' && <div className="passport-grid">
          <section><h4>{t('passport.identification')}</h4><dl className="detail-grid">
            <div><dt>{t('machines.inventoryNumber')}</dt><dd>{passport.machine.inventory_number}</dd></div><div><dt>{t('machines.brand')}</dt><dd>{passport.machine.brand}</dd></div>
            <div><dt>{t('machines.model')}</dt><dd>{passport.machine.model || t('common.noValue')}</dd></div><div><dt>{t('machines.pressure')}</dt><dd>{passport.machine.pressure_bar} bar</dd></div>
            <div><dt>{t('passport.manufacturer')}</dt><dd>{passport.machine.manufacturer || t('common.noValue')}</dd></div><div><dt>{t('passport.manufactureYear')}</dt><dd>{passport.machine.manufacture_year || t('common.noValue')}</dd></div>
            <div><dt>{t('passport.department')}</dt><dd>{passport.machine.department || t('common.noValue')}</dd></div><div><dt>{t('passport.responsible')}</dt><dd>{passport.machine.responsible_person || t('common.noValue')}</dd></div>
            <div><dt>{t('machines.assetType')}</dt><dd>{passport.machine.asset_type || t('common.noValue')}</dd></div><div><dt>{t('machines.subtype')}</dt><dd>{passport.machine.subtype || t('common.noValue')}</dd></div>
            <div><dt>{t('machines.ownership')}</dt><dd>{passport.machine.ownership || t('common.noValue')}</dd></div><div><dt>{t('machines.commissioningDate')}</dt><dd>{passport.machine.commissioning_date ? date(passport.machine.commissioning_date) : t('common.noValue')}</dd></div>
            <div><dt>{t('machines.capacity')}</dt><dd>{passport.machine.capacity || t('common.noValue')}</dd></div><div><dt>{t('machines.dimensions')}</dt><dd>{passport.machine.dimensions || t('common.noValue')}</dd></div>
            <div><dt>{t('machines.active')}</dt><dd>{passport.machine.is_active ? t('common.yes') : t('common.no')}</dd></div><div><dt>{t('passport.addedAt')}</dt><dd>{date(passport.machine.created_at)}</dd></div>
          </dl></section>
          <section><h4>{t('passport.customFields')}</h4>{passport.custom_fields.map((field) => <label key={field.field_id}>{field[`label_${locale}` as 'label_bg'] || field.label_bg}{field.unit ? ` (${field.unit})` : ''}{customFieldControl(field)}</label>)}{!passport.custom_fields.length && <div className="empty-state">{t('passport.noCustomFields')}</div>}{hasPermission('assets.edit') && passport.custom_fields.length > 0 && <button className="primary" onClick={saveCustomFields}>{t('common.save')}</button>}</section>
          <section><h4>{t('passport.currentState')}</h4><dl className="detail-grid">
            <div><dt>{t('passport.availability')}</dt><dd>{passport.current_state.available ? t('bulk.available') : t('bulk.unavailable')}</dd></div>
            <div><dt>{t('passport.activeTransfer')}</dt><dd>{passport.current_state.active_transfer?.protocol_number || t('common.noValue')}</dd></div>
            <div><dt>{t('passport.activeRepair')}</dt><dd>{passport.current_state.active_repair?.repair_reference || t('common.noValue')}</dd></div>
            <div><dt>{t('passport.lastMovement')}</dt><dd>{passport.current_state.last_movement ? `${translatedEventCode(t, passport.current_state.last_movement.event_type)} · ${date(passport.current_state.last_movement.created_at)}` : t('common.noValue')}</dd></div>
            <div><dt>{t('passport.lastInspection')}</dt><dd>{passport.current_state.last_inspection ? date(passport.current_state.last_inspection.completed_at) : t('common.noValue')}</dd></div>
            <div><dt>{t('passport.lastTest')}</dt><dd>{passport.current_state.last_test ? `${passport.current_state.last_test.passed ? t('common.yes') : t('common.no')} ${passport.current_state.last_test.completed_at ? `· ${date(passport.current_state.last_test.completed_at)}` : ''}` : t('common.noValue')}</dd></div>
          </dl><div className="summary-chips">{passport.current_state.allowed_actions.issue && <span>{t('bulk.issue')}</span>}{passport.current_state.allowed_actions.return && <span>{t('bulk.return')}</span>}{passport.current_state.allowed_actions.repair && <span>{t('nav.repairs')}</span>}{passport.current_state.allowed_actions.edit && <span>{t('common.edit')}</span>}</div>{passport.current_state.active_transfer && <div className="record-detail"><b>{passport.current_state.active_transfer.protocol_number}</b><span>{[passport.current_state.active_transfer.company_unit, passport.current_state.active_transfer.department, passport.current_state.active_transfer.vessel, passport.current_state.active_transfer.dock, passport.current_state.active_transfer.pier, passport.current_state.active_transfer.work_area, passport.current_state.active_transfer.location_text].filter(Boolean).join(' · ')}</span><small>{passport.current_state.active_transfer.issued_at ? date(passport.current_state.active_transfer.issued_at) : t('common.noValue')}</small></div>}</section>
          <section><h4>{t('passport.activeLinks')}</h4><div className="summary-chips"><span>{t('passport.repairsCount', { count: passport.repairs.length })}</span><span>{t('passport.transfersCount', { count: passport.transfers.length })}</span><span>{t('passport.requestsCount', { count: passport.part_requests.length })}</span><span>{t('passport.documentsCount', { count: passport.generated_documents.length + passport.technical_documents.length })}</span></div></section>
        </div>}
        {tab === 'history' && <div className="timeline">{passport.history.map((event) => <div key={event.id}><i /><span><b>{translatedEventCode(t, event.event_type)}</b><small>{date(event.created_at)} · {event.reference || t('common.system')}</small>{(event.previous_status || event.new_status) && <em>{event.previous_status ? statusText(t, event.previous_status) : ''} → {event.new_status ? statusText(t, event.new_status) : ''}</em>}</span></div>)}{!passport.history.length && <div className="empty-state">{t('passport.noHistory')}</div>}</div>}
        {tab === 'repairs' && <div className="document-list">{passport.repairs.map((repair) => <div key={repair.id}><span><b>{repair.repair_reference || t('common.noValue')}</b><small>{statusText(t, repair.status)} · {date(repair.opened_at)}</small><em>{repair.reported_problem}</em></span></div>)}{!passport.repairs.length && <div className="empty-state">{t('passport.noRepairs')}</div>}</div>}
        {tab === 'parts' && <><div className="toolbar"><div><h4>{t('passport.tab.parts')}</h4></div>{onOpenCatalog && <button className="primary" onClick={onOpenCatalog}><PackageCheck size={16} />{t('passport.openCatalog')}</button>}</div><div className="document-list">{passport.parts_used.map((part) => <div key={part.id}><span><b>{part.part_number || t('common.noValue')} · {part.description}</b><small>{part.repair_reference || t('common.noValue')} · {date(part.created_at)}</small><em>{part.quantity} {part.unit || ''}{part.source ? ` · ${part.source}` : ''}</em></span></div>)}{!passport.parts_used.length && <div className="empty-state">{t('passport.noParts')}</div>}</div></>}
        {tab === 'transfers' && <div className="document-list">{passport.transfers.map((transfer) => <div key={transfer.id}><span><b>{transfer.protocol_number}</b><small>{transfer.is_active ? t('global.activeTransfer') : t('global.closedTransfer')} · {transfer.issued_at ? date(transfer.issued_at) : t('common.noValue')}</small><em>{[transfer.batch_reference, transfer.location_text, transfer.accepted_by].filter(Boolean).join(' · ')}</em></span></div>)}{!passport.transfers.length && <div className="empty-state">{t('passport.noTransfers')}</div>}</div>}
        {tab === 'requests' && <div className="document-list">{passport.part_requests.map((request) => <div key={request.id}><span><b>{request.request_reference || t('common.noValue')}</b><small>{statusText(t, request.status, 'part')} · {statusText(t, request.priority, 'part')} · {date(request.created_at)}</small></span></div>)}{!passport.part_requests.length && <div className="empty-state">{t('passport.noRequests')}</div>}</div>}
        {tab === 'files' && <><div className="toolbar"><div><h4>{t('passport.attachments')}</h4></div>{hasPermission('repairs.edit') && <><input ref={fileRef} hidden type="file" accept="image/png,image/jpeg,image/webp,application/pdf,.docx,.xlsx" onChange={(event) => void upload(event.target.files?.[0])} /><button className="primary" disabled={uploading} onClick={() => fileRef.current?.click()}><ImagePlus size={17} />{uploading ? t('passport.uploading') : t('passport.addFile')}</button></>}</div><AttachmentList items={passport.attachments} /></>}
        {tab === 'documents' && <div className="document-list">{passport.generated_documents.map((item) => <div key={`g-${item.id}`}><span><b>{item.document_number}</b><small>{translatedCode(t, item.document_type, DOCUMENT_KEYS)} · {date(item.created_at)}</small></span><DocumentButtons path={item.download_endpoint} filename={item.filename} format={item.format} /></div>)}{passport.technical_documents.map((item) => <div key={`t-${item.id}`}><span><b>{item.title}</b><small>{translatedCode(t, item.document_type, DOCUMENT_KEYS)} · {item.revision || t('common.noValue')} · {item.language || t('common.noValue')}</small></span><button className="secondary compact" onClick={() => void downloadApiFile(item.download_endpoint, item.title)}><Download size={15} />{t('common.download')}</button></div>)}{!passport.generated_documents.length && !passport.technical_documents.length && <div className="empty-state">{t('passport.noDocuments')}</div>}</div>}
        {tab === 'audit' && <div className="document-list">{passport.audit.map((entry) => <div key={entry.id}><span><b>{entry.action}</b><small>{date(entry.created_at)} · {entry.user_name || t('common.system')} · {entry.entity_type} #{entry.entity_id || t('common.noValue')}</small><em>{entry.operation_reference || ''}</em></span></div>)}{!passport.audit.length && <div className="empty-state">{t('audit.empty')}</div>}</div>}
      </>}
    </Modal>
  )
}


export { PartRequestsTracking as IndustrialPartRequests } from './features/partRequests/PartRequestsTracking'

export function TechnicalLibrary() {
  const { t } = useI18n()
  const [items, setItems] = useState<TechnicalLibraryDocument[]>([])
  const [query, setQuery] = useState('')
  const [error, setError] = useState('')
  const [showUpload, setShowUpload] = useState<'new' | number | null>(null)
  const load = () => api<TechnicalLibraryDocument[]>(`/technical-library?q=${encodeURIComponent(query)}`).then((data) => { setItems(data); setError('') }).catch((caught) => setError(friendlyError(caught, t('documents.loadError'))))
  useEffect(() => { void load() }, [query])
  const revisionTarget = typeof showUpload === 'number' ? items.find((item) => item.id === showUpload) : undefined
  return <><div className="toolbar"><div><h3>{t('documents.title')}</h3><p className="muted">{t('library.versionHint')}</p></div>{hasPermission('settings.manage') && <button className="primary" onClick={() => setShowUpload('new')}><Upload size={17} />{t('library.upload')}</button>}</div><div className="filters"><div className="searchbox"><Search size={17} /><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder={t('library.searchPlaceholder')} /></div></div>{error && <div className="error">{error}</div>}<div className="library-grid">{items.map((document) => <article className="panel library-card" key={document.id}><div className="library-card-head"><BookOpen /><span><h4>{document.title}</h4><small>{document.brand} · {document.model || document.category}</small></span></div><div className="library-meta"><span>{t('library.revision')}: {document.revision || t('common.noValue')}</span><span>{t('library.versions', { count: document.revisions.length })}</span>{document.language && <span>{t(`language.${document.language}` as TranslationKey)}</span>}{document.page_count && <span>{t('library.pages', { count: document.page_count })}</span>}{document.linked_machine_numbers?.length ? <span>{t('library.linkedMachineCount', { count: document.linked_machine_numbers.length })}</span> : null}{document.tags?.map((tag) => <span className="badge" key={tag}>{tag}</span>)}{document.sha256 && <code>SHA-256 {document.sha256.slice(0, 12)}…</code>}</div>{document.source_label && <p className="muted">{t('library.source')}: {document.source_label}</p>}<div className="actions"><DownloadButton path={document.download_endpoint} filename={document.title} />{hasPermission('settings.manage') && <button className="secondary compact" onClick={() => setShowUpload(document.id)}><Upload size={15} />{t('library.newRevision')}</button>}</div><details><summary>{t('library.versionHistory')}</summary>{document.revisions.map((revision) => <div className="revision-row" key={revision.id}><span><b>v{revision.version} · {revision.revision_label || t('common.noValue')}</b><small>{revision.change_note}</small></span><DownloadButton path={revision.download_endpoint} filename={revision.filename} /></div>)}</details></article>)}{!items.length && <div className="empty-state">{t('documents.empty')}</div>}</div>{showUpload && <TechnicalUploadModal document={revisionTarget} onClose={() => setShowUpload(null)} onSaved={() => { setShowUpload(null); void load() }} />}</>
}

function TechnicalUploadModal({ document, onClose, onSaved }: { document?: TechnicalLibraryDocument; onClose: () => void; onSaved: () => void }) {
  const { locale, t } = useI18n()
  const [form, setForm] = useState({ brand: document?.brand || '', model: document?.model || '', category: document?.category || '', title: document?.title || '', revision: '', change_note: '', source_label: document?.source_label || '', document_date: document?.document_date?.slice(0, 10) || '', tags_text: document?.tags?.join(', ') || '', page_count: document?.page_count ? String(document.page_count) : '', notes: document?.notes || '', linked_machine_numbers_text: document?.linked_machine_numbers?.join(', ') || '' })
  const [file, setFile] = useState<File | null>(null)
  const [error, setError] = useState('')
  async function submit(event: FormEvent) {
    event.preventDefault()
    if (!file) return
    const path = document ? `/technical-library/${document.id}/revisions` : '/technical-library'
    const { tags_text, linked_machine_numbers_text, ...values } = form
    try { await api(path, { method: 'POST', body: JSON.stringify({ ...values, language: locale, document_date: form.document_date || null, page_count: form.page_count ? Number(form.page_count) : null, tags: tags_text.split(',').map((item) => item.trim()).filter(Boolean), linked_machine_numbers: linked_machine_numbers_text.split(/[;,\s]+/).map((item) => item.trim()).filter(Boolean), ...(await filePayload(file)) }) }); onSaved() } catch (caught) { setError(friendlyError(caught, t('library.uploadError'))) }
  }
  return <Modal title={document ? t('library.newRevision') : t('library.upload')} onClose={onClose} wide><form className="form-grid" onSubmit={submit}><label>{t('machines.brand')}<input required disabled={Boolean(document)} value={form.brand} onChange={(event) => setForm({ ...form, brand: event.target.value })} /></label><label>{t('machines.model')}<input disabled={Boolean(document)} value={form.model} onChange={(event) => setForm({ ...form, model: event.target.value })} /></label><label>{t('machines.category')}<input required disabled={Boolean(document)} value={form.category} onChange={(event) => setForm({ ...form, category: event.target.value })} /></label><label>{t('library.revision')}<input required value={form.revision} onChange={(event) => setForm({ ...form, revision: event.target.value })} /></label><label className="wide">{t('library.title')}<input required disabled={Boolean(document)} value={form.title} onChange={(event) => setForm({ ...form, title: event.target.value })} /></label><label>{t('library.source')}<input value={form.source_label} onChange={(event) => setForm({ ...form, source_label: event.target.value })} /></label><label>{t('library.documentDate')}<input type="date" value={form.document_date} onChange={(event) => setForm({ ...form, document_date: event.target.value })} /></label><label>{t('library.pageCount')}<input type="number" min="1" value={form.page_count} onChange={(event) => setForm({ ...form, page_count: event.target.value })} /></label><label>{t('library.tags')}<input value={form.tags_text} onChange={(event) => setForm({ ...form, tags_text: event.target.value })} /></label><label className="wide">{t('library.linkedMachines')}<input value={form.linked_machine_numbers_text} onChange={(event) => setForm({ ...form, linked_machine_numbers_text: event.target.value })} placeholder={t('catalog.compatibleMachinesHint')} /></label><label className="wide">{t('common.notes')}<textarea value={form.notes} onChange={(event) => setForm({ ...form, notes: event.target.value })} /></label><label className="wide">{t('library.changeNote')}<textarea required={Boolean(document)} value={form.change_note} onChange={(event) => setForm({ ...form, change_note: event.target.value })} /></label><label className="wide">{t('library.file')}<input required type="file" accept="application/pdf,.docx,.xlsx,image/png,image/jpeg,image/webp" onChange={(event) => setFile(event.target.files?.[0] || null)} /></label>{error && <div className="error wide">{error}</div>}<div className="actions wide"><button type="button" className="secondary" onClick={onClose}>{t('common.cancel')}</button><button className="primary" disabled={!file}>{document ? t('library.addRevision') : t('library.upload')}</button></div></form></Modal>
}

type DocumentTemplateInfo = { id: number; code: string; document_type: string; name_bg: string; is_active: boolean; versions: Array<{ id: number; version: number; language: string; source_filename?: string | null; source_sha256?: string | null; effective_from?: string | null; effective_to?: string | null; required_fields?: string[] | null; numbering_rule?: string | null; department?: string | null; change_note?: string | null; validation_status?: 'NOT_VALIDATED' | 'PASSED' | 'FAILED'; validation_report?: { errors?: string[] } | null; validated_at?: string | null; is_published: boolean; download_endpoint: string }> }
type AdminReferenceData = { locations: Location[]; departments: Department[] }

export function AdministrationPanel() {
  const { locale, t } = useI18n()
  const [categories, setCategories] = useState<AssetCategory[]>([])
  const [templates, setTemplates] = useState<DocumentTemplateInfo[]>([])
  const [locations, setLocations] = useState<Location[]>([])
  const [departments, setDepartments] = useState<Department[]>([])
  const [error, setError] = useState('')
  const [modal, setModal] = useState<'category' | 'field' | 'template' | 'location' | 'department' | null>(null)
  const [categoryId, setCategoryId] = useState<number | null>(null)
  const [categoryForm, setCategoryForm] = useState({ code: '', name_bg: '', name_en: '', name_ru: '', description: '', icon: '', validation_rules_text: '', document_types_text: '', checklists_text: '', status_codes_text: '' })
  const [fieldForm, setFieldForm] = useState({ code: '', label_bg: '', label_en: '', label_ru: '', field_type: 'TEXT', is_required: false, options_text: '', unit: '', validation_rules_text: '' })
  const [templateForm, setTemplateForm] = useState({ code: '', document_type: 'OTHER', name_bg: '', name_en: '', name_ru: '' })
  const [locationForm, setLocationForm] = useState({ name: '', description: '' })
  const [departmentForm, setDepartmentForm] = useState({ code: '', name_bg: '', name_en: '', name_ru: '', description: '' })
  const [versionTarget, setVersionTarget] = useState<DocumentTemplateInfo | null>(null)
  const emptyVersionForm = { language: locale, layout_contract: '{\n  "reference_only": true\n}', effective_from: '', effective_to: '', required_fields: '', numbering_rule: '', department: '', change_note: '' }
  const [versionForm, setVersionForm] = useState(emptyVersionForm)
  const [versionFile, setVersionFile] = useState<File | null>(null)
  const [importText, setImportText] = useState('')
  const [importPreview, setImportPreview] = useState<{ valid_records: Array<Record<string, unknown>>; errors: Array<{ row: number; message: string }>; can_confirm: boolean; preview_token?: string | null; message: string } | null>(null)
  const load = () => Promise.all([api<AssetCategory[]>('/categories'), api<DocumentTemplateInfo[]>('/document-templates'), api<AdminReferenceData>('/admin/reference-data')]).then(([categoryItems, templateItems, referenceData]) => { setCategories(categoryItems); setTemplates(templateItems); setLocations(referenceData.locations); setDepartments(referenceData.departments); setError('') }).catch((caught) => setError(friendlyError(caught, t('admin.loadError'))))
  useEffect(() => { if (hasPermission('settings.manage')) void load() }, [])
  if (!hasPermission('settings.manage')) return null
  async function createCategory(event: FormEvent) {
    event.preventDefault()
    try {
      const { validation_rules_text, document_types_text, checklists_text, status_codes_text, ...values } = categoryForm
      await api('/categories', { method: 'POST', body: JSON.stringify({ ...values, validation_rules: optionalJson(validation_rules_text, 'object'), document_types: optionalJson(document_types_text, 'array'), checklists: optionalJson(checklists_text, 'array'), status_codes: optionalJson(status_codes_text, 'array') }) })
      setModal(null)
      await load()
    } catch (caught) { setError(caught instanceof SyntaxError || (caught instanceof Error && caught.message.startsWith('invalid_')) ? t('admin.configurationJsonError') : friendlyError(caught, t('admin.saveError'))) }
  }
  async function createField(event: FormEvent) {
    event.preventDefault()
    if (!categoryId) return
    const { options_text, validation_rules_text, ...values } = fieldForm
    const options = fieldForm.field_type === 'SELECT'
      ? options_text.split(/[,\n]/).map((item) => item.trim()).filter(Boolean)
      : null
    try { await api(`/categories/${categoryId}/fields`, { method: 'POST', body: JSON.stringify({ ...values, options, validation_rules: optionalJson(validation_rules_text, 'object') }) }); setModal(null); await load() } catch (caught) { setError(caught instanceof SyntaxError || (caught instanceof Error && caught.message.startsWith('invalid_')) ? t('admin.configurationJsonError') : friendlyError(caught, t('admin.saveError'))) }
  }
  async function createTemplate(event: FormEvent) {
    event.preventDefault()
    try { await api('/document-templates', { method: 'POST', body: JSON.stringify(templateForm) }); setModal(null); await load() } catch (caught) { setError(friendlyError(caught, t('admin.saveError'))) }
  }
  async function createLocation(event: FormEvent) {
    event.preventDefault()
    try { await api('/admin/locations', { method: 'POST', body: JSON.stringify(locationForm) }); setLocationForm({ name: '', description: '' }); setModal(null); await load() } catch (caught) { setError(friendlyError(caught, t('admin.saveError'))) }
  }
  async function toggleLocation(location: Location) {
    if (!window.confirm(t(location.is_active ? 'admin.deactivateLocationConfirm' : 'admin.activateLocationConfirm'))) return
    try { await api(`/admin/locations/${location.id}`, { method: 'PATCH', body: JSON.stringify({ is_active: !location.is_active }) }); await load() } catch (caught) { setError(friendlyError(caught, t('admin.saveError'))) }
  }
  async function createDepartment(event: FormEvent) {
    event.preventDefault()
    try { await api('/admin/departments', { method: 'POST', body: JSON.stringify(departmentForm) }); setDepartmentForm({ code: '', name_bg: '', name_en: '', name_ru: '', description: '' }); setModal(null); await load() } catch (caught) { setError(friendlyError(caught, t('admin.saveError'))) }
  }
  async function toggleDepartment(department: Department) {
    if (!window.confirm(t(department.is_active ? 'admin.deactivateDepartmentConfirm' : 'admin.activateDepartmentConfirm'))) return
    try { await api(`/admin/departments/${department.id}`, { method: 'PATCH', body: JSON.stringify({ is_active: !department.is_active }) }); await load() } catch (caught) { setError(friendlyError(caught, t('admin.saveError'))) }
  }
  async function createTemplateVersion(event: FormEvent) {
    event.preventDefault()
    if (!versionTarget || !versionFile) return
    try {
      const layoutContract = JSON.parse(versionForm.layout_contract) as unknown
      if (!layoutContract || typeof layoutContract !== 'object' || Array.isArray(layoutContract)) throw new Error('invalid_contract')
      await api(`/document-templates/${versionTarget.id}/versions`, { method: 'POST', body: JSON.stringify({ language: versionForm.language, layout_contract: layoutContract, effective_from: versionForm.effective_from || null, effective_to: versionForm.effective_to || null, required_fields: versionForm.required_fields.split(/[\n,]/).map((item) => item.trim()).filter(Boolean), numbering_rule: versionForm.numbering_rule || null, department: versionForm.department || null, change_note: versionForm.change_note, ...(await filePayload(versionFile)) }) })
      setVersionTarget(null)
      setVersionFile(null)
      await load()
    } catch (caught) {
      setError(caught instanceof SyntaxError || (caught instanceof Error && caught.message === 'invalid_contract') ? t('admin.templateContractError') : friendlyError(caught, t('admin.saveError')))
    }
  }
  async function publishVersion(versionId: number) {
    if (!window.confirm(t('admin.publishConfirm'))) return
    try { await api(`/document-template-versions/${versionId}/publish`, { method: 'POST' }); await load() } catch (caught) { setError(friendlyError(caught, t('admin.saveError'))) }
  }
  async function previewImport() {
    try {
      const parsed = JSON.parse(importText) as unknown
      if (!Array.isArray(parsed)) throw new Error('array_required')
      setImportPreview(await api('/admin/import-preview', { method: 'POST', body: JSON.stringify({ records: parsed }) }))
    } catch (caught) { setError(caught instanceof SyntaxError || (caught instanceof Error && caught.message === 'array_required') ? t('admin.importJsonError') : friendlyError(caught, t('admin.importError'))) }
  }
  async function confirmImport() {
    if (!importPreview?.preview_token || !window.confirm(t('admin.importConfirm'))) return
    try { await api('/admin/import-confirm', { method: 'POST', body: JSON.stringify({ preview_token: importPreview.preview_token }) }); setImportPreview(null); setImportText(''); await load() } catch (caught) { setError(friendlyError(caught, t('admin.importError'))) }
  }

  return <><div className="admin-grid">{error && <div className="error wide">{error}</div>}<section className="panel"><div className="panel-title"><h3>{t('admin.categories')}</h3><button className="secondary compact" onClick={() => setModal('category')}><Plus size={15} />{t('admin.addCategory')}</button></div><div className="admin-list">{categories.map((category) => <div key={category.id}><span><b>{category[`name_${locale}` as 'name_bg'] || category.name_bg}</b><small>{category.code}</small></span><span>{t('admin.fieldsCount', { count: category.fields.length })}</span><button className="link" onClick={() => { setCategoryId(category.id); setModal('field') }}>{t('admin.addField')}</button></div>)}</div></section><section className="panel"><div className="panel-title"><h3>{t('admin.locations')}</h3><button className="secondary compact" onClick={() => setModal('location')}><Plus size={15} />{t('admin.addLocation')}</button></div><div className="admin-list">{locations.map((location) => <div key={location.id}><span><b>{location.name}</b><small>{location.description || t('common.noValue')}</small></span><span className="badge">{location.is_active ? t('admin.active') : t('admin.inactive')}</span><button className="link" onClick={() => void toggleLocation(location)}>{location.is_active ? t('admin.deactivate') : t('admin.activate')}</button></div>)}</div></section><section className="panel"><div className="panel-title"><h3>{t('admin.departments')}</h3><button className="secondary compact" onClick={() => setModal('department')}><Plus size={15} />{t('admin.addDepartment')}</button></div><div className="admin-list">{departments.map((department) => <div key={department.id}><span><b>{department[`name_${locale}` as 'name_bg'] || department.name_bg}</b><small>{department.code}</small></span><span className="badge">{department.is_active ? t('admin.active') : t('admin.inactive')}</span><button className="link" onClick={() => void toggleDepartment(department)}>{department.is_active ? t('admin.deactivate') : t('admin.activate')}</button></div>)}</div></section><section className="panel wide"><div className="panel-title"><h3>{t('admin.templates')}</h3><button className="secondary compact" onClick={() => setModal('template')}><Plus size={15} />{t('admin.addTemplate')}</button></div><p className="muted">{t('admin.templateHint')}</p><div className="template-grid">{templates.map((template) => <article key={template.id}><div className="panel-title"><div><b>{template.name_bg}</b><small>{translatedCode(t, template.document_type, DOCUMENT_KEYS)} · {template.code}</small></div><button className="secondary compact" onClick={() => { setVersionTarget(template); setVersionForm({ ...emptyVersionForm, language: locale }); setVersionFile(null) }}><Upload size={14} />{t('admin.addTemplateVersion')}</button></div><div>{template.versions.map((version) => <span className="template-version-row" key={version.id}><button className={version.is_published ? 'template-version published' : 'template-version'} disabled={version.is_published} onClick={() => void publishVersion(version.id)}>{t(`language.${version.language}` as TranslationKey)} v{version.version}</button><small>{[version.department, version.numbering_rule, version.change_note].filter(Boolean).join(' · ')}</small><DownloadButton path={version.download_endpoint} filename={version.source_filename || `${template.code}-v${version.version}`} /></span>)}</div></article>)}</div></section><section className="panel wide"><div className="panel-title"><h3>{t('admin.importTitle')}</h3><Upload /></div><p className="muted">{t('admin.importHint')}</p><textarea className="admin-import" value={importText} onChange={(event) => { setImportText(event.target.value); setImportPreview(null) }} placeholder={t('admin.importPlaceholder')} /><div className="actions"><button className="secondary" disabled={!importText.trim()} onClick={() => void previewImport()}>{t('admin.previewImport')}</button>{importPreview?.can_confirm && <button className="primary" onClick={() => void confirmImport()}>{t('admin.confirmImport')}</button>}</div>{importPreview && <div className={importPreview.can_confirm ? 'import-preview valid' : 'import-preview invalid'}><b>{importPreview.message}</b><p>{t('admin.validRecords', { count: importPreview.valid_records.length })}</p>{importPreview.errors.map((item) => <div key={`${item.row}-${item.message}`}>{t('admin.row', { number: item.row })}: {item.message}</div>)}</div>}</section></div>
    {modal === 'category' && <Modal title={t('admin.addCategory')} onClose={() => setModal(null)} wide><form className="form-grid" onSubmit={createCategory}><label>{t('admin.code')}<input required pattern="[A-Z0-9_-]+" value={categoryForm.code} onChange={(event) => setCategoryForm({ ...categoryForm, code: event.target.value.toUpperCase() })} /></label><label>{t('admin.categoryIcon')}<input value={categoryForm.icon} onChange={(event) => setCategoryForm({ ...categoryForm, icon: event.target.value })} /></label><label>{t('language.bg')}<input required value={categoryForm.name_bg} onChange={(event) => setCategoryForm({ ...categoryForm, name_bg: event.target.value })} /></label><label>{t('language.en')}<input value={categoryForm.name_en} onChange={(event) => setCategoryForm({ ...categoryForm, name_en: event.target.value })} /></label><label>{t('language.ru')}<input value={categoryForm.name_ru} onChange={(event) => setCategoryForm({ ...categoryForm, name_ru: event.target.value })} /></label><label className="wide">{t('catalog.description')}<textarea value={categoryForm.description} onChange={(event) => setCategoryForm({ ...categoryForm, description: event.target.value })} /></label><label>{t('admin.categoryDocumentTypes')}<textarea value={categoryForm.document_types_text} onChange={(event) => setCategoryForm({ ...categoryForm, document_types_text: event.target.value })} placeholder='["TECHNICAL"]' /></label><label>{t('admin.categoryStatuses')}<textarea value={categoryForm.status_codes_text} onChange={(event) => setCategoryForm({ ...categoryForm, status_codes_text: event.target.value })} placeholder='["READY", "REPAIR"]' /></label><label>{t('admin.categoryChecklists')}<textarea value={categoryForm.checklists_text} onChange={(event) => setCategoryForm({ ...categoryForm, checklists_text: event.target.value })} placeholder='[{"code":"INSPECTION"}]' /></label><label>{t('admin.validationRules')}<textarea value={categoryForm.validation_rules_text} onChange={(event) => setCategoryForm({ ...categoryForm, validation_rules_text: event.target.value })} placeholder='{"strict":true}' /></label><p className="muted wide">{t('admin.configurationJsonHint')}</p><div className="actions wide"><button type="button" className="secondary" onClick={() => setModal(null)}>{t('common.cancel')}</button><button className="primary">{t('common.save')}</button></div></form></Modal>}
    {modal === 'field' && <Modal title={t('admin.addField')} onClose={() => setModal(null)}><form className="form-grid" onSubmit={createField}><label>{t('admin.code')}<input required pattern="[A-Z0-9_-]+" value={fieldForm.code} onChange={(event) => setFieldForm({ ...fieldForm, code: event.target.value.toUpperCase() })} /></label><label>{t('admin.fieldType')}<select value={fieldForm.field_type} onChange={(event) => setFieldForm({ ...fieldForm, field_type: event.target.value })}>{['TEXT', 'INTEGER', 'DECIMAL', 'DATE', 'BOOLEAN', 'SELECT'].map((type) => <option key={type} value={type}>{t(`fieldType.${type.toLowerCase()}` as TranslationKey)}</option>)}</select></label><label>{t('language.bg')}<input required value={fieldForm.label_bg} onChange={(event) => setFieldForm({ ...fieldForm, label_bg: event.target.value })} /></label><label>{t('language.en')}<input value={fieldForm.label_en} onChange={(event) => setFieldForm({ ...fieldForm, label_en: event.target.value })} /></label><label>{t('language.ru')}<input value={fieldForm.label_ru} onChange={(event) => setFieldForm({ ...fieldForm, label_ru: event.target.value })} /></label><label>{t('admin.fieldUnit')}<input value={fieldForm.unit} onChange={(event) => setFieldForm({ ...fieldForm, unit: event.target.value })} /></label>{fieldForm.field_type === 'SELECT' && <label className="wide">{t('admin.fieldOptions')}<textarea required value={fieldForm.options_text} onChange={(event) => setFieldForm({ ...fieldForm, options_text: event.target.value })} placeholder={t('admin.fieldOptionsHint')} /></label>}<label className="wide">{t('admin.validationRules')}<textarea value={fieldForm.validation_rules_text} onChange={(event) => setFieldForm({ ...fieldForm, validation_rules_text: event.target.value })} placeholder='{"min":0,"max":1000}' /></label><label className="check-label"><input type="checkbox" checked={fieldForm.is_required} onChange={(event) => setFieldForm({ ...fieldForm, is_required: event.target.checked })} />{t('admin.requiredField')}</label><div className="actions wide"><button type="button" className="secondary" onClick={() => setModal(null)}>{t('common.cancel')}</button><button className="primary">{t('common.save')}</button></div></form></Modal>}
    {modal === 'template' && <Modal title={t('admin.addTemplate')} onClose={() => setModal(null)}><form className="form-grid" onSubmit={createTemplate}><label>{t('admin.code')}<input required pattern="[A-Z0-9_-]+" value={templateForm.code} onChange={(event) => setTemplateForm({ ...templateForm, code: event.target.value.toUpperCase() })} /></label><label>{t('admin.documentType')}<input required value={templateForm.document_type} onChange={(event) => setTemplateForm({ ...templateForm, document_type: event.target.value.toUpperCase() })} /></label><label>{t('language.bg')}<input required value={templateForm.name_bg} onChange={(event) => setTemplateForm({ ...templateForm, name_bg: event.target.value })} /></label><label>{t('language.en')}<input value={templateForm.name_en} onChange={(event) => setTemplateForm({ ...templateForm, name_en: event.target.value })} /></label><label>{t('language.ru')}<input value={templateForm.name_ru} onChange={(event) => setTemplateForm({ ...templateForm, name_ru: event.target.value })} /></label><div className="actions wide"><button type="button" className="secondary" onClick={() => setModal(null)}>{t('common.cancel')}</button><button className="primary">{t('common.save')}</button></div></form></Modal>}
    {modal === 'location' && <Modal title={t('admin.addLocation')} onClose={() => setModal(null)}><form className="form-grid" onSubmit={createLocation}><label className="wide">{t('admin.locationName')}<input required value={locationForm.name} onChange={(event) => setLocationForm({ ...locationForm, name: event.target.value })} /></label><label className="wide">{t('catalog.description')}<textarea value={locationForm.description} onChange={(event) => setLocationForm({ ...locationForm, description: event.target.value })} /></label><div className="actions wide"><button type="button" className="secondary" onClick={() => setModal(null)}>{t('common.cancel')}</button><button className="primary">{t('common.save')}</button></div></form></Modal>}
    {modal === 'department' && <Modal title={t('admin.addDepartment')} onClose={() => setModal(null)}><form className="form-grid" onSubmit={createDepartment}><label>{t('admin.code')}<input required pattern="[A-Z0-9_-]+" value={departmentForm.code} onChange={(event) => setDepartmentForm({ ...departmentForm, code: event.target.value.toUpperCase() })} /></label><label>{t('language.bg')}<input required value={departmentForm.name_bg} onChange={(event) => setDepartmentForm({ ...departmentForm, name_bg: event.target.value })} /></label><label>{t('language.en')}<input value={departmentForm.name_en} onChange={(event) => setDepartmentForm({ ...departmentForm, name_en: event.target.value })} /></label><label>{t('language.ru')}<input value={departmentForm.name_ru} onChange={(event) => setDepartmentForm({ ...departmentForm, name_ru: event.target.value })} /></label><label className="wide">{t('catalog.description')}<textarea value={departmentForm.description} onChange={(event) => setDepartmentForm({ ...departmentForm, description: event.target.value })} /></label><div className="actions wide"><button type="button" className="secondary" onClick={() => setModal(null)}>{t('common.cancel')}</button><button className="primary">{t('common.save')}</button></div></form></Modal>}
    {versionTarget && <Modal title={t('admin.addTemplateVersion')} onClose={() => setVersionTarget(null)} wide><form className="form-grid" onSubmit={createTemplateVersion}><p className="wide"><b>{versionTarget.name_bg}</b><br /><small>{versionTarget.code}</small></p><label>{t('admin.templateLanguage')}<select value={versionForm.language} onChange={(event) => setVersionForm({ ...versionForm, language: event.target.value as Locale })}><option value="bg">{t('language.bg')}</option><option value="en">{t('language.en')}</option><option value="ru">{t('language.ru')}</option></select></label><label>{t('admin.templateDepartment')}<input value={versionForm.department} onChange={(event) => setVersionForm({ ...versionForm, department: event.target.value })} /></label><label>{t('admin.templateEffectiveFrom')}<input type="datetime-local" value={versionForm.effective_from} onChange={(event) => setVersionForm({ ...versionForm, effective_from: event.target.value })} /></label><label>{t('admin.templateEffectiveTo')}<input type="datetime-local" value={versionForm.effective_to} onChange={(event) => setVersionForm({ ...versionForm, effective_to: event.target.value })} /></label><label className="wide">{t('admin.templateSourceFile')}<input required type="file" accept=".docx,application/pdf" onChange={(event) => setVersionFile(event.target.files?.[0] || null)} /></label><label>{t('admin.templateNumberingRule')}<input value={versionForm.numbering_rule} onChange={(event) => setVersionForm({ ...versionForm, numbering_rule: event.target.value })} /></label><label>{t('admin.templateRequiredFields')}<textarea value={versionForm.required_fields} onChange={(event) => setVersionForm({ ...versionForm, required_fields: event.target.value })} /></label><label className="wide">{t('admin.templateChangeNote')}<textarea required value={versionForm.change_note} onChange={(event) => setVersionForm({ ...versionForm, change_note: event.target.value })} /></label><label className="wide">{t('admin.templateContract')}<textarea required rows={8} value={versionForm.layout_contract} onChange={(event) => setVersionForm({ ...versionForm, layout_contract: event.target.value })} /></label><p className="muted wide">{t('admin.templatePublishHint')}</p><div className="actions wide"><button type="button" className="secondary" onClick={() => setVersionTarget(null)}>{t('common.cancel')}</button><button className="primary" disabled={!versionFile || !versionForm.change_note.trim()}>{t('admin.saveDraftVersion')}</button></div></form></Modal>}
  </>
}
