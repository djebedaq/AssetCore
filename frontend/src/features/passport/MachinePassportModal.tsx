import { useEffect, useRef, useState } from 'react'
import { Download, ImagePlus, PackageCheck } from 'lucide-react'
import { api, downloadApiFile } from '../../api'
import AuthenticatedImage from '../../AuthenticatedImage'
import { AttachmentList, DOCUMENT_KEYS, DocumentButtons, Modal, filePayload, friendlyError, translatedCode, translatedEventCode } from '../../industrialUi'
import { statusText, useI18n } from '../../i18n'
import { hasPermission } from '../../permissions'
import type { MachinePassport } from '../../types'

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
