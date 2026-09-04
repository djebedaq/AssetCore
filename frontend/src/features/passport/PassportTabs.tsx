import { useRef, type Dispatch, type SetStateAction } from 'react'
import { ImagePlus, PackageCheck } from 'lucide-react'

import { AttachmentList, DOCUMENT_KEYS, DocumentButtons, DownloadButton, translatedCode, translatedEventCode } from '../../industrialUi'
import { statusText, useI18n, type TranslationKey } from '../../i18n'
import { hasPermission } from '../../permissions'
import type { MachinePassport } from '../../types'

export type PassportTab = 'overview' | 'history' | 'repairs' | 'protocols' | 'parts' | 'files' | 'audit'

export const NORMAL_PASSPORT_TABS: readonly Exclude<PassportTab, 'audit'>[] = [
  'overview', 'history', 'repairs', 'protocols', 'parts', 'files',
]

type CommonProps = { passport: MachinePassport }

export function PassportTabList({ active, auditVisible, onChange }: {
  active: PassportTab
  auditVisible: boolean
  onChange: (tab: PassportTab) => void
}) {
  const { t } = useI18n()
  const tabs: PassportTab[] = [...NORMAL_PASSPORT_TABS, ...(auditVisible ? ['audit' as const] : [])]

  function moveFocus(index: number) {
    const next = tabs[(index + tabs.length) % tabs.length]
    onChange(next)
    window.requestAnimationFrame(() => document.getElementById(`passport-tab-${next}`)?.focus())
  }

  return <div className="tabs passport-tabs" role="tablist" aria-label={t('passport.businessSections')}>
    {tabs.map((value, index) => <button
      id={`passport-tab-${value}`}
      key={value}
      type="button"
      role="tab"
      aria-selected={active === value}
      aria-controls={`passport-panel-${value}`}
      tabIndex={active === value ? 0 : -1}
      className={active === value ? 'active' : ''}
      onClick={() => onChange(value)}
      onKeyDown={(event) => {
        if (event.key === 'ArrowRight') { event.preventDefault(); moveFocus(index + 1) }
        if (event.key === 'ArrowLeft') { event.preventDefault(); moveFocus(index - 1) }
        if (event.key === 'Home') { event.preventDefault(); moveFocus(0) }
        if (event.key === 'End') { event.preventDefault(); moveFocus(tabs.length - 1) }
      }}
    >{t(`passport.tab.${value}`)}</button>)}
  </div>
}

export function PassportOverviewTab({ passport, customValues, setCustomValues, onSave }: CommonProps & {
  customValues: Record<number, string>
  setCustomValues: Dispatch<SetStateAction<Record<number, string>>>
  onSave: () => void
}) {
  const { date, locale, t } = useI18n()
  const machine = passport.machine

  function control(field: MachinePassport['custom_fields'][number]) {
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

  return <div className="passport-grid">
    <section><h4>{t('passport.identification')}</h4><dl className="detail-grid">
      <Detail label={t('machines.inventoryNumber')} value={machine.inventory_number} />
      <Detail label={t('machines.brand')} value={machine.brand} />
      <Detail label={t('machines.model')} value={machine.model || t('common.noValue')} />
      {machine.pressure_bar ? <Detail label={t('machines.pressure')} value={`${machine.pressure_bar} bar`} /> : null}
      <Detail label={t('machines.serialNumber')} value={machine.serial_number || t('common.noValue')} />
      <Detail label={t('common.location')} value={machine.location?.name || t('common.notSpecified')} />
      <Detail label={t('passport.category')} value={machine.category_definition?.[`name_${locale}` as 'name_bg'] || machine.category || t('common.notSpecified')} />
      <Detail label={t('passport.manufacturer')} value={machine.manufacturer || t('common.noValue')} />
      <Detail label={t('passport.manufactureYear')} value={machine.manufacture_year || t('common.noValue')} />
      <Detail label={t('passport.department')} value={machine.department || t('common.noValue')} />
      <Detail label={t('passport.responsible')} value={machine.responsible_person || t('common.noValue')} />
      <Detail label={t('machines.assetType')} value={machine.asset_type || t('common.noValue')} />
      <Detail label={t('machines.subtype')} value={machine.subtype || t('common.noValue')} />
      <Detail label={t('machines.ownership')} value={machine.ownership || t('common.noValue')} />
      <Detail label={t('machines.commissioningDate')} value={machine.commissioning_date ? date(machine.commissioning_date) : t('common.noValue')} />
      <Detail label={t('machines.capacity')} value={machine.capacity || t('common.noValue')} />
      <Detail label={t('machines.dimensions')} value={machine.dimensions || t('common.noValue')} />
      <Detail label={t('machines.active')} value={machine.is_active ? t('common.yes') : t('common.no')} />
      <Detail label={t('passport.addedAt')} value={date(machine.created_at)} />
    </dl></section>
    <section><h4>{t('passport.customFields')}</h4>
      {passport.custom_fields.map((field) => <label key={field.field_id}>{field[`label_${locale}` as 'label_bg'] || field.label_bg}{field.unit ? ` (${field.unit})` : ''}{control(field)}</label>)}
      {!passport.custom_fields.length && <div className="empty-state">{t('passport.noCustomFields')}</div>}
      {hasPermission('assets.edit') && passport.custom_fields.length > 0 && <button className="primary" onClick={onSave}>{t('common.save')}</button>}
    </section>
    <section><h4>{t('passport.currentState')}</h4><dl className="detail-grid">
      <Detail label={t('passport.availability')} value={passport.current_state.available ? t('bulk.available') : t('bulk.unavailable')} />
      <Detail label={t('passport.lastMovement')} value={passport.current_state.last_movement ? `${translatedEventCode(t, passport.current_state.last_movement.event_type)} · ${date(passport.current_state.last_movement.created_at)}` : t('common.noValue')} />
      <Detail label={t('passport.lastInspection')} value={passport.current_state.last_inspection ? date(passport.current_state.last_inspection.completed_at) : t('common.noValue')} />
      <Detail label={t('passport.lastTest')} value={passport.current_state.last_test ? `${passport.current_state.last_test.passed ? t('common.yes') : t('common.no')}${passport.current_state.last_test.completed_at ? ` · ${date(passport.current_state.last_test.completed_at)}` : ''}` : t('common.noValue')} />
    </dl><div className="summary-chips" aria-label={t('passport.allowedActions')}>
      {passport.current_state.allowed_actions.issue && <span>{t('bulk.issue')}</span>}
      {passport.current_state.allowed_actions.return && <span>{t('bulk.return')}</span>}
      {passport.current_state.allowed_actions.repair && <span>{t('nav.repairs')}</span>}
      {passport.current_state.allowed_actions.edit && <span>{t('common.edit')}</span>}
      {!Object.values(passport.current_state.allowed_actions).some(Boolean) && <span>{t('passport.noAllowedActions')}</span>}
    </div></section>
  </div>
}

export function PassportHistoryTab({ passport }: CommonProps) {
  const { date, t } = useI18n()
  return <div className="timeline">{passport.history.map((event) => <div key={event.id}><i /><span><b>{translatedEventCode(t, event.event_type)}</b><small>{date(event.created_at)} · {event.reference || t('common.system')}</small>{(event.previous_status || event.new_status) && <em>{event.previous_status ? statusText(t, event.previous_status) : ''} → {event.new_status ? statusText(t, event.new_status) : ''}</em>}</span></div>)}{!passport.history.length && <div className="empty-state">{t('passport.noHistory')}</div>}</div>
}

export function PassportRepairsTab({ passport }: CommonProps) {
  const { date, t } = useI18n()
  return <div className="document-list">{passport.repairs.map((repair) => <div key={repair.id}><span><b>{repair.repair_reference || t('common.noValue')}</b><small>{statusText(t, repair.status, 'repair')} · {date(repair.opened_at)}{repair.closed_at ? ` · ${date(repair.closed_at)}` : ''}</small><em>{repair.reported_problem}</em></span></div>)}{!passport.repairs.length && <div className="empty-state">{t('passport.noRepairs')}</div>}</div>
}

export function PassportProtocolsTab({ passport }: CommonProps) {
  const { date, t } = useI18n()
  const supplemental = passport.generated_documents.filter((item) => item.display_separately !== false)
  const official = passport.official_documents || []
  const empty = !passport.transfers.length && !official.length && !supplemental.length

  return <div className="passport-section-stack">
    <section><h4>{t('passport.transferRecords')}</h4><div className="document-list">{passport.transfers.map((transfer) => <div key={transfer.id}><span><b>{transfer.protocol_number}</b><small>{transfer.is_active ? t('global.activeTransfer') : t('global.closedTransfer')} · {transfer.issued_at ? date(transfer.issued_at) : t('common.noValue')}{transfer.returned_at ? ` · ${date(transfer.returned_at)}` : ''}</small>{[transfer.batch_reference, transfer.location_text, transfer.accepted_by].filter(Boolean).length > 0 && <em>{[transfer.batch_reference, transfer.location_text, transfer.accepted_by].filter(Boolean).join(' · ')}</em>}</span></div>)}{!passport.transfers.length && <div className="empty-state">{t('passport.noTransfers')}</div>}</div></section>
    <section><h4>{t('passport.officialProtocols')}</h4><div className="document-list">{official.map((item) => <div key={item.registry_key}><span><b>{item.documents.map((document) => document.document_number).join(' · ')}</b><small>{registryStatus(item.status, item.category, t)}{item.created_at ? ` · ${date(item.created_at)}` : ''}</small><em>{signatureLabel(item.signature_status, t)}</em></span><div className="official-document-actions">{item.documents.map((document) => <div key={`${item.registry_key}-${document.document_type}`}><small>{translatedCode(t, document.document_type, DOCUMENT_KEYS)}</small><div>{document.files.map((file) => {
        const safeNumber = document.document_number.replace(/[^A-Za-z0-9._-]/g, '_')
        return <DocumentButtons key={`${document.document_number}-${file.format}`} path={file.preview_endpoint || file.download_endpoint} filename={`${safeNumber}${document.version ? `-v${document.version}` : ''}.${file.format}`} format={file.format} label={file.format === 'docx' ? t('common.word') : t('common.pdf')} />
      })}{!document.files.length && <span className="muted">{t('common.noValue')}</span>}</div></div>)}</div></div>)}{!official.length && <div className="empty-state">{t('passport.noOfficialProtocols')}</div>}</div></section>
    {supplemental.length > 0 && <section><h4>{t('passport.additionalGeneratedDocuments')}</h4><div className="document-list">{supplemental.map((item) => <div key={`g-${item.id}`}><span><b>{item.document_number}</b><small>{translatedCode(t, item.document_type, DOCUMENT_KEYS)} · {date(item.created_at)}</small></span><DocumentButtons path={item.download_endpoint} filename={item.filename} format={item.format} /></div>)}</div></section>}
    {empty && <div className="empty-state">{t('passport.noDocuments')}</div>}
  </div>
}

export function PassportPartsTab({ passport, onOpenCatalog }: CommonProps & { onOpenCatalog?: () => void }) {
  const { date, t } = useI18n()
  return <div className="passport-section-stack">
    <section><div className="toolbar"><div><h4>{t('passport.usedParts')}</h4></div>{onOpenCatalog && <button className="primary" onClick={onOpenCatalog}><PackageCheck size={16} />{t('passport.openCatalog')}</button>}</div><div className="document-list">{passport.parts_used.map((part) => <div key={part.id}><span><b>{part.part_number || t('common.noValue')} · {part.description}</b><small>{part.repair_reference || t('common.noValue')} · {date(part.created_at)}</small><em>{part.quantity} {part.unit || ''}{part.source ? ` · ${part.source}` : ''}</em></span></div>)}{!passport.parts_used.length && <div className="empty-state">{t('passport.noParts')}</div>}</div></section>
    <section><h4>{t('passport.partRequests')}</h4><div className="document-list">{passport.part_requests.map((request) => <div key={request.id}><span><b>{request.request_reference || t('common.noValue')}</b><small>{statusText(t, request.status, 'part')} · {statusText(t, request.priority, 'part')} · {date(request.created_at)}</small></span></div>)}{!passport.part_requests.length && <div className="empty-state">{t('passport.noRequests')}</div>}</div></section>
  </div>
}

export function PassportFilesTab({ passport, uploading, onUpload }: CommonProps & { uploading: boolean; onUpload: (file?: File) => void }) {
  const { date, t } = useI18n()
  const fileRef = useRef<HTMLInputElement>(null)
  return <div className="passport-section-stack">
    <section><div className="toolbar"><div><h4>{t('passport.attachments')}</h4></div>{hasPermission('repairs.edit') && <><input ref={fileRef} hidden type="file" accept="image/png,image/jpeg,image/webp,application/pdf,.docx,.xlsx" onChange={(event) => { onUpload(event.target.files?.[0]); event.currentTarget.value = '' }} /><button className="primary" disabled={uploading} onClick={() => fileRef.current?.click()}><ImagePlus size={17} />{uploading ? t('passport.uploading') : t('passport.addFile')}</button></>}</div><AttachmentList items={passport.attachments} /></section>
    <section><h4>{t('passport.technicalDocuments')}</h4><div className="document-list">{passport.technical_documents.map((item) => <div key={`t-${item.id}`}><span><b>{item.title}</b><small>{translatedCode(t, item.document_type, DOCUMENT_KEYS)} · {item.language || t('common.noValue')} · {item.revision || t('common.noValue')}{item.document_date ? ` · ${date(item.document_date)}` : ''}</small>{item.source_label && <em>{item.source_label}</em>}</span><div className="technical-document-actions"><DownloadButton path={item.download_endpoint} filename={item.title} />{item.revisions.map((revision) => <DownloadButton key={revision.id} path={revision.download_endpoint} filename={revision.filename} label={revision.revision_label || `v${revision.version}`} />)}</div></div>)}{!passport.technical_documents.length && <div className="empty-state">{t('passport.noTechnicalDocuments')}</div>}</div></section>
  </div>
}

export function PassportAuditTab({ passport }: CommonProps) {
  const { date, t } = useI18n()
  return <div className="document-list">{passport.audit.map((entry) => <div key={entry.id}><span><b>{entry.action}</b><small>{date(entry.created_at)} · {entry.user_name || t('common.system')} · {entry.entity_type} #{entry.entity_id || t('common.noValue')}</small><em>{entry.operation_reference || ''}</em></span></div>)}{!passport.audit.length && <div className="empty-state">{t('audit.empty')}</div>}</div>
}

function Detail({ label, value }: { label: string; value: string | number }) {
  return <div><dt>{label}</dt><dd>{value}</dd></div>
}

function registryStatus(value: string, category: MachinePassport['official_documents'][number]['category'], t: (key: TranslationKey) => string): string {
  if (value === 'COMPLETE') return t('official.lifecycleComplete')
  if (value === 'INCOMPLETE') return t('official.lifecycleIncomplete')
  if (category === 'repairs') return statusText(t, value, 'repair')
  if (category === 'parts') return statusText(t, value, 'part')
  return statusText(t, value, 'batch')
}

function signatureLabel(value: MachinePassport['official_documents'][number]['signature_status'], t: (key: TranslationKey) => string): string {
  return t(({
    SIGNED: 'official.signatureSigned', PARTIALLY_SIGNED: 'official.signaturePartial',
    UNSIGNED: 'official.signatureUnsigned', NOT_REQUIRED: 'official.signatureNotRequired',
    UNKNOWN: 'official.signatureUnknown',
  } as const)[value])
}
