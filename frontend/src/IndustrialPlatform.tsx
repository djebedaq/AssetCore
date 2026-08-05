import { type FormEvent, useEffect, useMemo, useRef, useState } from 'react'
import {
  Archive,
  BookOpen,
  CheckCircle2,
  ChevronRight,
  Download,
  FilePlus2,
  FileText,
  ImagePlus,
  Maximize2,
  PackageCheck,
  Plus,
  Search,
  ShieldCheck,
  Upload,
  Wrench,
  X,
  ZoomIn,
  ZoomOut,
} from 'lucide-react'
import { ApiError, api, createApiObjectUrl, downloadApiFile } from './api'
import AuthenticatedImage from './AuthenticatedImage'
import { statusText, useI18n, type TranslationKey } from './i18n'
import type { Locale } from './locale'
import { hasPermission } from './permissions'
import type {
  AssetCategory,
  CatalogPartImage,
  CatalogPartEnhanced,
  Department,
  GlobalSearchResults,
  Location,
  Machine,
  MachinePassport,
  MultiPartRequest,
  PartHotspot,
  RepairCase,
  RepairKit,
  StoredAttachment,
  TechnicalLibraryDocument,
} from './types'

function friendlyError(error: unknown, fallback: string): string {
  if (error instanceof ApiError && error.data.message) return error.data.message
  return fallback
}

function optionalJson(text: string, shape: 'object' | 'array'): Record<string, unknown> | unknown[] | null {
  if (!text.trim()) return null
  const value = JSON.parse(text) as unknown
  const valid = shape === 'array'
    ? Array.isArray(value)
    : Boolean(value) && typeof value === 'object' && !Array.isArray(value)
  if (!valid) throw new Error(`invalid_${shape}`)
  return value as Record<string, unknown> | unknown[]
}

const EVENT_KEYS: Record<string, TranslationKey> = {
  MACHINE_CREATED: 'event.machineCreated', MACHINE_UPDATED: 'event.machineUpdated',
  CUSTOM_FIELDS_UPDATED: 'event.customFieldsUpdated', ATTACHMENT_ADDED: 'event.attachmentAdded',
  TRANSFER_ISSUED: 'event.transferIssued', TRANSFER_RETURNED: 'event.transferReturned',
  REPAIR_ACCEPTED: 'event.repairAccepted', REPAIR_STATUS_CHANGED: 'event.repairStatusChanged',
  IMPORTED: 'event.imported', ACCEPTED: 'event.accepted', INSPECTION: 'event.inspection',
  CLEANING: 'event.cleaning', DIAGNOSIS: 'event.diagnosis', APPROVAL: 'event.approval',
  PARTS: 'event.parts', REPAIR_ACTION: 'event.repairAction', TEST: 'event.test',
  STATUS_CHANGE: 'event.statusChange', COMPLETED: 'event.completed', NOTE: 'event.note',
}

const DOCUMENT_KEYS: Record<string, TranslationKey> = {
  TRANSFER_ISSUE: 'documentType.transferIssue', TRANSFER_RETURN: 'documentType.transferReturn',
  REPAIR_PROTOCOL: 'documentType.repairProtocol', PART_REQUEST: 'documentType.partRequest',
  DAILY_REPORT: 'documentType.dailyReport', QR_LABEL: 'documentType.qrLabel',
  TECHNICAL: 'documentType.technical', OTHER: 'documentType.other',
}

function translatedCode(
  t: (key: TranslationKey, values?: Record<string, string | number>) => string,
  value: string,
  keys: Record<string, TranslationKey>,
): string {
  return keys[value] ? t(keys[value]) : value
}

function Modal({ title, onClose, children, wide = false }: {
  title: string; onClose: () => void; children: React.ReactNode; wide?: boolean
}) {
  const { t } = useI18n()
  return (
    <div className="modal-bg">
      <div className={`modal industrial-modal ${wide ? 'industrial-modal-wide' : ''}`} role="dialog" aria-modal="true" aria-label={title}>
        <div className="modal-head"><h3>{title}</h3><button onClick={onClose} aria-label={t('common.close')}><X /></button></div>
        {children}
      </div>
    </div>
  )
}

async function filePayload(file: File): Promise<{ filename: string; media_type: string; content_base64: string }> {
  const dataUrl = await new Promise<string>((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => resolve(String(reader.result))
    reader.onerror = () => reject(reader.error)
    reader.readAsDataURL(file)
  })
  return {
    filename: file.name,
    media_type: file.type || 'application/octet-stream',
    content_base64: dataUrl.split(',', 2)[1] || '',
  }
}

function DownloadButton({ path, filename, label }: { path: string; filename: string; label?: string }) {
  const { t } = useI18n()
  const [failed, setFailed] = useState(false)
  return (
    <span>
      <button className="secondary compact" onClick={() => downloadApiFile(path, filename).catch(() => setFailed(true))}>
        <Download size={15} />{label || t('common.download')}
      </button>
      {failed && <small className="inline-error">{t('errors.generic')}</small>}
    </span>
  )
}

function DocumentButtons({ path, filename, format, label }: { path: string; filename: string; format: string; label?: string }) {
  const { t } = useI18n()
  const [previewUrl, setPreviewUrl] = useState('')
  const [failed, setFailed] = useState(false)
  const [loading, setLoading] = useState(false)
  useEffect(() => () => { if (previewUrl) URL.revokeObjectURL(previewUrl) }, [previewUrl])
  async function preview() {
    setLoading(true)
    setFailed(false)
    try {
      const result = await createApiObjectUrl(path)
      setPreviewUrl(result.url)
    } catch {
      setFailed(true)
    } finally {
      setLoading(false)
    }
  }
  function closePreview() {
    URL.revokeObjectURL(previewUrl)
    setPreviewUrl('')
  }
  return <span className="document-actions-inline"><DownloadButton path={path} filename={filename} label={label || format.toUpperCase()} />{format.toLowerCase() === 'pdf' && <button className="secondary compact" disabled={loading} onClick={() => void preview()}><Search size={15} />{t('common.preview')}</button>}{failed && <small className="inline-error">{t('catalog.documentPreviewError')}</small>}{previewUrl && <Modal title={filename} onClose={closePreview} wide><object className="generated-document-preview" data={previewUrl} type="application/pdf"><p>{t('catalog.previewUnsupported')}</p></object></Modal>}</span>
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

function AttachmentList({ items }: { items: StoredAttachment[] }) {
  const { date, t } = useI18n()
  return (
    <div className="document-list">
      {items.map((item) => <div key={item.id}><span><b>{item.filename}</b><small>{date(item.created_at)} · SHA-256 {item.sha256.slice(0, 12)}…</small></span><DownloadButton path={item.download_endpoint} filename={item.filename} /></div>)}
      {!items.length && <div className="empty-state">{t('passport.noAttachments')}</div>}
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
            <div><dt>{t('passport.lastMovement')}</dt><dd>{passport.current_state.last_movement ? `${translatedCode(t, passport.current_state.last_movement.event_type, EVENT_KEYS)} · ${date(passport.current_state.last_movement.created_at)}` : t('common.noValue')}</dd></div>
            <div><dt>{t('passport.lastInspection')}</dt><dd>{passport.current_state.last_inspection ? date(passport.current_state.last_inspection.completed_at) : t('common.noValue')}</dd></div>
            <div><dt>{t('passport.lastTest')}</dt><dd>{passport.current_state.last_test ? `${passport.current_state.last_test.passed ? t('common.yes') : t('common.no')} ${passport.current_state.last_test.completed_at ? `· ${date(passport.current_state.last_test.completed_at)}` : ''}` : t('common.noValue')}</dd></div>
          </dl><div className="summary-chips">{passport.current_state.allowed_actions.issue && <span>{t('bulk.issue')}</span>}{passport.current_state.allowed_actions.return && <span>{t('bulk.return')}</span>}{passport.current_state.allowed_actions.repair && <span>{t('nav.repairs')}</span>}{passport.current_state.allowed_actions.edit && <span>{t('common.edit')}</span>}</div>{passport.current_state.active_transfer && <div className="record-detail"><b>{passport.current_state.active_transfer.protocol_number}</b><span>{[passport.current_state.active_transfer.company_unit, passport.current_state.active_transfer.department, passport.current_state.active_transfer.vessel, passport.current_state.active_transfer.dock, passport.current_state.active_transfer.pier, passport.current_state.active_transfer.work_area, passport.current_state.active_transfer.location_text].filter(Boolean).join(' · ')}</span><small>{passport.current_state.active_transfer.issued_at ? date(passport.current_state.active_transfer.issued_at) : t('common.noValue')}</small></div>}</section>
          <section><h4>{t('passport.activeLinks')}</h4><div className="summary-chips"><span>{t('passport.repairsCount', { count: passport.repairs.length })}</span><span>{t('passport.transfersCount', { count: passport.transfers.length })}</span><span>{t('passport.requestsCount', { count: passport.part_requests.length })}</span><span>{t('passport.documentsCount', { count: passport.generated_documents.length + passport.technical_documents.length })}</span></div></section>
        </div>}
        {tab === 'history' && <div className="timeline">{passport.history.map((event) => <div key={event.id}><i /><span><b>{translatedCode(t, event.event_type, EVENT_KEYS)}</b><small>{date(event.created_at)} · {event.reference || t('common.system')}</small>{(event.previous_status || event.new_status) && <em>{event.previous_status ? statusText(t, event.previous_status) : ''} → {event.new_status ? statusText(t, event.new_status) : ''}</em>}</span></div>)}{!passport.history.length && <div className="empty-state">{t('passport.noHistory')}</div>}</div>}
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

const repairTransitions: Record<string, string[]> = {
  ACCEPTED: ['DIAGNOSIS'], DIAGNOSIS: ['WAITING_APPROVAL', 'WAITING_PARTS', 'REPAIRING'],
  WAITING_APPROVAL: ['WAITING_PARTS', 'REPAIRING'], WAITING_PARTS: ['REPAIRING'],
  REPAIRING: ['WAITING_PARTS', 'TESTING'], TESTING: ['REPAIRING', 'COMPLETED'], COMPLETED: [],
}

function RepairCreateModal({ machines, onClose, onSaved }: { machines: Machine[]; onClose: () => void; onSaved: () => void }) {
  const { t } = useI18n()
  const eligible = machines.filter((machine) => !['ISSUED', 'IN_USE'].includes(machine.status))
  const [form, setForm] = useState({ machine_id: eligible[0]?.id || 0, reported_problem: '', reported_by_name: '', symptoms: '', required_work: '', condition_before: '', repair_type: '', severity: '', cleaning_required: false, test_required: true })
  const [error, setError] = useState('')
  async function submit(event: FormEvent) {
    event.preventDefault()
    try {
      await api('/repair-cases', { method: 'POST', body: JSON.stringify(form) })
      onSaved()
    } catch (caught) { setError(friendlyError(caught, t('repairs.saveError'))) }
  }
  return <Modal title={t('repairs.acceptTitle')} onClose={onClose}><form className="form-grid" onSubmit={submit}>
    <label>{t('repairs.machine')}<select value={form.machine_id} onChange={(event) => setForm({ ...form, machine_id: Number(event.target.value) })}>{eligible.map((machine) => <option key={machine.id} value={machine.id}>{machine.name} · {statusText(t, machine.status)}</option>)}</select></label>
    <label>{t('repairCase.type')}<input value={form.repair_type} onChange={(event) => setForm({ ...form, repair_type: event.target.value })} /></label>
    <label>{t('repairCase.severity')}<input value={form.severity} onChange={(event) => setForm({ ...form, severity: event.target.value })} /></label>
    <label className="check-label"><input type="checkbox" checked={form.cleaning_required} onChange={(event) => setForm({ ...form, cleaning_required: event.target.checked })} />{t('repairCase.cleaningRequired')}</label>
    <label>{t('repairCase.reportedBy')}<input value={form.reported_by_name} onChange={(event) => setForm({ ...form, reported_by_name: event.target.value })} /></label>
    <label className="wide">{t('repairs.reportedProblem')}<textarea required value={form.reported_problem} onChange={(event) => setForm({ ...form, reported_problem: event.target.value })} /></label>
    <label className="wide">{t('repairCase.symptoms')}<textarea value={form.symptoms} onChange={(event) => setForm({ ...form, symptoms: event.target.value })} /></label>
    <label className="wide">{t('repairCase.requiredWork')}<textarea value={form.required_work} onChange={(event) => setForm({ ...form, required_work: event.target.value })} /></label>
    <label className="wide">{t('repairCase.conditionBefore')}<textarea value={form.condition_before} onChange={(event) => setForm({ ...form, condition_before: event.target.value })} /></label>
    {error && <div className="error wide">{error}</div>}<div className="actions wide"><button type="button" className="secondary" onClick={onClose}>{t('common.cancel')}</button><button className="primary" disabled={!eligible.length}>{t('repairCase.accept')}</button></div>
  </form></Modal>
}

function RepairWorkspace({ repairId, onClose, onChanged }: { repairId: number; onClose: () => void; onChanged: () => void }) {
  const { date, locale, t } = useI18n()
  const [repair, setRepair] = useState<RepairCase | null>(null)
  const [form, setForm] = useState({ diagnosis: '', required_work: '', removed_parts_text: '', work_performed: '', result: '', condition_after: '', test_method: '', test_pressure_bar: '', leaks_detected: '', electrical_test_result: '', functional_test_result: '', test_details: '', test_passed: '' })
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [catalog, setCatalog] = useState<CatalogPartEnhanced[]>([])
  const [partDraft, setPartDraft] = useState({ catalog_part_id: '', quantity: 1 })
  const [participantDraft, setParticipantDraft] = useState({ full_name: '', job_title: '', contribution: '' })
  const fileRef = useRef<HTMLInputElement>(null)
  const load = () => Promise.all([api<RepairCase>(`/repair-cases/${repairId}`), api<CatalogPartEnhanced[]>('/catalog/parts')]).then(([data, partItems]) => { setRepair(data); setCatalog(partItems.filter((item) => item.is_verified)); setForm({ diagnosis: data.diagnosis || '', required_work: data.required_work || '', removed_parts_text: data.removed_parts_text || '', work_performed: data.work_performed || '', result: data.result || '', condition_after: data.condition_after || '', test_method: data.test_method || '', test_pressure_bar: data.test_pressure_bar != null ? String(data.test_pressure_bar) : '', leaks_detected: data.leaks_detected == null ? '' : data.leaks_detected ? 'yes' : 'no', electrical_test_result: data.electrical_test_result || '', functional_test_result: data.functional_test_result || '', test_details: data.test_details || '', test_passed: data.test_passed == null ? '' : data.test_passed ? 'yes' : 'no' }); setError('') }).catch((caught) => setError(friendlyError(caught, t('repairCase.loadError'))))
  useEffect(() => { void load() }, [repairId])
  async function transition(nextStatus: string) {
    if (!repair) return
    if (nextStatus === 'COMPLETED' && !window.confirm(t('repairCase.completeConfirm'))) return
    setBusy(true)
    const payload: Record<string, unknown> = { ...form, test_pressure_bar: form.test_pressure_bar ? Number(form.test_pressure_bar) : null, leaks_detected: form.leaks_detected ? form.leaks_detected === 'yes' : null, test_passed: form.test_passed ? form.test_passed === 'yes' : null, status: nextStatus }
    if (nextStatus === 'DIAGNOSIS') payload.inspection_complete = true
    if (nextStatus === 'TESTING' && repair.cleaning_required) payload.cleaning_complete = true
    try {
      const updated = await api<RepairCase>(`/repair-cases/${repair.id}`, { method: 'PATCH', body: JSON.stringify(payload) })
      if (updated.document_generation_warning) setError(t('repairCase.documentWarning', { message: updated.document_generation_warning.message }))
      await load(); onChanged()
    } catch (caught) { setError(friendlyError(caught, t('repairCase.transitionError'))) } finally { setBusy(false) }
  }
  async function upload(file?: File) {
    if (!file || !repair) return
    try { await api(`/repair-cases/${repair.id}/attachments`, { method: 'POST', body: JSON.stringify({ ...(await filePayload(file)), stage: repair.status, description: file.name }) }); await load() } catch (caught) { setError(friendlyError(caught, t('passport.uploadError'))) }
  }
  async function generate() {
    if (!repair) return
    try { await api(`/repair-cases/${repair.id}/documents`, { method: 'POST' }); await load(); onChanged() } catch (caught) { setError(friendlyError(caught, t('repairCase.documentError'))) }
  }
  async function addPart(event: FormEvent) {
    event.preventDefault()
    if (!repair || !partDraft.catalog_part_id) return
    const part = catalog.find((item) => item.id === Number(partDraft.catalog_part_id))
    if (!part) return
    try {
      await api(`/repair-cases/${repair.id}/parts`, { method: 'POST', body: JSON.stringify({ catalog_part_id: part.id, part_number: part.part_number, description: part.description, quantity: partDraft.quantity, unit: part.unit, source: part.source_document }) })
      setPartDraft({ catalog_part_id: '', quantity: 1 })
      await load()
      onChanged()
    } catch (caught) { setError(friendlyError(caught, t('repairCase.partError'))) }
  }
  async function addParticipant(event: FormEvent) {
    event.preventDefault()
    if (!repair || !participantDraft.full_name.trim()) return
    try {
      await api(`/repair-cases/${repair.id}/participants`, { method: 'POST', body: JSON.stringify(participantDraft) })
      setParticipantDraft({ full_name: '', job_title: '', contribution: '' })
      await load(); onChanged()
    } catch (caught) { setError(friendlyError(caught, t('repairCase.participantError'))) }
  }
  async function removeParticipant(id: number) {
    if (!repair) return
    try { await api(`/repair-cases/${repair.id}/participants/${id}`, { method: 'DELETE' }); await load(); onChanged() }
    catch (caught) { setError(friendlyError(caught, t('repairCase.participantError'))) }
  }
  return <Modal title={repair?.repair_reference || t('common.loading')} onClose={onClose} wide>{error && <div className="error">{error}</div>}{!repair ? <div className="loading">{t('common.loading')}</div> : <>
    <div className="workflow-strip">{['ACCEPTED', 'DIAGNOSIS', 'WAITING_APPROVAL', 'WAITING_PARTS', 'REPAIRING', 'TESTING', 'COMPLETED'].map((status) => <span className={repair.status === status ? 'active' : ''} key={status}>{statusText(t, status, 'repair')}</span>)}</div>
    <div className="repair-workspace-grid"><section><h4>{repair.machine_name} · №{repair.machine_number}</h4><p><b>{t('repairs.problem')}</b> {repair.reported_problem}</p><p><b>{t('repairCase.conditionBefore')}</b> {repair.condition_before || t('common.noValue')}</p>
      <div className="form-grid"><label className="wide">{t('repairs.diagnosisField')}<textarea value={form.diagnosis} onChange={(event) => setForm({ ...form, diagnosis: event.target.value })} /></label><label className="wide">{t('repairCase.requiredWork')}<textarea value={form.required_work} onChange={(event) => setForm({ ...form, required_work: event.target.value })} /></label><label className="wide">{t('repairCase.removedParts')}<textarea value={form.removed_parts_text} onChange={(event) => setForm({ ...form, removed_parts_text: event.target.value })} /></label><label className="wide">{t('repairs.workField')}<textarea value={form.work_performed} onChange={(event) => setForm({ ...form, work_performed: event.target.value })} /></label><label>{t('repairCase.testPassed')}<select value={form.test_passed} onChange={(event) => setForm({ ...form, test_passed: event.target.value })}><option value="">{t('common.notSpecified')}</option><option value="no">{t('common.no')}</option><option value="yes">{t('common.yes')}</option></select></label><label>{t('repairCase.testMethod')}<input value={form.test_method} onChange={(event) => setForm({ ...form, test_method: event.target.value })} /></label><label>{t('repairCase.testPressure')}<input type="number" min="0" max="10000" value={form.test_pressure_bar} onChange={(event) => setForm({ ...form, test_pressure_bar: event.target.value })} /></label><label>{t('repairCase.leaksDetected')}<select value={form.leaks_detected} onChange={(event) => setForm({ ...form, leaks_detected: event.target.value })}><option value="">{t('common.notSpecified')}</option><option value="no">{t('common.no')}</option><option value="yes">{t('common.yes')}</option></select></label><label>{t('repairCase.electricalTest')}<input value={form.electrical_test_result} onChange={(event) => setForm({ ...form, electrical_test_result: event.target.value })} /></label><label>{t('repairCase.functionalTest')}<input value={form.functional_test_result} onChange={(event) => setForm({ ...form, functional_test_result: event.target.value })} /></label><label className="wide">{t('repairs.testResult')}<textarea value={form.test_details} onChange={(event) => setForm({ ...form, test_details: event.target.value })} /></label><label className="wide">{t('repairCase.conditionAfter')}<textarea value={form.condition_after} onChange={(event) => setForm({ ...form, condition_after: event.target.value })} /></label><label className="wide">{t('repairCase.result')}<textarea value={form.result} onChange={(event) => setForm({ ...form, result: event.target.value })} /></label></div>
      <section className="repair-parts"><h4>{t('repairCase.partsUsed')}</h4><div className="request-line-list">{repair.parts_used.map((part) => <div key={part.id}><span><b>{part.part_number || t('common.noValue')}</b><small>{part.description}{part.source ? ` · ${part.source}` : ''}</small></span><em>{part.quantity} {part.unit}</em></div>)}{!repair.parts_used.length && <div className="empty-state">{t('repairCase.noParts')}</div>}</div>{hasPermission('repairs.edit') && repair.status !== 'COMPLETED' && <form className="repair-part-form" onSubmit={addPart}><label>{t('repairCase.catalogPart')}<select required value={partDraft.catalog_part_id} onChange={(event) => setPartDraft({ ...partDraft, catalog_part_id: event.target.value })}><option value="">{t('common.notSpecified')}</option>{catalog.map((part) => <option value={part.id} key={part.id}>{part.part_number} · {part.description}</option>)}</select></label><label>{t('common.quantity')}<input required min="0.01" step="0.01" type="number" value={partDraft.quantity} onChange={(event) => setPartDraft({ ...partDraft, quantity: Number(event.target.value) })} /></label><button className="secondary" disabled={!partDraft.catalog_part_id || partDraft.quantity <= 0}><Plus size={15} />{t('repairCase.addPart')}</button></form>}</section>
      <section className="repair-parts"><h4>{t('repairCase.participants')}</h4><div className="request-line-list">{repair.participants.map((participant) => <div key={participant.id}><span><b>{participant.full_name}</b><small>{[participant.job_title, participant.contribution].filter(Boolean).join(' · ')}</small></span>{hasPermission('repairs.edit') && repair.status !== 'COMPLETED' && <button className="link" type="button" onClick={() => void removeParticipant(participant.id)}>{t('common.remove')}</button>}</div>)}{!repair.participants.length && <div className="empty-state">{t('repairCase.noParticipants')}</div>}</div>{hasPermission('repairs.edit') && repair.status !== 'COMPLETED' && <form className="repair-part-form repair-participant-form" onSubmit={addParticipant}><label>{t('repairCase.participantName')}<input required value={participantDraft.full_name} onChange={(event) => setParticipantDraft({ ...participantDraft, full_name: event.target.value })} /></label><label>{t('repairCase.participantJobTitle')}<input value={participantDraft.job_title} onChange={(event) => setParticipantDraft({ ...participantDraft, job_title: event.target.value })} /></label><label>{t('repairCase.participantContribution')}<input value={participantDraft.contribution} onChange={(event) => setParticipantDraft({ ...participantDraft, contribution: event.target.value })} /></label><button className="secondary" disabled={!participantDraft.full_name.trim()}><Plus size={15} />{t('repairCase.addParticipant')}</button></form>}</section>
      {hasPermission('repairs.edit') && <div className="actions workflow-actions">{repairTransitions[repair.status]?.map((next) => <button disabled={busy} className={next === 'COMPLETED' ? 'primary' : 'secondary'} key={next} onClick={() => void transition(next)}>{statusText(t, next, 'repair')}<ChevronRight size={15} /></button>)}</div>}
    </section><aside><h4>{t('repairCase.timeline')}</h4><div className="timeline compact-timeline">{repair.events.map((event) => <div key={event.id}><i /><span><b>{translatedCode(t, event.event_type, EVENT_KEYS)}</b>{event.description && ['NOTE', 'REPAIR_ACTION', 'DIAGNOSIS', 'TEST', 'PARTS'].includes(event.event_type) && <em>{event.description}</em>}<small>{date(event.created_at)} · {statusText(t, event.status_after || repair.status, 'repair')}</small></span></div>)}</div></aside></div>
    <div className="toolbar"><div><h4>{t('passport.attachments')}</h4></div>{hasPermission('repairs.edit') && <><input ref={fileRef} hidden type="file" accept="image/png,image/jpeg,image/webp,application/pdf,.docx" onChange={(event) => void upload(event.target.files?.[0])} /><button className="secondary" onClick={() => fileRef.current?.click()}><Upload size={16} />{t('passport.addFile')}</button>{repair.status === 'COMPLETED' && <button className="primary" onClick={() => void generate()}><FileText size={16} />{t('repairCase.generateProtocolBg')}</button>}</>}</div><AttachmentList items={repair.attachments} />
    <div className="document-list">{repair.generated_documents.map((document) => <div key={document.id}><span><b>{document.document_number}</b><small>{translatedCode(t, document.document_type, DOCUMENT_KEYS)} · {date(document.created_at)}</small></span><DocumentButtons path={document.download_endpoint} filename={document.filename} format={document.format} /></div>)}</div>
  </>}</Modal>
}

export function IndustrialRepairs() {
  const { date, t } = useI18n()
  const [items, setItems] = useState<RepairCase[]>([])
  const [machines, setMachines] = useState<Machine[]>([])
  const [selected, setSelected] = useState<number | null>(null)
  const [create, setCreate] = useState(false)
  const [error, setError] = useState('')
  const load = () => Promise.all([api<RepairCase[]>('/repair-cases'), api<Machine[]>('/machines')]).then(([repairs, machineItems]) => { setItems(repairs); setMachines(machineItems); setError('') }).catch((caught) => setError(friendlyError(caught, t('repairCase.loadError'))))
  useEffect(() => { void load() }, [])
  return <><div className="toolbar"><div><h3>{t('repairs.title')}</h3><p className="muted">{t('repairCase.workflowHint')}</p></div>{hasPermission('repairs.create') && <button className="primary" onClick={() => setCreate(true)}><Plus size={18} />{t('repairs.new')}</button>}</div>{error && <div className="error">{error}</div>}<div className="cards-list">{items.map((repair) => <button className="repair-card repair-card-button" key={repair.id} onClick={() => setSelected(repair.id)}><div><span className="badge">{statusText(t, repair.status, 'repair')}</span><h3>{repair.machine_name} · {repair.repair_reference}</h3><p><b>{t('repairs.problem')}</b> {repair.reported_problem}</p><div className="workflow-checks"><span className={repair.inspection_completed_at ? 'done' : ''}>{t('repairCase.inspection')}</span><span className={repair.cleaning_completed_at || !repair.cleaning_required ? 'done' : ''}>{t('status.cleaning')}</span><span className={repair.test_passed ? 'done' : ''}>{t('status.testing')}</span></div></div><div className="repair-side"><small>{date(repair.opened_at)}</small><ChevronRight /></div></button>)}{!items.length && <div className="empty-state">{t('repairs.empty')}</div>}</div>{create && <RepairCreateModal machines={machines} onClose={() => setCreate(false)} onSaved={() => { setCreate(false); void load() }} />}{selected && <RepairWorkspace repairId={selected} onClose={() => setSelected(null)} onChanged={() => void load()} />}</>
}

type RequestDraftLine = { catalog_part_id?: number; position: string; part_number: string; description: string; quantity: number; unit: string; source_document?: string; source_page?: number; is_unknown_part?: boolean; assembly?: string; note?: string }

function PartRequestCreateModal({ machines, repairs, catalog, onClose, onSaved }: { machines: Machine[]; repairs: RepairCase[]; catalog: CatalogPartEnhanced[]; onClose: () => void; onSaved: () => void }) {
  const { locale, t } = useI18n()
  const [machineId, setMachineId] = useState<number | ''>('')
  const [repairId, setRepairId] = useState<number | ''>('')
  const [priority, setPriority] = useState('NORMAL')
  const [department, setDepartment] = useState('')
  const [reason, setReason] = useState('')
  const [lines, setLines] = useState<RequestDraftLine[]>([{ position: '', part_number: '', description: '', quantity: 1, unit: '' }])
  const [step, setStep] = useState<'edit' | 'confirm'>('edit')
  const [error, setError] = useState('')
  const updateLine = (index: number, changes: Partial<RequestDraftLine>) => setLines((current) => current.map((line, itemIndex) => itemIndex === index ? { ...line, ...changes } : line))
  const chooseCatalog = (index: number, id: number) => {
    const part = catalog.find((item) => item.id === id)
    if (!part) return
    updateLine(index, { catalog_part_id: part.id, position: part.position || '', part_number: part.part_number, description: part.description, unit: part.unit || '', source_document: part.source_document || undefined, source_page: part.source_page || undefined })
  }
  async function submit() {
    try {
      const result = await api<MultiPartRequest>('/part-requests/multi', { method: 'POST', body: JSON.stringify({ machine_id: machineId || null, repair_id: repairId || null, priority, language: locale, department: department || null, reason: reason || null, lines }) })
      await api(`/part-requests/${result.id}/submit`, { method: 'POST' })
      onSaved()
    } catch (caught) { setError(friendlyError(caught, t('requests.saveError'))) }
  }
  const invalid = lines.some((line) => !line.description.trim() || line.quantity <= 0)
  return <Modal title={t('requests.new')} onClose={onClose} wide>{error && <div className="error">{error}</div>}{step === 'edit' ? <>
    <div className="form-grid"><label>{t('parts.machine')}<select value={machineId} onChange={(event) => { setMachineId(event.target.value ? Number(event.target.value) : ''); setRepairId('') }}><option value="">{t('parts.general')}</option>{machines.map((machine) => <option key={machine.id} value={machine.id}>{machine.name}</option>)}</select></label><label>{t('requests.linkedRepair')}<select value={repairId} onChange={(event) => { const value = event.target.value ? Number(event.target.value) : ''; setRepairId(value); if (value) { const repair = repairs.find((item) => item.id === value); if (repair) setMachineId(repair.machine_id) } }}><option value="">{t('common.notSpecified')}</option>{repairs.filter((repair) => !machineId || repair.machine_id === machineId).map((repair) => <option value={repair.id} key={repair.id}>{repair.repair_reference} · №{repair.machine_number}</option>)}</select></label><label>{t('parts.priority')}<select value={priority} onChange={(event) => setPriority(event.target.value)}>{['LOW', 'NORMAL', 'URGENT'].map((value) => <option value={value} key={value}>{statusText(t, value, 'part')}</option>)}</select></label><label>{t('requests.department')}<input value={department} onChange={(event) => setDepartment(event.target.value)} /></label><label className="wide">{t('parts.reason')}<textarea value={reason} onChange={(event) => setReason(event.target.value)} /></label></div>
    <div className="request-lines"><div className="request-lines-head"><h4>{t('requests.lines', { count: lines.length })}</h4><button className="secondary compact" onClick={() => setLines((current) => [...current, { position: '', part_number: '', description: '', quantity: 1, unit: '' }])}><Plus size={15} />{t('requests.addLine')}</button></div>{lines.map((line, index) => <div className="request-line" key={index}><label>{t('requests.catalogPart')}<select value={line.catalog_part_id || ''} onChange={(event) => chooseCatalog(index, Number(event.target.value))}><option value="">{t('requests.manualLine')}</option>{catalog.map((part) => <option key={part.id} value={part.id}>{part.part_number} · {part.description}</option>)}</select></label><label>{t('catalog.position')}<input value={line.position} onChange={(event) => updateLine(index, { position: event.target.value })} /></label><label>{t('common.partNumber')}<input value={line.part_number} onChange={(event) => updateLine(index, { part_number: event.target.value })} /></label><label>{t('catalog.description')}<input required value={line.description} onChange={(event) => updateLine(index, { description: event.target.value })} /></label><label>{t('common.quantity')}<input type="number" min="0.01" step="0.01" value={line.quantity} onChange={(event) => updateLine(index, { quantity: Number(event.target.value) })} /></label><label>{t('requests.unit')}<input value={line.unit} onChange={(event) => updateLine(index, { unit: event.target.value })} /></label>{lines.length > 1 && <button className="link remove-line" onClick={() => setLines((current) => current.filter((_, itemIndex) => itemIndex !== index))}>{t('requests.removeLine')}</button>}</div>)}</div>
    <div className="actions"><button className="secondary" onClick={onClose}>{t('common.cancel')}</button><button className="primary" disabled={invalid} onClick={() => setStep('confirm')}>{t('bulk.reviewConfirm')}</button></div>
  </> : <><div className="confirmation-summary"><h4>{t('requests.confirm')}</h4><p>{t('requests.confirmSummary', { count: lines.length })}</p>{lines.map((line, index) => <div className="summary-line" key={index}><b>{line.part_number || t('common.noValue')}</b><span>{line.description}</span><em>{line.quantity} {line.unit}</em></div>)}</div><div className="actions"><button className="secondary" onClick={() => setStep('edit')}>{t('common.back')}</button><button className="primary" onClick={() => void submit()}>{t('requests.submit')}</button></div></>}
  </Modal>
}

function UnknownPartRequestModal({ machines, repairs, onClose, onSaved }: { machines: Machine[]; repairs: RepairCase[]; onClose: () => void; onSaved: () => void }) {
  const { locale, t } = useI18n()
  const [machineId, setMachineId] = useState<number | ''>('')
  const [repairId, setRepairId] = useState<number | ''>('')
  const [assembly, setAssembly] = useState('')
  const [description, setDescription] = useState('')
  const [quantity, setQuantity] = useState(1)
  const [unit, setUnit] = useState('')
  const [note, setNote] = useState('')
  const [priority, setPriority] = useState('NORMAL')
  const [photo, setPhoto] = useState<File | null>(null)
  const [previewUrl, setPreviewUrl] = useState('')
  const [step, setStep] = useState<'edit' | 'confirm' | 'done'>('edit')
  const [reference, setReference] = useState('')
  const [error, setError] = useState('')
  useEffect(() => () => { if (previewUrl) URL.revokeObjectURL(previewUrl) }, [previewUrl])
  function choosePhoto(file?: File) {
    if (previewUrl) URL.revokeObjectURL(previewUrl)
    setPreviewUrl('')
    if (!file) { setPhoto(null); return }
    if (!['image/jpeg', 'image/png', 'image/webp'].includes(file.type)) {
      setError(t('unknownPart.photoFormatError'))
      setPhoto(null)
      return
    }
    setError('')
    setPhoto(file)
    setPreviewUrl(URL.createObjectURL(file))
  }
  async function submit() {
    if (!photo || !machineId) return
    try {
      const created = await api<MultiPartRequest>('/part-requests/unknown', {
        method: 'POST',
        body: JSON.stringify({ machine_id: machineId, repair_id: repairId || null, assembly, description, quantity, unit: unit || null, note: note || null, priority, language: locale, photo: await filePayload(photo) }),
      })
      await api(`/part-requests/${created.id}/submit`, { method: 'POST' })
      setReference(created.request_reference)
      setStep('done')
      onSaved()
    } catch (caught) { setError(friendlyError(caught, t('unknownPart.saveError'))) }
  }
  const invalid = !machineId || !assembly.trim() || !description.trim() || quantity <= 0 || !photo
  return <Modal title={t('unknownPart.new')} onClose={onClose} wide>{error && <div className="error">{error}</div>}{step === 'edit' && <>
    <div className="unknown-part-banner"><b>{t('unknownPart.label')}</b><span>{t('unknownPart.catalogWarning')}</span></div>
    <div className="form-grid"><label>{t('parts.machine')}<select required value={machineId} onChange={(event) => { setMachineId(event.target.value ? Number(event.target.value) : ''); setRepairId('') }}><option value="">{t('unknownPart.chooseMachine')}</option>{machines.map((machine) => <option key={machine.id} value={machine.id}>{machine.name}</option>)}</select></label><label>{t('requests.linkedRepair')}<select value={repairId} onChange={(event) => setRepairId(event.target.value ? Number(event.target.value) : '')}><option value="">{t('common.notSpecified')}</option>{repairs.filter((repair) => !machineId || repair.machine_id === machineId).map((repair) => <option value={repair.id} key={repair.id}>{repair.repair_reference} · №{repair.machine_number}</option>)}</select></label><label>{t('unknownPart.assembly')}<input required value={assembly} onChange={(event) => setAssembly(event.target.value)} /></label><label>{t('parts.priority')}<select value={priority} onChange={(event) => setPriority(event.target.value)}>{['LOW', 'NORMAL', 'URGENT'].map((value) => <option value={value} key={value}>{statusText(t, value, 'part')}</option>)}</select></label><label className="wide">{t('unknownPart.description')}<textarea required value={description} onChange={(event) => setDescription(event.target.value)} /></label><label>{t('common.quantity')}<input type="number" min="0.01" step="0.01" value={quantity} onChange={(event) => setQuantity(Number(event.target.value))} /></label><label>{t('requests.unit')}<input value={unit} onChange={(event) => setUnit(event.target.value)} /></label><label className="wide">{t('unknownPart.note')}<textarea value={note} onChange={(event) => setNote(event.target.value)} /></label><label className="wide unknown-part-photo-field">{t('unknownPart.photo')}<input required type="file" accept="image/jpeg,image/png,image/webp" onChange={(event) => choosePhoto(event.target.files?.[0])} />{previewUrl && <img src={previewUrl} alt={t('unknownPart.photoPreview')} />}</label></div>
    <div className="actions"><button className="secondary" onClick={onClose}>{t('common.cancel')}</button><button className="primary" disabled={invalid} onClick={() => setStep('confirm')}>{t('bulk.reviewConfirm')}</button></div>
  </>}{step === 'confirm' && <><div className="confirmation-summary"><h4>{t('requests.confirm')}</h4><div className="summary-line"><b>{t('unknownPart.label')}</b><span>{assembly} · {description}</span><em>{quantity} {unit}</em></div>{photo && <p>{t('unknownPart.photo')}: {photo.name}</p>}<p>{t('unknownPart.confirmWarning')}</p></div><div className="actions"><button className="secondary" onClick={() => setStep('edit')}>{t('common.back')}</button><button className="primary" onClick={() => void submit()}>{t('requests.submit')}</button></div></>}{step === 'done' && <div className="operation-result" role="status"><CheckCircle2 size={36} /><h4>{t('unknownPart.created')}</h4><p>{reference}</p><button className="primary" onClick={onClose}>{t('common.done')}</button></div>}</Modal>
}

function UnknownPartLinkModal({ request, line, catalog, onClose, onSaved }: { request: MultiPartRequest; line: MultiPartRequest['lines'][number]; catalog: CatalogPartEnhanced[]; onClose: () => void; onSaved: () => void }) {
  const { t } = useI18n()
  const compatible = catalog.filter((part) => part.is_verified && part.is_active !== false && (!request.machine_number || (part.compatible_machine_numbers || []).map(String).includes(String(request.machine_number))))
  const [catalogPartId, setCatalogPartId] = useState<number | ''>('')
  const [note, setNote] = useState('')
  const [error, setError] = useState('')
  async function submit() {
    if (!catalogPartId) return
    try {
      await api(`/part-requests/${request.id}/lines/${line.id}/link-catalog-part`, { method: 'POST', body: JSON.stringify({ catalog_part_id: catalogPartId, note: note || null }) })
      onSaved()
    } catch (caught) { setError(friendlyError(caught, t('unknownPart.linkError'))) }
  }
  return <Modal title={t('unknownPart.linkTitle')} onClose={onClose} wide>{error && <div className="error">{error}</div>}<div className="unknown-part-banner"><b>{t('unknownPart.label')}</b><span>{line.assembly} · {line.description}</span></div><div className="form-grid"><label className="wide">{t('unknownPart.verifiedCatalogPart')}<select value={catalogPartId} onChange={(event) => setCatalogPartId(event.target.value ? Number(event.target.value) : '')}><option value="">{t('unknownPart.chooseVerifiedPart')}</option>{compatible.map((part) => <option value={part.id} key={part.id}>{part.part_number} · {part.description}</option>)}</select></label><label className="wide">{t('unknownPart.linkNote')}<textarea value={note} onChange={(event) => setNote(event.target.value)} /></label></div>{!compatible.length && <div className="error">{t('unknownPart.noCompatibleVerifiedParts')}</div>}<div className="actions"><button className="secondary" onClick={onClose}>{t('common.cancel')}</button><button className="primary" disabled={!catalogPartId} onClick={() => void submit()}>{t('unknownPart.linkAction')}</button></div></Modal>
}

function PartRequestFulfillmentModal({ request, onClose, onSaved }: { request: MultiPartRequest; onClose: () => void; onSaved: () => void }) {
  const { t } = useI18n()
  const statuses = request.status === 'APPROVED'
    ? ['ORDERED', 'CANCELLED']
    : ['PARTIALLY_DELIVERED', 'DELIVERED', 'CANCELLED']
  const [nextStatus, setNextStatus] = useState(statuses[0])
  const [supplier, setSupplier] = useState(request.supplier || '')
  const [note, setNote] = useState(request.delivery_note || '')
  const [quantities, setQuantities] = useState<Record<number, number>>(Object.fromEntries(request.lines.map((line) => [line.id, line.delivered_quantity])))
  const [error, setError] = useState('')
  async function submit(event: FormEvent) {
    event.preventDefault()
    if (!window.confirm(t('requests.fulfillmentConfirm'))) return
    try {
      await api(`/part-requests/${request.id}/fulfillment`, { method: 'PATCH', body: JSON.stringify({ status: nextStatus, supplier: supplier || null, note: note || null, lines: request.lines.map((line) => ({ line_id: line.id, delivered_quantity: quantities[line.id] || 0 })) }) })
      onSaved()
    } catch (caught) { setError(friendlyError(caught, t('requests.fulfillmentError'))) }
  }
  return <Modal title={t('requests.fulfillmentTitle')} onClose={onClose} wide><form className="form-grid" onSubmit={submit}><label>{t('common.status')}<select value={nextStatus} onChange={(event) => setNextStatus(event.target.value)}>{statuses.map((status) => <option value={status} key={status}>{statusText(t, status, 'part')}</option>)}</select></label><label>{t('catalog.supplier')}<input value={supplier} onChange={(event) => setSupplier(event.target.value)} /></label><label className="wide">{t('common.notes')}<textarea value={note} onChange={(event) => setNote(event.target.value)} /></label><div className="wide request-line-list">{request.lines.map((line) => <div key={line.id}><span><b>{line.part_number || t('common.noValue')}</b><small>{line.description}</small></span><label>{t('requests.deliveredQuantity')}<input disabled={nextStatus === 'ORDERED' || nextStatus === 'CANCELLED'} type="number" min={line.delivered_quantity} max={line.quantity} step="0.01" value={quantities[line.id] || 0} onChange={(event) => setQuantities((current) => ({ ...current, [line.id]: Number(event.target.value) }))} /></label><em>/ {line.quantity} {line.unit}</em></div>)}</div>{error && <div className="error wide">{error}</div>}<div className="actions wide"><button type="button" className="secondary" onClick={onClose}>{t('common.cancel')}</button><button className="primary">{t('requests.saveFulfillment')}</button></div></form></Modal>
}

export function IndustrialPartRequests() {
  const { date, t } = useI18n()
  const [items, setItems] = useState<MultiPartRequest[]>([])
  const [machines, setMachines] = useState<Machine[]>([])
  const [catalog, setCatalog] = useState<CatalogPartEnhanced[]>([])
  const [repairs, setRepairs] = useState<RepairCase[]>([])
  const [create, setCreate] = useState(false)
  const [fulfillment, setFulfillment] = useState<MultiPartRequest | null>(null)
  const [unknownCreate, setUnknownCreate] = useState(false)
  const [unknownLink, setUnknownLink] = useState<{ request: MultiPartRequest; line: MultiPartRequest['lines'][number] } | null>(null)
  const [error, setError] = useState('')
  const load = () => Promise.all([api<MultiPartRequest[]>('/part-requests/multi'), api<Machine[]>('/machines'), api<CatalogPartEnhanced[]>('/catalog/parts'), api<RepairCase[]>('/repair-cases')]).then(([requestItems, machineItems, catalogItems, repairItems]) => { setItems(requestItems); setMachines(machineItems); setCatalog(catalogItems); setRepairs(repairItems); setError('') }).catch((caught) => setError(friendlyError(caught, t('requests.loadError'))))
  useEffect(() => { void load() }, [])
  async function decide(id: number, decision: 'APPROVED' | 'REJECTED') {
    if (!window.confirm(t(decision === 'APPROVED' ? 'requests.approveConfirm' : 'requests.rejectConfirm'))) return
    try { await api(`/part-requests/${id}/decision`, { method: 'POST', body: JSON.stringify({ decision }) }); await load() } catch (caught) { setError(friendlyError(caught, t('requests.decisionError'))) }
  }
  async function generate(request: MultiPartRequest) {
    if (!window.confirm(t('documents.confirmLanguage', { language: t(`language.${request.language}` as TranslationKey) }))) return
    try { await api(`/part-requests/${request.id}/documents?language=${request.language}`, { method: 'POST' }); await load() } catch (caught) { setError(friendlyError(caught, t('requests.documentError'))) }
  }
  async function attach(request: MultiPartRequest, file?: File) {
    if (!file) return
    try {
      await api(`/part-requests/${request.id}/attachments`, { method: 'POST', body: JSON.stringify({ ...(await filePayload(file)), description: file.name }) })
      await load()
    } catch (caught) { setError(friendlyError(caught, t('requests.attachmentError'))) }
  }
  return <><div className="toolbar"><div><h3>{t('parts.title')}</h3><p className="muted">{t('requests.subtitle')}</p></div><div className="toolbar-actions">{hasPermission('requests.create') && <button className="secondary" onClick={() => setUnknownCreate(true)}><ImagePlus size={18} />{t('unknownPart.new')}</button>}{hasPermission('requests.create') && <button className="primary" onClick={() => setCreate(true)}><Plus size={18} />{t('requests.new')}</button>}</div></div>{error && <div className="error">{error}</div>}<div className="cards-list">{items.map((request) => <article className="panel request-card" key={request.id}><div className="request-card-head"><div><span className="badge">{statusText(t, request.status, 'part')}</span><h3>{request.request_reference}</h3><small>{date(request.created_at)} · {request.machine_number ? t('passport.title', { number: request.machine_number }) : t('parts.general')}</small>{request.repair_reference && <small>{t('requests.linkedRepair')}: {request.repair_reference}</small>}{request.department && <small>{t('requests.department')}: {request.department}</small>}{request.supplier && <small>{t('catalog.supplier')}: {request.supplier}</small>}</div><b>{statusText(t, request.priority, 'part')}</b></div><div className="request-line-list">{request.lines.map((line) => <div className={line.is_unknown_part ? 'unknown-part-request-line' : ''} key={line.id}><span><b>{line.is_unknown_part ? t('unknownPart.label') : line.part_number || t('common.noValue')}</b><small>{line.is_unknown_part && line.assembly ? `${t('unknownPart.assembly')}: ${line.assembly} · ` : ''}{line.description}</small>{line.linked_part_number && <small className="verified">{t('unknownPart.linkedTo')}: {line.linked_part_number} · {line.linked_part_description}</small>}</span><span className="request-line-side"><em>{line.delivered_quantity > 0 ? `${t('requests.deliveredQuantity')}: ${line.delivered_quantity} / ` : ''}{line.quantity} {line.unit}</em>{line.is_unknown_part && !line.linked_catalog_part_id && hasPermission('settings.manage') && <button className="secondary compact" onClick={() => setUnknownLink({ request, line })}><ShieldCheck size={14} />{t('unknownPart.linkAction')}</button>}</span></div>)}</div>{request.attachments.length > 0 && <details><summary>{t('requests.attachments')} ({request.attachments.length})</summary><AttachmentList items={request.attachments} /></details>}<div className="request-actions">{request.status === 'WAITING_APPROVAL' && hasPermission('requests.approve') && <><button className="primary" onClick={() => void decide(request.id, 'APPROVED')}><CheckCircle2 size={16} />{t('requests.approve')}</button><button className="secondary" onClick={() => void decide(request.id, 'REJECTED')}>{t('requests.reject')}</button></>}{['APPROVED', 'ORDERED', 'PARTIALLY_DELIVERED'].includes(request.status) && hasPermission('requests.create') && <button className="secondary" onClick={() => setFulfillment(request)}><PackageCheck size={16} />{t('requests.updateFulfillment')}</button>}{hasPermission('requests.create') && <label className="secondary compact file-button"><Upload size={15} />{t('requests.addAttachment')}<input hidden type="file" accept="application/pdf,.docx,.xlsx,image/png,image/jpeg,image/webp" onChange={(event) => { void attach(request, event.target.files?.[0]); event.currentTarget.value = '' }} /></label>}{request.status !== 'DRAFT' && hasPermission('requests.create') && <button className="secondary" onClick={() => void generate(request)}><FilePlus2 size={16} />{t('requests.generate')} ({t(`language.${request.language}` as TranslationKey)})</button>}{request.documents.map((document) => <DocumentButtons key={document.id} path={document.download_endpoint} filename={document.filename} format={document.format} />)}</div></article>)}{!items.length && <div className="empty-state">{t('parts.empty')}</div>}</div>{create && <PartRequestCreateModal machines={machines} repairs={repairs} catalog={catalog} onClose={() => setCreate(false)} onSaved={() => { setCreate(false); void load() }} />}{unknownCreate && <UnknownPartRequestModal machines={machines} repairs={repairs} onClose={() => setUnknownCreate(false)} onSaved={() => void load()} />}{unknownLink && <UnknownPartLinkModal request={unknownLink.request} line={unknownLink.line} catalog={catalog} onClose={() => setUnknownLink(null)} onSaved={() => { setUnknownLink(null); void load() }} />}{fulfillment && <PartRequestFulfillmentModal request={fulfillment} onClose={() => setFulfillment(null)} onSaved={() => { setFulfillment(null); void load() }} />}</>
}

type QuickRequestLine = {
  part_id: number
  part_number: string
  description: string
  quantity: number
  unit?: string | null
  source_document?: string | null
  source_page?: number | null
  is_optional: boolean
  included: boolean
}

function QuickPartRequestModal({ part, kit, defaultMachineId, onClose }: { part?: CatalogPartEnhanced; kit?: RepairKit; defaultMachineId?: number; onClose: () => void }) {
  const { locale, t } = useI18n()
  const [machines, setMachines] = useState<Machine[]>([])
  const [machineId, setMachineId] = useState<number | ''>(defaultMachineId || '')
  const [reason, setReason] = useState('')
  const [mode, setMode] = useState<'COMPONENTS' | 'KIT'>('COMPONENTS')
  const [step, setStep] = useState<'edit' | 'confirm' | 'done'>('edit')
  const [createdReference, setCreatedReference] = useState('')
  const [error, setError] = useState('')
  const [lines, setLines] = useState<QuickRequestLine[]>(() => part ? [{ part_id: part.id, part_number: part.part_number, description: part.description, quantity: 1, unit: part.unit, source_document: part.source_document, source_page: part.source_page, is_optional: false, included: true }] : (kit?.components || []).map((component) => ({ part_id: component.part_id, part_number: component.part_number, description: component.description, quantity: component.quantity, unit: undefined, source_document: kit?.source_document, source_page: kit?.source_page, is_optional: component.is_optional, included: true })))
  useEffect(() => { void api<Machine[]>('/machines').then(setMachines).catch((caught) => setError(friendlyError(caught, t('requests.loadError')))) }, [])
  useEffect(() => { if (defaultMachineId) setMachineId(defaultMachineId) }, [defaultMachineId])
  const selectedLines = lines.filter((line) => line.included)
  const updateLine = (partId: number, changes: Partial<QuickRequestLine>) => setLines((current) => current.map((line) => line.part_id === partId ? { ...line, ...changes } : line))
  async function submit() {
    if (!selectedLines.length && mode === 'COMPONENTS') return
    try {
      const requestLines = kit && mode === 'KIT'
        ? [{ part_number: kit.code, description: kit.name, quantity: 1, source_document: kit.source_document, source_page: kit.source_page }]
        : selectedLines.map((line) => ({ catalog_part_id: line.part_id, part_number: line.part_number, description: line.description, quantity: line.quantity, unit: line.unit, source_document: line.source_document, source_page: line.source_page }))
      const created = await api<MultiPartRequest>('/part-requests/multi', { method: 'POST', body: JSON.stringify({ machine_id: machineId || null, repair_kit_id: kit?.id || null, repair_kit_mode: mode, priority: 'NORMAL', language: locale, reason: reason || null, lines: requestLines }) })
      await api(`/part-requests/${created.id}/submit`, { method: 'POST' })
      setCreatedReference(created.request_reference)
      setStep('done')
    } catch (caught) { setError(friendlyError(caught, t('requests.saveError'))) }
  }
  const title = kit ? t('catalog.requestKit') : t('catalog.requestPart')
  return <Modal title={title} onClose={onClose} wide>{error && <div className="error">{error}</div>}{step === 'edit' && <><div className="form-grid"><label>{t('parts.machine')}<select value={machineId} onChange={(event) => setMachineId(event.target.value ? Number(event.target.value) : '')}><option value="">{t('parts.general')}</option>{machines.map((machine) => <option value={machine.id} key={machine.id}>{machine.name}</option>)}</select></label>{kit && <label>{t('catalog.kitRequestMode')}<select value={mode} onChange={(event) => setMode(event.target.value as 'COMPONENTS' | 'KIT')}><option value="COMPONENTS">{t('catalog.expandComponents')}</option><option value="KIT">{t('catalog.singleKitLine')}</option></select></label>}<label className="wide">{t('parts.reason')}<textarea value={reason} onChange={(event) => setReason(event.target.value)} /></label></div>{mode === 'COMPONENTS' && <div className="kit-request-lines">{lines.map((line) => <div key={line.part_id}><label className="check-label"><input type="checkbox" checked={line.included} disabled={!line.is_optional} onChange={(event) => updateLine(line.part_id, { included: event.target.checked })} /><span><b>{line.part_number}</b><small>{line.description}{line.is_optional ? ` · ${t('catalog.optionalComponent')}` : ''}</small></span></label><input aria-label={t('common.quantity')} disabled={!line.included} type="number" min="0.01" step="0.01" value={line.quantity} onChange={(event) => updateLine(line.part_id, { quantity: Number(event.target.value) })} /></div>)}</div>}<div className="actions"><button className="secondary" onClick={onClose}>{t('common.cancel')}</button><button className="primary" disabled={(mode === 'COMPONENTS' && (!selectedLines.length || selectedLines.some((line) => line.quantity <= 0)))} onClick={() => setStep('confirm')}>{t('bulk.reviewConfirm')}</button></div></>}{step === 'confirm' && <><div className="confirmation-summary"><h4>{t('requests.confirm')}</h4><p>{kit ? `${kit.code} · ${kit.name}` : `${part?.part_number} · ${part?.description}`}</p>{mode === 'COMPONENTS' ? selectedLines.map((line) => <div className="summary-line" key={line.part_id}><b>{line.part_number}</b><span>{line.description}</span><em>{line.quantity} {line.unit}</em></div>) : <div className="summary-line"><b>{kit?.code}</b><span>{kit?.name}</span><em>1</em></div>}</div><div className="actions"><button className="secondary" onClick={() => setStep('edit')}>{t('common.back')}</button><button className="primary" onClick={() => void submit()}>{t('requests.submit')}</button></div></>}{step === 'done' && <div className="operation-result" role="status"><CheckCircle2 size={36} /><h4>{t('catalog.requestCreated')}</h4><p>{createdReference}</p><button className="primary" onClick={onClose}>{t('common.done')}</button></div>}</Modal>
}

function CatalogPartCreateModal({ parts, onClose, onSaved }: { parts: CatalogPartEnhanced[]; onClose: () => void; onSaved: () => void }) {
  const { t } = useI18n()
  const [form, setForm] = useState({ brand: '', model: '', manufacturer: '', category: '', name_bg: '', name_en: '', name_ru: '', original_name: '', assembly: '', position: '', part_number: '', description: '', quantity: '', unit: '', technical_specification: '', compatible_models: '', compatible_machine_numbers_text: '', technical_notes: '', alternative_part_number: '', alternative_part_numbers_text: '', supplier: '', supplier_code: '', estimated_price: '', currency: '', lead_time_days: '', revision: '', source_document: '', source_page: '', source_excerpt: '', provenance_confidence: '', is_active: true })
  const [replacementPartIds, setReplacementPartIds] = useState<number[]>([])
  const [error, setError] = useState('')
  async function submit(event: FormEvent) {
    event.preventDefault()
    try {
      const { compatible_machine_numbers_text, alternative_part_numbers_text, ...values } = form
      await api('/catalog/parts', { method: 'POST', body: JSON.stringify({ ...values, quantity: form.quantity ? Number(form.quantity) : null, source_page: form.source_page ? Number(form.source_page) : null, provenance_confidence: form.provenance_confidence ? Number(form.provenance_confidence) : null, estimated_price: form.estimated_price ? Number(form.estimated_price) : null, lead_time_days: form.lead_time_days ? Number(form.lead_time_days) : null, compatible_machine_numbers: compatible_machine_numbers_text.split(/[;,\s]+/).map((item) => item.trim()).filter(Boolean), alternative_part_numbers: alternative_part_numbers_text.split(/[;,\n]+/).map((item) => item.trim()).filter(Boolean), replacement_part_ids: replacementPartIds }) })
      onSaved()
    } catch (caught) { setError(friendlyError(caught, t('catalog.partSaveError'))) }
  }
  const update = (field: keyof typeof form, value: string) => setForm((current) => ({ ...current, [field]: value }))
  return <Modal title={t('catalog.addPart')} onClose={onClose} wide><form className="form-grid" onSubmit={submit}><label>{t('machines.brand')}<input required value={form.brand} onChange={(event) => update('brand', event.target.value)} /></label><label>{t('machines.model')}<input value={form.model} onChange={(event) => update('model', event.target.value)} /></label><label>{t('catalog.manufacturer')}<input value={form.manufacturer} onChange={(event) => update('manufacturer', event.target.value)} /></label><label>{t('machines.category')}<input value={form.category} onChange={(event) => update('category', event.target.value)} /></label><label>{t('language.bg')}<input value={form.name_bg} onChange={(event) => update('name_bg', event.target.value)} /></label><label>{t('language.en')}<input value={form.name_en} onChange={(event) => update('name_en', event.target.value)} /></label><label>{t('language.ru')}<input value={form.name_ru} onChange={(event) => update('name_ru', event.target.value)} /></label><label>{t('catalog.originalName')}<input value={form.original_name} onChange={(event) => update('original_name', event.target.value)} /></label><label>{t('catalog.assembly')}<input value={form.assembly} onChange={(event) => update('assembly', event.target.value)} /></label><label>{t('catalog.position')}<input value={form.position} onChange={(event) => update('position', event.target.value)} /></label><label>{t('common.partNumber')}<input required value={form.part_number} onChange={(event) => update('part_number', event.target.value)} /></label><label>{t('catalog.revision')}<input value={form.revision} onChange={(event) => update('revision', event.target.value)} /></label><label className="wide">{t('catalog.description')}<textarea required value={form.description} onChange={(event) => update('description', event.target.value)} /></label><label>{t('common.quantity')}<input type="number" min="0" value={form.quantity} onChange={(event) => update('quantity', event.target.value)} /></label><label>{t('requests.unit')}<input value={form.unit} onChange={(event) => update('unit', event.target.value)} /></label><label>{t('catalog.alternativeNumber')}<input value={form.alternative_part_number} onChange={(event) => update('alternative_part_number', event.target.value)} /></label><label>{t('catalog.alternativeNumbers')}<input value={form.alternative_part_numbers_text} onChange={(event) => update('alternative_part_numbers_text', event.target.value)} placeholder={t('catalog.listHint')} /></label><label className="wide">{t('catalog.replacements')}<select multiple value={replacementPartIds.map(String)} onChange={(event) => setReplacementPartIds(Array.from(event.currentTarget.selectedOptions, (option) => Number(option.value)))}>{parts.map((part) => <option key={part.id} value={part.id}>{part.part_number} · {part.description}</option>)}</select><small>{t('catalog.multiSelectHint')}</small></label><label>{t('catalog.compatibility')}<input value={form.compatible_models} onChange={(event) => update('compatible_models', event.target.value)} /></label><label className="wide">{t('catalog.compatibleMachines')}<input value={form.compatible_machine_numbers_text} onChange={(event) => update('compatible_machine_numbers_text', event.target.value)} placeholder={t('catalog.compatibleMachinesHint')} /></label><label className="wide">{t('catalog.specification')}<textarea value={form.technical_specification} onChange={(event) => update('technical_specification', event.target.value)} /></label><label className="wide">{t('catalog.technicalNotes')}<textarea value={form.technical_notes} onChange={(event) => update('technical_notes', event.target.value)} /></label><label>{t('catalog.supplier')}<input value={form.supplier} onChange={(event) => update('supplier', event.target.value)} /></label><label>{t('catalog.supplierCode')}<input value={form.supplier_code} onChange={(event) => update('supplier_code', event.target.value)} /></label><label>{t('catalog.estimatedPrice')}<input type="number" min="0" step="0.01" value={form.estimated_price} onChange={(event) => update('estimated_price', event.target.value)} /></label><label>{t('catalog.currency')}<input maxLength={3} value={form.currency} onChange={(event) => update('currency', event.target.value.toUpperCase())} /></label><label>{t('catalog.leadTime')}<input type="number" min="0" value={form.lead_time_days} onChange={(event) => update('lead_time_days', event.target.value)} /></label><label>{t('catalog.sourceDocument')}<input value={form.source_document} onChange={(event) => update('source_document', event.target.value)} /></label><label>{t('common.page')}<input type="number" min="1" value={form.source_page} onChange={(event) => update('source_page', event.target.value)} /></label><label>{t('catalog.confidence')}<input type="number" min="0" max="1" step="0.01" value={form.provenance_confidence} onChange={(event) => update('provenance_confidence', event.target.value)} /></label><label className="wide">{t('catalog.sourceExcerpt')}<textarea value={form.source_excerpt} onChange={(event) => update('source_excerpt', event.target.value)} /></label><label className="check-label"><input type="checkbox" checked={form.is_active} onChange={(event) => setForm({ ...form, is_active: event.target.checked })} />{t('catalog.activePart')}</label>{error && <div className="error wide">{error}</div>}<div className="actions wide"><button type="button" className="secondary" onClick={onClose}>{t('common.cancel')}</button><button className="primary">{t('common.save')}</button></div></form></Modal>
}

function RepairKitCreateModal({ parts, onClose, onSaved }: { parts: CatalogPartEnhanced[]; onClose: () => void; onSaved: () => void }) {
  const { t } = useI18n()
  const [form, setForm] = useState({ code: '', name: '', brand: '', model: '', compatible_models: '', revision: '', assembly: '', source_document: '', source_page: '', provenance: '', confidence: '' })
  const [components, setComponents] = useState([{ part_id: '', quantity: 1, is_optional: false, note: '' }])
  const [error, setError] = useState('')
  const updateComponent = (index: number, changes: Partial<(typeof components)[number]>) => setComponents((current) => current.map((item, itemIndex) => itemIndex === index ? { ...item, ...changes } : item))
  async function submit(event: FormEvent) {
    event.preventDefault()
    try {
      await api('/repair-kits', { method: 'POST', body: JSON.stringify({ ...form, source_page: form.source_page ? Number(form.source_page) : null, confidence: form.confidence ? Number(form.confidence) : null, components: components.map((item) => ({ ...item, part_id: Number(item.part_id) })) }) })
      onSaved()
    } catch (caught) { setError(friendlyError(caught, t('catalog.kitSaveError'))) }
  }
  return <Modal title={t('catalog.addKit')} onClose={onClose} wide><form className="form-grid" onSubmit={submit}><label>{t('admin.code')}<input required value={form.code} onChange={(event) => setForm({ ...form, code: event.target.value })} /></label><label>{t('catalog.kitName')}<input required value={form.name} onChange={(event) => setForm({ ...form, name: event.target.value })} /></label><label>{t('machines.brand')}<input value={form.brand} onChange={(event) => setForm({ ...form, brand: event.target.value })} /></label><label>{t('machines.model')}<input value={form.model} onChange={(event) => setForm({ ...form, model: event.target.value })} /></label><label>{t('catalog.compatibility')}<input value={form.compatible_models} onChange={(event) => setForm({ ...form, compatible_models: event.target.value })} /></label><label>{t('catalog.revision')}<input value={form.revision} onChange={(event) => setForm({ ...form, revision: event.target.value })} /></label><label>{t('catalog.assembly')}<input value={form.assembly} onChange={(event) => setForm({ ...form, assembly: event.target.value })} /></label><label>{t('catalog.sourceDocument')}<input required value={form.source_document} onChange={(event) => setForm({ ...form, source_document: event.target.value })} /></label><label>{t('common.page')}<input required type="number" min="1" value={form.source_page} onChange={(event) => setForm({ ...form, source_page: event.target.value })} /></label><label>{t('catalog.confidence')}<input required type="number" min="0" max="1" step="0.01" value={form.confidence} onChange={(event) => setForm({ ...form, confidence: event.target.value })} /></label><label className="wide">{t('catalog.provenance')}<textarea required value={form.provenance} onChange={(event) => setForm({ ...form, provenance: event.target.value })} /></label><div className="wide request-lines"><div className="request-lines-head"><h4>{t('catalog.kitComponents')}</h4><button type="button" className="secondary compact" onClick={() => setComponents((current) => [...current, { part_id: '', quantity: 1, is_optional: false, note: '' }])}><Plus size={15} />{t('requests.addLine')}</button></div>{components.map((component, index) => <div className="request-line" key={index}><label>{t('repairCase.catalogPart')}<select required value={component.part_id} onChange={(event) => updateComponent(index, { part_id: event.target.value })}><option value="">{t('common.notSpecified')}</option>{parts.filter((part) => part.is_verified).map((part) => <option value={part.id} key={part.id}>{part.part_number} · {part.description}</option>)}</select></label><label>{t('common.quantity')}<input required type="number" min="0.01" step="0.01" value={component.quantity} onChange={(event) => updateComponent(index, { quantity: Number(event.target.value) })} /></label><label className="check-label"><input type="checkbox" checked={component.is_optional} onChange={(event) => updateComponent(index, { is_optional: event.target.checked })} />{t('catalog.optionalComponent')}</label><label>{t('common.notes')}<input value={component.note} onChange={(event) => updateComponent(index, { note: event.target.value })} /></label>{components.length > 1 && <button type="button" className="link remove-line" onClick={() => setComponents((current) => current.filter((_, itemIndex) => itemIndex !== index))}>{t('requests.removeLine')}</button>}</div>)}</div>{error && <div className="error wide">{error}</div>}<div className="actions wide"><button type="button" className="secondary" onClick={onClose}>{t('common.cancel')}</button><button className="primary" disabled={components.some((item) => !item.part_id || item.quantity <= 0)}>{t('common.save')}</button></div></form></Modal>
}

function CatalogAssemblyBrowser({
  machine,
  parts,
  assembly,
  onRequest,
  onOpenHotspotEditor,
}: {
  machine: Machine
  parts: CatalogPartEnhanced[]
  assembly: string
  onRequest: (part: CatalogPartEnhanced) => void
  onOpenHotspotEditor: (part: CatalogPartEnhanced) => void
}) {
  const { t } = useI18n()
  const assemblyParts = useMemo(
    () => parts.filter((part) => part.assembly === assembly),
    [parts, assembly],
  )
  const [selectedPartId, setSelectedPartId] = useState<number | null>(null)
  const [documents, setDocuments] = useState<TechnicalLibraryDocument[]>([])
  const [documentId, setDocumentId] = useState<number | ''>('')
  const [pageNumber, setPageNumber] = useState(1)
  const [previewUrl, setPreviewUrl] = useState('')
  const [hotspots, setHotspots] = useState<PartHotspot[]>([])
  const [zoom, setZoom] = useState(100)
  const [query, setQuery] = useState('')
  const [error, setError] = useState('')
  const [dragging, setDragging] = useState(false)
  const dragState = useRef<{ x: number; y: number; left: number; top: number } | null>(null)
  const viewportRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const first = assemblyParts[0]?.id || null
    setSelectedPartId((current) => assemblyParts.some((part) => part.id === current) ? current : first)
    setQuery('')
  }, [assembly, parts])
  const selectedPart = assemblyParts.find((part) => part.id === selectedPartId) || assemblyParts[0]
  const filteredParts = useMemo(() => {
    const normalized = query.trim().toLocaleLowerCase()
    if (!normalized) return assemblyParts
    return assemblyParts.filter((part) => `${part.position || ''} ${part.part_number} ${part.description} ${part.original_name || ''}`.toLocaleLowerCase().includes(normalized))
  }, [assemblyParts, query])

  useEffect(() => {
    if (!selectedPart) return
    let active = true
    void api<TechnicalLibraryDocument[]>(`/technical-library?brand=${encodeURIComponent(selectedPart.brand)}${selectedPart.model ? `&model=${encodeURIComponent(selectedPart.model)}` : ''}`)
      .then((items) => {
        if (!active) return
        setDocuments(items)
        const sourceKey = selectedPart.source_document?.replace(/^technical_docs\//, '')
        const filename = sourceKey?.split('/').pop()
        const preferred = items.find((item) => item.source_key === sourceKey)
          || items.find((item) => item.title === filename)
          || items[0]
        setDocumentId(preferred?.id || '')
        setPageNumber(selectedPart.diagram_page || selectedPart.source_page || 1)
      })
      .catch((caught) => setError(friendlyError(caught, t('catalog.documentPreviewError'))))
    return () => { active = false }
  }, [selectedPart?.id])

  useEffect(() => {
    setPreviewUrl('')
    if (!documentId) return
    let active = true
    let createdUrl = ''
    void createApiObjectUrl(`/technical-library/${documentId}/pages/${pageNumber}/preview?scale=2`)
      .then((result) => {
        createdUrl = result.url
        if (active) setPreviewUrl(result.url)
      })
      .catch((caught) => setError(friendlyError(caught, t('catalog.documentPreviewError'))))
    return () => { active = false; if (createdUrl) URL.revokeObjectURL(createdUrl) }
  }, [documentId, pageNumber])

  useEffect(() => {
    if (!documentId) { setHotspots([]); return }
    void api<PartHotspot[]>(`/catalog/hotspots?technical_document_id=${documentId}&page_number=${pageNumber}`)
      .then(setHotspots)
      .catch((caught) => setError(friendlyError(caught, t('catalog.hotspotLoadError'))))
  }, [documentId, pageNumber])

  useEffect(() => {
    const part = assemblyParts.find((item) => item.id === selectedPartId)
    if (!part) return
    const page = part.diagram_page || part.source_page || 1
    setPageNumber(page)
  }, [selectedPartId])

  const verifiedHotspots = hotspots.filter((item) => item.is_verified)
  const selectedHotspots = verifiedHotspots.filter((item) => item.part_id === selectedPart?.id)
  const selectedDocument = documents.find((document) => document.id === documentId)
  const diagramAvailable = Boolean(selectedPart?.diagram_page)

  function startPan(event: React.PointerEvent<HTMLDivElement>) {
    if (!viewportRef.current || event.button !== 0) return
    dragState.current = { x: event.clientX, y: event.clientY, left: viewportRef.current.scrollLeft, top: viewportRef.current.scrollTop }
    setDragging(true)
    event.currentTarget.setPointerCapture(event.pointerId)
  }
  function movePan(event: React.PointerEvent<HTMLDivElement>) {
    const origin = dragState.current
    const viewport = viewportRef.current
    if (!origin || !viewport) return
    viewport.scrollLeft = origin.left - (event.clientX - origin.x)
    viewport.scrollTop = origin.top - (event.clientY - origin.y)
  }
  function endPan(event: React.PointerEvent<HTMLDivElement>) {
    dragState.current = null
    setDragging(false)
    if (event.currentTarget.hasPointerCapture(event.pointerId)) event.currentTarget.releasePointerCapture(event.pointerId)
  }

  if (!assemblyParts.length) return <div className="empty-state">{t('catalog.noCompatibleParts')}</div>
  return <section className="visual-catalog-workspace" aria-label={t('catalog.visualWorkspace')}>
    {error && <div className="error">{error}</div>}
    <header className="visual-catalog-header">
      <div><span className="badge">{t('catalog.selectedMachine')}</span><h3>{machine.name}</h3><p>{machine.brand} · {machine.model || t('common.noValue')} · {assembly}</p></div>
      <div className="visual-catalog-source"><b>{selectedDocument?.title || selectedPart?.source_document || t('common.noValue')}</b><small>{t('common.page')} {pageNumber}{selectedPart?.source_figure ? ` · ${selectedPart.source_figure}` : ''}</small></div>
    </header>
    <div className="visual-catalog-grid">
      <div className="visual-diagram-panel">
        <div className="hotspot-tools">
          <button className="secondary compact" aria-label={t('catalog.zoomOut')} disabled={zoom <= 75} onClick={() => setZoom((value) => Math.max(75, value - 25))}><ZoomOut size={16} /></button>
          <span>{zoom}%</span>
          <button className="secondary compact" aria-label={t('catalog.zoomIn')} disabled={zoom >= 250} onClick={() => setZoom((value) => Math.min(250, value + 25))}><ZoomIn size={16} /></button>
          <button className="secondary compact" onClick={() => setZoom(100)}>{t('catalog.resetView')}</button>
          <button className="secondary compact" onClick={() => void viewportRef.current?.requestFullscreen()}><Maximize2 size={16} />{t('catalog.fullscreen')}</button>
        </div>
        {!diagramAvailable && <div className="catalog-fallback-note"><b>{t('catalog.noVerifiedDiagram')}</b><span>{t('catalog.tableSelectionFallback')}</span></div>}
        <div
          className={`diagram-pan-viewport ${dragging ? 'dragging' : ''}`}
          ref={viewportRef}
          onPointerDown={startPan}
          onPointerMove={movePan}
          onPointerUp={endPan}
          onPointerCancel={endPan}
        >
          <div className="diagram-scaled-canvas" style={{ width: `${zoom}%` }}>
            {previewUrl ? <img draggable={false} src={previewUrl} alt={`${assembly} · ${t('common.page')} ${pageNumber}`} /> : <div className="diagram-loading">{t('common.loading')}</div>}
            {verifiedHotspots.map((hotspot) => {
              const mappedPart = assemblyParts.find((part) => part.id === hotspot.part_id)
              if (!mappedPart) return null
              const selected = mappedPart.id === selectedPart?.id
              return <button
                type="button"
                key={hotspot.id}
                className={`hotspot-marker verified-marker ${selected ? 'selected-marker' : ''}`}
                style={{ left: `${hotspot.x * 100}%`, top: `${hotspot.y * 100}%`, width: `${Math.max(hotspot.width, .025) * 100}%`, height: `${Math.max(hotspot.height, .025) * 100}%` }}
                title={`${mappedPart.position || ''} · ${mappedPart.part_number} · ${mappedPart.description}`}
                onPointerDown={(event) => event.stopPropagation()}
                onClick={() => setSelectedPartId(mappedPart.id)}
              >{hotspot.label || mappedPart.position || '•'}</button>
            })}
            {selectedPart && !selectedHotspots.length && <div className="selected-position-chip">{t('catalog.selectedPosition')}: <b>{selectedPart.position || t('common.noValue')}</b></div>}
          </div>
        </div>
        <p className="diagram-pan-hint">{t('catalog.panHint')}</p>
      </div>
      <aside className="visual-part-details">
        {selectedPart && <>
          <span className="badge batch-complete">{selectedPart.is_verified ? t('catalog.verified') : t('catalog.unverified')}</span>
          <h3>{selectedPart.position ? `${t('catalog.position')} ${selectedPart.position}` : selectedPart.part_number}</h3>
          <code>{selectedPart.part_number}</code>
          <p>{selectedPart.description}</p>
          <dl className="detail-grid compact-details"><div><dt>{t('common.quantity')}</dt><dd>{selectedPart.quantity ?? t('common.noValue')} {selectedPart.unit || ''}</dd></div><div><dt>{t('catalog.compatibility')}</dt><dd>{selectedPart.compatible_models || selectedPart.model || t('common.noValue')}</dd></div><div><dt>{t('catalog.source')}</dt><dd>{selectedPart.source_document} · {t('common.page')} {selectedPart.source_page}</dd></div><div><dt>{t('catalog.verification')}</dt><dd>{selectedPart.verification_status || t('common.noValue')}</dd></div></dl>
          <div className="actions vertical-actions">
            {hasPermission('requests.create') && <button className="primary" onClick={() => onRequest(selectedPart)}><PackageCheck size={16} />{t('catalog.addToRequest')}</button>}
            {hasPermission('parts.manage') && <button className="secondary" onClick={() => onOpenHotspotEditor(selectedPart)}>{t('catalog.manageVisualPositions')}</button>}
          </div>
        </>}
      </aside>
    </div>
    <div className="visual-position-table">
      <div className="searchbox"><Search size={17} /><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder={t('catalog.searchPositions')} /></div>
      <div className="table-card"><table><thead><tr><th>{t('catalog.position')}</th><th>{t('common.partNumber')}</th><th>{t('catalog.description')}</th><th>{t('common.quantity')}</th><th>{t('catalog.source')}</th></tr></thead><tbody>{filteredParts.map((part) => <tr className={part.id === selectedPart?.id ? 'selected-catalog-row' : ''} key={part.id} onClick={() => setSelectedPartId(part.id)}><td><b>{part.position || t('common.noValue')}</b></td><td><code>{part.part_number}</code></td><td>{part.description}</td><td>{part.quantity ?? t('common.noValue')} {part.unit || ''}</td><td>{t('common.page')} {part.source_page}</td></tr>)}</tbody></table></div>
    </div>
  </section>
}

export function IndustrialCatalog({ defaultMachineId }: { defaultMachineId?: number } = {}) {
  const { t } = useI18n()
  const [machines, setMachines] = useState<Machine[]>([])
  const [selectedMachineId, setSelectedMachineId] = useState<number | ''>(defaultMachineId || '')
  const [parts, setParts] = useState<CatalogPartEnhanced[]>([])
  const [kits, setKits] = useState<RepairKit[]>([])
  const [assembly, setAssembly] = useState('')
  const [selected, setSelected] = useState<CatalogPartEnhanced | null>(null)
  const [requestPart, setRequestPart] = useState<CatalogPartEnhanced | null>(null)
  const [requestKit, setRequestKit] = useState<RepairKit | null>(null)
  const [createPart, setCreatePart] = useState(false)
  const [createKit, setCreateKit] = useState(false)
  const [error, setError] = useState('')
  const selectedMachine = machines.find((machine) => machine.id === selectedMachineId)
  useEffect(() => {
    void Promise.all([api<Machine[]>('/machines'), api<RepairKit[]>('/repair-kits')])
      .then(([machineItems, kitItems]) => { setMachines(machineItems); setKits(kitItems); setError('') })
      .catch((caught) => setError(friendlyError(caught, t('catalog.loadError'))))
  }, [])
  useEffect(() => { if (defaultMachineId) setSelectedMachineId(defaultMachineId) }, [defaultMachineId])
  const loadParts = () => {
    if (!selectedMachineId) { setParts([]); setAssembly(''); return Promise.resolve() }
    return api<CatalogPartEnhanced[]>(`/catalog/parts?verified_only=true&machine_id=${selectedMachineId}`)
      .then((items) => {
        setParts(items)
        setAssembly((current) => current && items.some((item) => item.assembly === current)
          ? current
          : items.find((item) => item.assembly)?.assembly || '')
        setError('')
      })
      .catch((caught) => setError(friendlyError(caught, t('catalog.loadError'))))
  }
  useEffect(() => { setParts([]); setAssembly(''); void loadParts() }, [selectedMachineId])
  const assemblies = useMemo(() => Array.from(new Set(parts.map((part) => part.assembly).filter((value): value is string => Boolean(value)))).sort(), [parts])
  async function approveKit(kit: RepairKit) {
    if (!window.confirm(t('catalog.approveKitConfirm'))) return
    try { await api(`/repair-kits/${kit.id}/approve`, { method: 'POST' }); const items = await api<RepairKit[]>('/repair-kits'); setKits(items) } catch (caught) { setError(friendlyError(caught, t('catalog.approveKitError'))) }
  }
  return <>
    <div className="toolbar">
      <div><h3>{t('catalog.title')}</h3><p className="muted">{t('catalog.machineFirstHint')}</p></div>
      {hasPermission('parts.manage') && <button className="primary" onClick={() => setCreatePart(true)}><Plus size={17} />{t('catalog.addPart')}</button>}
    </div>
    <div className="catalog-machine-selector panel">
      <label>{t('catalog.chooseMachine')}<select value={selectedMachineId} onChange={(event) => setSelectedMachineId(event.target.value ? Number(event.target.value) : '')}><option value="">{t('catalog.chooseMachinePlaceholder')}</option>{machines.map((machine) => <option key={machine.id} value={machine.id}>{machine.name} · {machine.brand} {machine.model || ''}</option>)}</select></label>
      {selectedMachine && <div className="selected-machine-summary"><b>{selectedMachine.name}</b><span>{selectedMachine.brand} · {selectedMachine.model || t('common.noValue')}</span><small>{t('machines.serialNumber')}: {selectedMachine.serial_number || t('common.noValue')}</small></div>}
      {selectedMachineId && <label>{t('catalog.assembly')}<select value={assembly} onChange={(event) => setAssembly(event.target.value)}><option value="">{t('catalog.chooseAssembly')}</option>{assemblies.map((item) => <option key={item} value={item}>{item}</option>)}</select></label>}
    </div>
    {error && <div className="error">{error}</div>}
    {!selectedMachineId && <div className="empty-state visual-catalog-empty"><BookOpen size={34} /><h3>{t('catalog.chooseMachineTitle')}</h3><p>{t('catalog.chooseMachineExplanation')}</p></div>}
    {selectedMachine && assembly && <CatalogAssemblyBrowser machine={selectedMachine} parts={parts} assembly={assembly} onRequest={setRequestPart} onOpenHotspotEditor={setSelected} />}
    {selectedMachineId && !parts.length && <div className="empty-state">{t('catalog.noCompatibleParts')}</div>}
    <div className="toolbar section-heading"><div><h3>{t('catalog.kits')}</h3><p className="muted">{t('catalog.kitsHint')}</p></div>{hasPermission('parts.manage') && <button className="secondary" onClick={() => setCreateKit(true)}><Plus size={17} />{t('catalog.addKit')}</button>}</div>
    <div className="cards-list">{kits.map((kit) => <article className="panel kit-card" key={kit.id}><div><span className={`badge ${kit.is_approved ? 'batch-complete' : 'batch-active'}`}>{kit.is_approved ? t('catalog.approvedKit') : t('catalog.pendingKit')}</span><h3>{kit.code} · {kit.name}</h3><p>{kit.brand} {kit.model} · {kit.compatible_models || t('common.noValue')} · {kit.assembly}</p><small>{kit.revision ? `${t('catalog.revision')}: ${kit.revision} · ` : ''}{kit.source_document} · {t('common.page')} {kit.source_page}{kit.confidence != null ? ` · ${t('catalog.confidence')}: ${Math.round(kit.confidence * 100)}%` : ''}</small></div><ul>{kit.components.map((component) => <li key={component.id}><b>{component.part_number}</b> {component.description} · {component.quantity}{component.is_optional ? ` · ${t('catalog.optionalComponent')}` : ''}</li>)}</ul><div className="actions">{kit.is_approved && hasPermission('requests.create') && <button className="primary" onClick={() => setRequestKit(kit)}>{t('catalog.addKitToRequest')}</button>}{!kit.is_approved && hasPermission('parts.manage') && <button className="secondary" onClick={() => void approveKit(kit)}>{t('catalog.approveKit')}</button>}</div></article>)}{!kits.length && <div className="empty-state">{t('catalog.noKits')}</div>}</div>
    {selected && <PartHotspotViewer part={selected} allParts={parts} onRequest={(requestedPart) => { setSelected(null); setRequestPart(requestedPart) }} onClose={() => setSelected(null)} />}
    {requestPart && <QuickPartRequestModal part={requestPart} defaultMachineId={selectedMachineId || defaultMachineId} onClose={() => setRequestPart(null)} />}
    {requestKit && <QuickPartRequestModal kit={requestKit} defaultMachineId={selectedMachineId || defaultMachineId} onClose={() => setRequestKit(null)} />}
    {createPart && <CatalogPartCreateModal parts={parts} onClose={() => setCreatePart(false)} onSaved={() => { setCreatePart(false); void loadParts() }} />}
    {createKit && <RepairKitCreateModal parts={parts} onClose={() => setCreateKit(false)} onSaved={() => { setCreateKit(false); void api<RepairKit[]>('/repair-kits').then(setKits) }} />}
  </>
}

function CatalogImagePreview({ image }: { image: CatalogPartImage }) {
  const { t } = useI18n()
  const [url, setUrl] = useState('')
  const [failed, setFailed] = useState(false)
  useEffect(() => {
    let active = true
    let createdUrl = ''
    void createApiObjectUrl(image.download_endpoint).then((result) => {
      createdUrl = result.url
      if (active) setUrl(result.url)
    }).catch(() => setFailed(true))
    return () => { active = false; if (createdUrl) URL.revokeObjectURL(createdUrl) }
  }, [image.download_endpoint])
  return <article className="catalog-image-card">{url && <img src={url} alt={image.caption || image.filename} />}{!url && !failed && <span className="skeleton-image" aria-label={t('common.loading')} />}{failed && <span className="inline-error">{t('catalog.imageLoadError')}</span>}<div><b>{image.caption || image.filename}</b><small>SHA-256 {image.sha256.slice(0, 12)}…</small><DownloadButton path={image.download_endpoint} filename={image.filename} /></div></article>
}

function PartHotspotViewer({ part, allParts, onRequest, onClose }: { part: CatalogPartEnhanced; allParts: CatalogPartEnhanced[]; onRequest: (part: CatalogPartEnhanced) => void; onClose: () => void }) {
  const { t } = useI18n()
  const [hotspots, setHotspots] = useState<PartHotspot[]>([])
  const [documents, setDocuments] = useState<TechnicalLibraryDocument[]>([])
  const [images, setImages] = useState<CatalogPartImage[]>([])
  const [documentId, setDocumentId] = useState<number | ''>('')
  const [pageNumber, setPageNumber] = useState(part.diagram_page || part.source_page || 1)
  const [source, setSource] = useState('')
  const [confidence, setConfidence] = useState('')
  const [objectUrl, setObjectUrl] = useState('')
  const [mediaType, setMediaType] = useState('')
  const [marking, setMarking] = useState(false)
  const [zoom, setZoom] = useState(100)
  const [error, setError] = useState('')
  const [imageFile, setImageFile] = useState<File | null>(null)
  const [uploadingImage, setUploadingImage] = useState(false)
  const viewerRef = useRef<HTMLDivElement>(null)

  const load = () => Promise.all([
    api<PartHotspot[]>(`/catalog/parts/${part.id}/hotspots`),
    api<TechnicalLibraryDocument[]>(`/technical-library?brand=${encodeURIComponent(part.brand)}${part.model ? `&model=${encodeURIComponent(part.model)}` : ''}`),
    api<CatalogPartImage[]>(`/catalog/parts/${part.id}/images`),
  ]).then(([items, library, imageItems]) => {
    setHotspots(items)
    setDocuments(library)
    setImages(imageItems)
    const preferred = items.find((item) => item.technical_document_id)?.technical_document_id || library[0]?.id || ''
    setDocumentId((current) => current || preferred)
  }).catch((caught) => setError(friendlyError(caught, t('catalog.hotspotLoadError'))))

  useEffect(() => { void load() }, [part.id])
  const loadDocumentHotspots = () => documentId
    ? api<PartHotspot[]>(`/catalog/hotspots?technical_document_id=${documentId}&page_number=${pageNumber}`).then(setHotspots)
    : Promise.resolve()
  useEffect(() => {
    void loadDocumentHotspots().catch((caught) => setError(friendlyError(caught, t('catalog.hotspotLoadError'))))
  }, [documentId, pageNumber])
  useEffect(() => {
    if (!documentId) return
    let active = true
    let createdUrl = ''
    void createApiObjectUrl(`/technical-library/${documentId}/pages/${pageNumber}/preview?scale=2`).then((result) => {
      createdUrl = result.url
      if (active) { setObjectUrl(result.url); setMediaType(result.mediaType) }
    }).catch((caught) => setError(friendlyError(caught, t('catalog.documentPreviewError'))))
    return () => { active = false; if (createdUrl) URL.revokeObjectURL(createdUrl) }
  }, [documentId, pageNumber])

  const visibleHotspots = hotspots.filter((item) => item.technical_document_id === documentId && item.page_number === pageNumber)
  async function addMarker(event: React.MouseEvent<HTMLDivElement>) {
    if (!marking || !documentId) return
    const rect = event.currentTarget.getBoundingClientRect()
    const x = Math.max(0, Math.min(1, (event.clientX - rect.left) / rect.width))
    const y = Math.max(0, Math.min(1, (event.clientY - rect.top) / rect.height))
    try {
      await api(`/catalog/parts/${part.id}/hotspots`, { method: 'POST', body: JSON.stringify({ technical_document_id: documentId, page_number: pageNumber, x, y, width: 0.035, height: 0.035, label: part.position || part.part_number, provenance: source, confidence: confidence ? Number(confidence) : null }) })
      setMarking(false)
      await loadDocumentHotspots()
    } catch (caught) { setError(friendlyError(caught, t('catalog.hotspotSaveError'))) }
  }
  async function verifyHotspot(id: number) {
    try { await api(`/catalog/hotspots/${id}/verify`, { method: 'POST' }); await loadDocumentHotspots() } catch (caught) { setError(friendlyError(caught, t('catalog.hotspotVerifyError'))) }
  }
  async function uploadImage() {
    if (!imageFile) return
    setUploadingImage(true)
    setError('')
    try {
      await api(`/catalog/parts/${part.id}/images`, { method: 'POST', body: JSON.stringify({ ...(await filePayload(imageFile)), description: imageFile.name }) })
      setImageFile(null)
      await load()
    } catch (caught) {
      setError(friendlyError(caught, t('catalog.imageUploadError')))
    } finally {
      setUploadingImage(false)
    }
  }
  const replacements = (part.replacement_part_ids || []).map((id) => allParts.find((item) => item.id === id)).filter((item): item is CatalogPartEnhanced => Boolean(item))

  return <Modal title={`${part.part_number} · ${part.description}`} onClose={onClose} wide>
    {error && <div className="error">{error}</div>}
    <div className="hotspot-layout"><aside><dl className="detail-grid"><div><dt>{t('catalog.assembly')}</dt><dd>{part.assembly || t('common.noValue')}</dd></div><div><dt>{t('catalog.position')}</dt><dd>{part.position || t('common.noValue')}</dd></div><div><dt>{t('catalog.alternativeNumbers')}</dt><dd>{[part.alternative_part_number, ...(part.alternative_part_numbers || [])].filter(Boolean).join(', ') || t('common.noValue')}</dd></div><div><dt>{t('catalog.replacements')}</dt><dd>{replacements.map((item) => `${item.part_number} · ${item.description}`).join(', ') || t('common.noValue')}</dd></div><div><dt>{t('catalog.compatibility')}</dt><dd>{part.compatible_models || part.model || t('common.noValue')}</dd></div><div><dt>{t('catalog.specification')}</dt><dd>{part.technical_specification || t('common.noValue')}</dd></div><div><dt>{t('catalog.source')}</dt><dd>{part.source_document || t('common.noValue')} · {part.source_page || t('common.noValue')}</dd></div><div><dt>{t('catalog.confidence')}</dt><dd>{part.provenance_confidence == null ? t('common.noValue') : `${Math.round(part.provenance_confidence * 100)}%`}</dd></div></dl>
      <label>{t('catalog.visualDocument')}<select value={documentId} onChange={(event) => setDocumentId(event.target.value ? Number(event.target.value) : '')}><option value="">{t('common.notSpecified')}</option>{documents.map((document) => <option key={document.id} value={document.id}>{document.title}</option>)}</select></label>
      <label>{t('common.page')}<input type="number" min="1" value={pageNumber} onChange={(event) => setPageNumber(Math.max(1, Number(event.target.value)))} /></label>
      {hasPermission('parts.manage') && <><label>{t('catalog.hotspotProvenance')}<textarea value={source} onChange={(event) => setSource(event.target.value)} /></label><label>{t('catalog.hotspotConfidence')}<input type="number" min="0" max="1" step="0.01" value={confidence} onChange={(event) => setConfidence(event.target.value)} /></label><button className={marking ? 'primary' : 'secondary'} disabled={!documentId || !source.trim()} onClick={() => setMarking((value) => !value)}>{marking ? t('catalog.clickPosition') : t('catalog.addHotspot')}</button></>}
      <div className="catalog-images"><h4>{t('catalog.images')}</h4>{images.map((image) => <CatalogImagePreview key={image.id} image={image} />)}{!images.length && <small>{t('catalog.noImages')}</small>}</div>
      {hasPermission('parts.manage') && <div className="catalog-image-upload"><label>{t('catalog.addImage')}<input type="file" accept="image/png,image/jpeg,image/webp" onChange={(event) => setImageFile(event.target.files?.[0] || null)} /></label><button className="secondary" disabled={!imageFile || uploadingImage} onClick={() => void uploadImage()}><ImagePlus size={16} />{uploadingImage ? t('common.loading') : t('common.upload')}</button></div>}
      {part.is_verified && hasPermission('requests.create') && <button className="primary" onClick={() => onRequest(part)}><PackageCheck size={16} />{t('catalog.addToRequest')}</button>}
      <div className="hotspot-list"><h4>{t('catalog.positionsOnPage')}</h4>{visibleHotspots.map((item) => { const mappedPart = allParts.find((candidate) => candidate.id === item.part_id); return <div key={item.id}><span><b>{item.label || mappedPart?.part_number || t('common.noValue')}</b><small>{mappedPart?.description || t('common.noValue')}{item.confidence != null ? ` · ${t('catalog.confidence')}: ${Math.round(item.confidence * 100)}%` : ''}</small><small>{item.provenance || t('catalog.unverified')}</small></span>{item.is_verified ? <ShieldCheck size={17} /> : hasPermission('parts.manage') && <button className="link" onClick={() => void verifyHotspot(item.id)}>{t('catalog.verify')}</button>}</div> })}{!visibleHotspots.length && <small>{t('catalog.noPositions')}</small>}</div>
    </aside><div className="hotspot-viewer"><div className="hotspot-tools"><button className="secondary compact" aria-label={t('catalog.zoomOut')} disabled={zoom <= 75} onClick={() => setZoom((value) => Math.max(75, value - 25))}><ZoomOut size={16} /></button><span>{zoom}%</span><button className="secondary compact" aria-label={t('catalog.zoomIn')} disabled={zoom >= 200} onClick={() => setZoom((value) => Math.min(200, value + 25))}><ZoomIn size={16} /></button><button className="secondary compact" onClick={() => void viewerRef.current?.requestFullscreen()}><Maximize2 size={16} />{t('catalog.fullscreen')}</button></div><div className="hotspot-scroll" ref={viewerRef}><div className={`hotspot-canvas ${marking ? 'marking' : ''}`} style={{ width: `${zoom}%` }} onClick={(event) => void addMarker(event)}>{!objectUrl && <div className="diagram-loading">{t('common.loading')}</div>}{objectUrl && mediaType.startsWith('image/') && <img src={objectUrl} alt={`${part.description} · ${t('common.page')} ${pageNumber}`} />}{objectUrl && !mediaType.startsWith('image/') && <div className="empty-state">{t('catalog.previewUnsupported')}</div>}{visibleHotspots.map((item) => { const mappedPart = allParts.find((candidate) => candidate.id === item.part_id); return <button type="button" onClick={(event) => { event.stopPropagation(); if (item.is_verified && mappedPart && hasPermission('requests.create')) onRequest(mappedPart) }} key={item.id} title={mappedPart ? `${mappedPart.part_number} · ${mappedPart.description}` : item.label || t('common.noValue')} className={item.is_verified ? 'hotspot-marker verified-marker' : 'hotspot-marker'} style={{ left: `${item.x * 100}%`, top: `${item.y * 100}%`, width: `${Math.max(item.width, .025) * 100}%`, height: `${Math.max(item.height, .025) * 100}%` }}>{item.label || mappedPart?.position || '•'}</button> })}</div></div></div></div>
  </Modal>
}

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
