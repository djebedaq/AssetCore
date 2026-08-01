import { type FormEvent, type ReactNode, useEffect, useMemo, useState } from 'react'
import { Archive, CheckCircle2, Download, RotateCcw, Search, Send, X } from 'lucide-react'
import { ApiError, api, downloadApiFile } from './api'
import { statusText, useI18n, type TranslationKey } from './i18n'
import type {
  BatchDetails,
  BatchProgress,
  BulkIssueResult,
  BulkReturnResult,
  Location,
  ProtocolDocument,
  TransferAvailability,
} from './types'

type BulkTransfersProps = { onChanged: () => void }

type IssueForm = {
  document_language: 'bg' | 'en' | 'ru'
  company_unit: string
  department: string
  vessel: string
  dock: string
  pier: string
  work_area: string
  location_text: string
  location_id: string
  handed_over_by: string
  accepted_by: string
  equipment: string
  hoses: string
  nozzles: string
  guns: string
  accessories: string
  condition_text: string
  remarks: string
}

const EMPTY_ISSUE_FORM: IssueForm = {
  document_language: 'bg',
  company_unit: '',
  department: '',
  vessel: '',
  dock: '',
  pier: '',
  work_area: '',
  location_text: '',
  location_id: '',
  handed_over_by: '',
  accepted_by: '',
  equipment: '',
  hoses: '',
  nozzles: '',
  guns: '',
  accessories: '',
  condition_text: '',
  remarks: '',
}

type ReturnDraft = {
  transfer_id: number
  machine_id: number
  condition_text: string
  result_text: string
  notes: string
  missing_equipment: string
  damage: string
  contamination: string
  cleaning_required: boolean
  inspection_required: boolean
  repair_required: boolean
  returned_by: string
  accepted_by: string
  location_id: string
  next_status: string
}

const RETURN_STATUS_CODES = [
  'RETURNED',
  'INSPECTION',
  'CLEANING',
  'REPAIR',
  'WAITING_APPROVAL',
  'WAITING_PARTS',
  'TESTING',
]

function canOperateTransfers(): boolean {
  try {
    const role = (JSON.parse(localStorage.getItem('assetcore_user') || 'null') as { role?: string } | null)?.role
    return role === 'admin' || role === 'manager'
  } catch {
    return false
  }
}

function localizedErrorKey(error: Error): TranslationKey {
  if (!(error instanceof ApiError)) return 'errors.generic'
  if (error.status === 403) return 'errors.permissionDenied'
  if (error.status === 404) return 'errors.notFound'
  if (error.code === 'issue_conflict' || error.code === 'concurrent_issue_conflict') return 'errors.issueConflict'
  if (error.code === 'return_conflict' || error.code === 'return_without_active_transfer') return 'errors.returnConflict'
  if (error.code === 'document_template_unavailable') return 'errors.templateUnavailable'
  if (error.code === 'validation_error') return 'errors.validation'
  return 'errors.generic'
}

function ModalShell({ title, onClose, children, wide = false }: {
  title: string
  onClose: () => void
  children: ReactNode
  wide?: boolean
}) {
  const { t } = useI18n()
  return (
    <div className="modal-bg" role="presentation">
      <section className={`modal bulk-modal ${wide ? 'bulk-modal-wide' : ''}`} role="dialog" aria-modal="true" aria-label={title}>
        <div className="modal-head"><h3>{title}</h3><button onClick={onClose} aria-label={t('common.close')}><X /></button></div>
        {children}
      </section>
    </div>
  )
}

export function ConflictNotice({ error }: { error: Error | null }) {
  const { date, t } = useI18n()
  if (!error) return null
  const conflicts = error instanceof ApiError && Array.isArray(error.data.conflicts)
    ? error.data.conflicts as Array<Record<string, unknown>>
    : []
  return (
    <div className="conflict-notice" role="alert">
      <strong>{t(localizedErrorKey(error))}</strong>
      {conflicts.length > 0 && (
        <ul>
          {conflicts.map((conflict, index) => (
            <li key={String(conflict.transfer_id || conflict.machine_id || index)}>
              <b>{t('bulk.machineName', { number: String(conflict.machine_number || t('common.noValue')) })}</b>
              {conflict.status ? ` · ${statusText(t, String(conflict.status))}` : ''}
              {conflict.protocol_number ? ` · ${t('errors.protocol', { protocol: String(conflict.protocol_number) })}` : ''}
              {conflict.issued_at ? ` · ${t('errors.issuedAt', { date: date(String(conflict.issued_at)) })}` : ''}
              {conflict.current_recipient_or_location ? ` · ${String(conflict.current_recipient_or_location)}` : ''}
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

export function IssueSelectionList({ items, selected, onToggle }: {
  items: TransferAvailability[]
  selected: Set<number>
  onToggle: (item: TransferAvailability) => void
}) {
  const { t } = useI18n()
  if (!items.length) return <div className="empty-state">{t('bulk.noSearchMachines')}</div>
  return (
    <div className="selection-list">
      {items.map((item) => (
        <label
          key={item.machine_id}
          className={`selection-row ${item.available ? '' : 'unavailable'} ${selected.has(item.machine_id) ? 'selected' : ''}`}
        >
          <input
            type="checkbox"
            aria-label={t('bulk.machineAria', { number: item.machine_number })}
            checked={selected.has(item.machine_id)}
            disabled={!item.available}
            onChange={() => onToggle(item)}
          />
          <span className="selection-main">
            <strong>{t('bulk.machineName', { number: item.machine_number })}</strong>
            <small>{item.brand} · {item.pressure_bar} bar · {item.location || t('common.notSpecified')}</small>
          </span>
          <span className={`availability-pill ${item.available ? 'available' : 'blocked'}`}>
            {item.available ? t('bulk.available') : t('bulk.unavailable')}
          </span>
          {!item.available && <small className="unavailable-reason">{item.unavailable_reason || t('errors.issueConflict')}</small>}
        </label>
      ))}
    </div>
  )
}

export function ConfirmationSummary({ title, machineNumbers, rows }: {
  title: string
  machineNumbers: string[]
  rows: Array<[string, string]>
}) {
  const { t } = useI18n()
  return (
    <section className="confirmation-summary" aria-label={title}>
      <h4>{title}</h4>
      <p><b>{t('bulk.selectedSummary', { count: machineNumbers.length })}</b> {machineNumbers.map((number) => `№${number}`).join(', ')}</p>
      <dl>{rows.filter(([, value]) => value).map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{value}</dd></div>)}</dl>
    </section>
  )
}

export function IssueResult({ result, onDownload }: {
  result: BulkIssueResult
  onDownload: (path: string, filename: string) => void
}) {
  const { t } = useI18n()
  return (
    <div className="operation-result" role="status">
      <CheckCircle2 size={36} />
      <h4>{t('bulk.issueSuccess')}</h4>
      <p>{t('bulk.batchLabel', { reference: result.batch_reference })}</p>
      <button className="primary" onClick={() => onDownload(result.zip_download_endpoint, `${result.batch_reference}-protocols.zip`)}>
        <Archive size={17} />{t('bulk.downloadAllZip')}
      </button>
      <div className="result-protocols">
        <h4>{t('bulk.createdProtocols')}</h4>
        {result.transfers.map((item) => (
          <div key={item.transfer_id}>
            <span><b>{t('bulk.machineName', { number: item.machine_number })}</b><small>{item.protocol_number}</small></span>
            <span>{item.documents.map((document) => (
              <button key={document.id} className="secondary compact" onClick={() => onDownload(document.download_endpoint, document.filename)}>
                <Download size={15} />{document.format.toUpperCase()}
              </button>
            ))}</span>
          </div>
        ))}
      </div>
    </div>
  )
}

export function IssueModal({ items, locations, onClose, onComplete }: {
  items: TransferAvailability[]
  locations: Location[]
  onClose: () => void
  onComplete: () => void
}) {
  const { t } = useI18n()
  const [selected, setSelected] = useState<Set<number>>(new Set())
  const [query, setQuery] = useState('')
  const [form, setForm] = useState<IssueForm>(EMPTY_ISSUE_FORM)
  const [step, setStep] = useState<'select' | 'confirm' | 'result'>('select')
  const [result, setResult] = useState<BulkIssueResult | null>(null)
  const [error, setError] = useState<Error | null>(null)
  const [busy, setBusy] = useState(false)

  const filtered = useMemo(() => items.filter((item) => (
    `${item.machine_number} ${item.brand} ${statusText(t, item.status)} ${item.location || ''}`
      .toLowerCase()
      .includes(query.toLowerCase())
  )), [items, query, t])
  const selectedItems = items.filter((item) => selected.has(item.machine_id))
  const setField = <K extends keyof IssueForm>(field: K, value: IssueForm[K]) => setForm((current) => ({ ...current, [field]: value }))
  const toggle = (item: TransferAvailability) => {
    if (!item.available) return
    setSelected((current) => {
      const next = new Set(current)
      if (next.has(item.machine_id)) next.delete(item.machine_id)
      else next.add(item.machine_id)
      return next
    })
  }
  const continueToConfirm = () => {
    if (!selected.size) {
      setError(new Error('selection_required'))
      return
    }
    setError(null)
    setStep('confirm')
  }

  async function submit() {
    setBusy(true)
    setError(null)
    try {
      const payload = {
        machine_ids: [...selected],
        ...Object.fromEntries(Object.entries(form).map(([key, value]) => [key, value || null])),
        location_id: form.location_id ? Number(form.location_id) : null,
      }
      const created = await api<BulkIssueResult>('/transfers/bulk-issue', { method: 'POST', body: JSON.stringify(payload) })
      setResult(created)
      setStep('result')
      onComplete()
    } catch (caught) {
      setError(caught instanceof Error ? caught : new Error('request_failed'))
      setStep('confirm')
    } finally {
      setBusy(false)
    }
  }

  const download = (path: string, filename: string) => downloadApiFile(path, filename)
    .catch(() => setError(new Error('request_failed')))

  return (
    <ModalShell title={t('bulk.issue')} onClose={onClose} wide>
      {error?.message === 'selection_required'
        ? <div className="conflict-notice" role="alert"><strong>{t('bulk.selectAvailableError')}</strong></div>
        : <ConflictNotice error={error} />}
      {step === 'select' && (
        <>
          <div className="bulk-step-head">
            <div><b>{t('bulk.selectedCount', { count: selected.size })}</b><small>{t('bulk.unavailableHint')}</small></div>
            <div className="search small-search"><Search size={17} /><input aria-label={t('bulk.machineSearch')} value={query} onChange={(event) => setQuery(event.target.value)} placeholder={t('bulk.machineSearchPlaceholder')} /></div>
          </div>
          <IssueSelectionList items={filtered} selected={selected} onToggle={toggle} />
          <div className="form-grid bulk-fields">
            <label>{t('bulk.documentLanguage')}<select value={form.document_language} onChange={(event) => setField('document_language', event.target.value as IssueForm['document_language'])}><option value="bg">{t('language.bg')}</option><option value="en">{t('language.en')}</option><option value="ru">{t('language.ru')}</option></select></label>
            <label>{t('bulk.companyUnit')}<input value={form.company_unit} onChange={(event) => setField('company_unit', event.target.value)} /></label>
            <label>{t('bulk.department')}<input value={form.department} onChange={(event) => setField('department', event.target.value)} /></label>
            <label>{t('bulk.vessel')}<input value={form.vessel} onChange={(event) => setField('vessel', event.target.value)} /></label>
            <label>{t('bulk.dock')}<input value={form.dock} onChange={(event) => setField('dock', event.target.value)} /></label>
            <label>{t('bulk.pier')}<input value={form.pier} onChange={(event) => setField('pier', event.target.value)} /></label>
            <label>{t('bulk.workArea')}<input value={form.work_area} onChange={(event) => setField('work_area', event.target.value)} /></label>
            <label>{t('bulk.describedLocation')}<input value={form.location_text} onChange={(event) => setField('location_text', event.target.value)} /></label>
            <label>{t('bulk.systemLocation')}<select value={form.location_id} onChange={(event) => setField('location_id', event.target.value)}><option value="">{t('common.noChange')}</option>{locations.map((location) => <option key={location.id} value={location.id}>{location.name}</option>)}</select></label>
            <label>{t('bulk.handedOverBy')}<input value={form.handed_over_by} onChange={(event) => setField('handed_over_by', event.target.value)} /></label>
            <label>{t('bulk.acceptedBy')}<input value={form.accepted_by} onChange={(event) => setField('accepted_by', event.target.value)} /></label>
            <label className="wide">{t('bulk.equipment')}<textarea value={form.equipment} onChange={(event) => setField('equipment', event.target.value)} /></label>
            <label>{t('bulk.hoses')}<textarea value={form.hoses} onChange={(event) => setField('hoses', event.target.value)} /></label>
            <label>{t('bulk.nozzles')}<textarea value={form.nozzles} onChange={(event) => setField('nozzles', event.target.value)} /></label>
            <label>{t('bulk.guns')}<textarea value={form.guns} onChange={(event) => setField('guns', event.target.value)} /></label>
            <label>{t('bulk.accessories')}<textarea value={form.accessories} onChange={(event) => setField('accessories', event.target.value)} /></label>
            <label className="wide">{t('bulk.issueCondition')}<textarea value={form.condition_text} onChange={(event) => setField('condition_text', event.target.value)} /></label>
            <label className="wide">{t('common.notes')}<textarea value={form.remarks} onChange={(event) => setField('remarks', event.target.value)} /></label>
          </div>
          <div className="actions"><button className="secondary" onClick={onClose}>{t('common.cancel')}</button><button className="primary" onClick={continueToConfirm} disabled={!selected.size}>{t('bulk.reviewConfirm')}</button></div>
        </>
      )}
      {step === 'confirm' && (
        <>
          <ConfirmationSummary title={t('bulk.issueConfirmTitle')} machineNumbers={selectedItems.map((item) => item.machine_number)} rows={[
            [t('bulk.documentLanguage'), t(`language.${form.document_language}` as TranslationKey)],
            [t('bulk.companyUnit'), form.company_unit], [t('bulk.department'), form.department], [t('bulk.vessel'), form.vessel],
            [t('bulk.dock'), form.dock], [t('bulk.pier'), form.pier], [t('bulk.workArea'), form.work_area], [t('common.location'), form.location_text],
            [t('bulk.handedOverBy'), form.handed_over_by], [t('bulk.acceptedBy'), form.accepted_by], [t('bulk.equipment'), form.equipment],
            [t('bulk.hoses'), form.hoses], [t('bulk.nozzles'), form.nozzles], [t('bulk.guns'), form.guns], [t('bulk.accessories'), form.accessories],
            [t('bulk.issueCondition'), form.condition_text], [t('common.notes'), form.remarks],
          ]} />
          <p className="confirmation-warning">{t('bulk.atomicWarning')}</p>
          <div className="actions"><button className="secondary" onClick={() => setStep('select')} disabled={busy}>{t('common.back')}</button><button className="primary" onClick={submit} disabled={busy}>{busy ? t('bulk.issuing') : t('bulk.confirmIssue')}</button></div>
        </>
      )}
      {step === 'result' && result && <><IssueResult result={result} onDownload={download} /><div className="actions"><button className="primary" onClick={onClose}>{t('common.done')}</button></div></>}
    </ModalShell>
  )
}

function ReturnModal({ items, locations, onClose, onComplete }: {
  items: TransferAvailability[]
  locations: Location[]
  onClose: () => void
  onComplete: () => void
}) {
  const { t } = useI18n()
  const activeItems = items.filter((item) => item.active_transfer_id)
  const [drafts, setDrafts] = useState<Record<number, ReturnDraft>>({})
  const [query, setQuery] = useState('')
  const [documentLanguage, setDocumentLanguage] = useState<'bg' | 'en' | 'ru'>('bg')
  const [step, setStep] = useState<'edit' | 'confirm' | 'result'>('edit')
  const [result, setResult] = useState<BulkReturnResult | null>(null)
  const [error, setError] = useState<Error | null>(null)
  const [busy, setBusy] = useState(false)
  const filtered = activeItems.filter((item) => (
    `${item.machine_number} ${item.brand} ${item.batch_reference || ''} ${item.protocol_number || ''}`
      .toLowerCase()
      .includes(query.toLowerCase())
  ))

  const toggle = (item: TransferAvailability) => setDrafts((current) => {
    const next = { ...current }
    if (next[item.machine_id]) delete next[item.machine_id]
    else next[item.machine_id] = {
      transfer_id: item.active_transfer_id!,
      machine_id: item.machine_id,
      condition_text: '',
      result_text: '',
      notes: '',
      missing_equipment: '',
      damage: '',
      contamination: '',
      cleaning_required: false,
      inspection_required: true,
      repair_required: false,
      returned_by: '',
      accepted_by: '',
      location_id: '',
      next_status: 'INSPECTION',
    }
    return next
  })
  const update = <K extends keyof ReturnDraft>(machineId: number, field: K, value: ReturnDraft[K]) => setDrafts((current) => ({
    ...current,
    [machineId]: { ...current[machineId], [field]: value },
  }))
  const selectedItems = activeItems.filter((item) => drafts[item.machine_id])

  const confirm = (event: FormEvent) => {
    event.preventDefault()
    if (!selectedItems.length) {
      setError(new Error('selection_required'))
      return
    }
    if (Object.values(drafts).some((draft) => !draft.condition_text.trim() || !draft.result_text.trim())) {
      setError(new Error('details_required'))
      return
    }
    setError(null)
    setStep('confirm')
  }

  async function submit() {
    setBusy(true)
    setError(null)
    try {
      const payload = {
        document_language: documentLanguage,
        items: Object.values(drafts).map((draft) => ({
          ...draft,
          location_id: draft.location_id ? Number(draft.location_id) : null,
        })),
      }
      const completed = await api<BulkReturnResult>('/transfers/bulk-return', { method: 'POST', body: JSON.stringify(payload) })
      setResult(completed)
      setStep('result')
      onComplete()
    } catch (caught) {
      setError(caught instanceof Error ? caught : new Error('request_failed'))
      setStep('confirm')
    } finally {
      setBusy(false)
    }
  }

  const localValidationMessage = error?.message === 'selection_required'
    ? t('bulk.selectIssuedError')
    : error?.message === 'details_required'
      ? t('bulk.returnDetailsError')
      : null

  return (
    <ModalShell title={t('bulk.return')} onClose={onClose} wide>
      {localValidationMessage
        ? <div className="conflict-notice" role="alert"><strong>{localValidationMessage}</strong></div>
        : <ConflictNotice error={error} />}
      {step === 'edit' && (
        <form onSubmit={confirm}>
          <div className="bulk-step-head">
            <div><b>{t('bulk.selectedCount', { count: selectedItems.length })}</b><small>{t('bulk.mixedReturnHint')}</small></div>
            <div className="search small-search"><Search size={17} /><input aria-label={t('bulk.returnSearch')} value={query} onChange={(event) => setQuery(event.target.value)} placeholder={t('bulk.returnSearchPlaceholder')} /></div>
          </div>
          <div className="form-grid bulk-fields"><label>{t('bulk.documentLanguage')}<select value={documentLanguage} onChange={(event) => setDocumentLanguage(event.target.value as 'bg' | 'en' | 'ru')}><option value="bg">{t('language.bg')}</option><option value="en">{t('language.en')}</option><option value="ru">{t('language.ru')}</option></select></label></div>
          {!filtered.length && <div className="empty-state">{t('bulk.noActiveTransfers')}</div>}
          <div className="return-list">
            {filtered.map((item) => (
              <section key={item.machine_id} className={`return-item ${drafts[item.machine_id] ? 'selected' : ''}`}>
                <label className="return-select">
                  <input type="checkbox" aria-label={t('bulk.returnMachineAria', { number: item.machine_number })} checked={Boolean(drafts[item.machine_id])} onChange={() => toggle(item)} />
                  <span><b>{t('bulk.machineName', { number: item.machine_number })}</b><small>{item.brand} · {item.protocol_number} · {item.batch_reference || t('bulk.noBatch')}</small></span>
                  <span className="availability-pill blocked">{t('bulk.issued')}</span>
                </label>
                {drafts[item.machine_id] && (
                  <div className="form-grid return-fields">
                    <label>{t('bulk.nextStage')}<select value={drafts[item.machine_id].next_status} onChange={(event) => update(item.machine_id, 'next_status', event.target.value)}>{RETURN_STATUS_CODES.map((status) => <option value={status} key={status}>{statusText(t, status)}</option>)}</select></label>
                    <label>{t('common.location')}<select value={drafts[item.machine_id].location_id} onChange={(event) => update(item.machine_id, 'location_id', event.target.value)}><option value="">{t('common.noChange')}</option>{locations.map((location) => <option key={location.id} value={location.id}>{location.name}</option>)}</select></label>
                    <label>{t('bulk.returnedBy')}<input value={drafts[item.machine_id].returned_by} onChange={(event) => update(item.machine_id, 'returned_by', event.target.value)} /></label>
                    <label>{t('bulk.acceptedBy')}<input value={drafts[item.machine_id].accepted_by} onChange={(event) => update(item.machine_id, 'accepted_by', event.target.value)} /></label>
                    <label className="wide">{t('bulk.returnCondition')}<textarea required value={drafts[item.machine_id].condition_text} onChange={(event) => update(item.machine_id, 'condition_text', event.target.value)} /></label>
                    <label className="wide">{t('bulk.returnResult')}<textarea required value={drafts[item.machine_id].result_text} onChange={(event) => update(item.machine_id, 'result_text', event.target.value)} /></label>
                    <label className="wide">{t('bulk.missingEquipment')}<textarea value={drafts[item.machine_id].missing_equipment} onChange={(event) => update(item.machine_id, 'missing_equipment', event.target.value)} /></label>
                    <label>{t('bulk.damage')}<textarea value={drafts[item.machine_id].damage} onChange={(event) => update(item.machine_id, 'damage', event.target.value)} /></label>
                    <label>{t('bulk.contamination')}<textarea value={drafts[item.machine_id].contamination} onChange={(event) => update(item.machine_id, 'contamination', event.target.value)} /></label>
                    <label className="checkbox-row"><input type="checkbox" checked={drafts[item.machine_id].cleaning_required} onChange={(event) => update(item.machine_id, 'cleaning_required', event.target.checked)} />{t('bulk.cleaningRequired')}</label>
                    <label className="checkbox-row"><input type="checkbox" checked={drafts[item.machine_id].inspection_required} onChange={(event) => update(item.machine_id, 'inspection_required', event.target.checked)} />{t('bulk.inspectionRequired')}</label>
                    <label className="checkbox-row"><input type="checkbox" checked={drafts[item.machine_id].repair_required} onChange={(event) => update(item.machine_id, 'repair_required', event.target.checked)} />{t('bulk.repairRequired')}</label>
                    <label className="wide">{t('common.notes')}<textarea value={drafts[item.machine_id].notes} onChange={(event) => update(item.machine_id, 'notes', event.target.value)} /></label>
                  </div>
                )}
              </section>
            ))}
          </div>
          <div className="actions"><button type="button" className="secondary" onClick={onClose}>{t('common.cancel')}</button><button className="primary" disabled={!selectedItems.length}>{t('bulk.reviewConfirm')}</button></div>
        </form>
      )}
      {step === 'confirm' && (
        <>
          <ConfirmationSummary title={t('bulk.returnConfirmTitle')} machineNumbers={selectedItems.map((item) => item.machine_number)} rows={[[t('bulk.documentLanguage'), t(`language.${documentLanguage}` as TranslationKey)]]} />
          <div className="return-confirm-list">{selectedItems.map((item) => {
            const draft = drafts[item.machine_id]
            const requirements = [
              draft.cleaning_required ? t('bulk.cleaningRequired') : '',
              draft.inspection_required ? t('bulk.inspectionRequired') : '',
              draft.repair_required ? t('bulk.repairRequired') : '',
            ].filter(Boolean).join(' · ')
            return <div key={item.machine_id}>
              <b>{t('bulk.returnLine', { number: item.machine_number, status: statusText(t, draft.next_status) })}</b>
              <span>{draft.condition_text}</span><span>{draft.result_text}</span>
              {draft.missing_equipment && <span>{t('bulk.missingEquipment')}: {draft.missing_equipment}</span>}
              {draft.damage && <span>{t('bulk.damage')}: {draft.damage}</span>}
              {draft.contamination && <span>{t('bulk.contamination')}: {draft.contamination}</span>}
              {requirements && <span>{requirements}</span>}
            </div>
          })}</div>
          <p className="confirmation-warning">{t('bulk.noAutoReady')}</p>
          <div className="actions"><button className="secondary" onClick={() => setStep('edit')} disabled={busy}>{t('common.back')}</button><button className="primary" onClick={submit} disabled={busy}>{busy ? t('bulk.returning') : t('bulk.confirmReturn')}</button></div>
        </>
      )}
      {step === 'result' && result && (
        <div className="operation-result" role="status">
          <CheckCircle2 size={36} />
          <h4>{t('bulk.returnSuccess')}</h4>
          <div className="return-confirm-list">{result.returned.map((item) => <div key={item.transfer_id}><b>{t('bulk.machineName', { number: item.machine_number })}</b><span>{t('bulk.newStatus', { status: statusText(t, item.new_status) })}</span></div>)}</div>
          {result.batches.map((batch) => <BatchProgressCard key={batch.batch_id} batch={batch} />)}
          <div className="actions"><button className="primary" onClick={onClose}>{t('common.done')}</button></div>
        </div>
      )}
    </ModalShell>
  )
}

export function BatchProgressCard({ batch, onOpen }: { batch: BatchProgress; onOpen?: (batch: BatchProgress) => void }) {
  const { date, t } = useI18n()
  const returnedPercent = batch.total_machines ? Math.round((batch.returned_machines / batch.total_machines) * 100) : 0
  return (
    <article className="batch-card">
      <div><span className={`badge ${batch.still_issued_machines ? 'batch-active' : 'batch-complete'}`}>{statusText(t, batch.status, 'batch')}</span><h4>{batch.batch_reference}</h4>{batch.created_at && <small>{date(batch.created_at)}</small>}</div>
      <div className="batch-progress"><span style={{ width: `${returnedPercent}%` }} /><small>{t('bulk.returnedProgress', { returned: batch.returned_machines, issued: batch.still_issued_machines, total: batch.total_machines })}</small></div>
      {onOpen && <button className="secondary compact" onClick={() => onOpen(batch)}>{t('common.details')}</button>}
    </article>
  )
}

function BatchDetailsPanel({ details, onDownload }: { details: BatchDetails; onDownload: (path: string, filename: string) => void }) {
  const { t } = useI18n()
  return (
    <div className="batch-details">
      <button className="secondary" onClick={() => onDownload(details.zip_download_endpoint, `${details.batch_reference}-protocols.zip`)}><Archive size={16} />{t('bulk.zipProtocols')}</button>
      {details.transfers.map((transfer) => (
        <div key={transfer.transfer_id}>
          <span><b>{t('bulk.batchMachine', { number: transfer.machine_number })}</b><small>{transfer.brand} · {transfer.protocol_number}</small></span>
          <span className={`availability-pill ${transfer.is_active ? 'blocked' : 'available'}`}>{transfer.is_active ? t('transfers.stillIssued') : t('transfers.returned')}</span>
          <span>{transfer.documents.map((document: ProtocolDocument) => <button className="link" key={document.id} onClick={() => onDownload(document.download_endpoint, document.filename)}>{document.format.toUpperCase()}</button>)}</span>
        </div>
      ))}
    </div>
  )
}

export default function BulkTransfers({ onChanged }: BulkTransfersProps) {
  const { t } = useI18n()
  const [availabilityItems, setAvailability] = useState<TransferAvailability[]>([])
  const [locations, setLocations] = useState<Location[]>([])
  const [batches, setBatches] = useState<BatchProgress[]>([])
  const [details, setDetails] = useState<Record<number, BatchDetails>>({})
  const [mode, setMode] = useState<'issue' | 'return' | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<Error | null>(null)

  const load = async () => {
    setLoading(true)
    try {
      const [available, locationItems, batchItems] = await Promise.all([
        api<TransferAvailability[]>('/transfers/availability'),
        api<Location[]>('/locations'),
        api<BatchProgress[]>('/transfer-batches'),
      ])
      setAvailability(available)
      setLocations(locationItems)
      setBatches(batchItems)
      setError(null)
    } catch (caught) {
      setError(caught instanceof Error ? caught : new Error('request_failed'))
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { void load() }, [])
  const completed = () => {
    void load()
    onChanged()
  }
  const openBatch = async (batch: BatchProgress) => {
    if (details[batch.batch_id]) {
      setDetails((current) => {
        const next = { ...current }
        delete next[batch.batch_id]
        return next
      })
      return
    }
    try {
      const value = await api<BatchDetails>(`/transfer-batches/${batch.batch_id}`)
      setDetails((current) => ({ ...current, [batch.batch_id]: value }))
    } catch (caught) {
      setError(caught instanceof Error ? caught : new Error('request_failed'))
    }
  }
  const download = (path: string, filename: string) => downloadApiFile(path, filename)
    .catch(() => setError(new Error('request_failed')))

  return (
    <section className="bulk-workspace">
      {canOperateTransfers() && (
        <div className="bulk-actions"><button className="primary" onClick={() => setMode('issue')}><Send size={18} />{t('bulk.issue')}</button><button className="secondary emphasized" onClick={() => setMode('return')}><RotateCcw size={18} />{t('bulk.return')}</button></div>
      )}
      <ConflictNotice error={error} />
      <div className="panel batch-panel">
        <div className="panel-title"><div><h3>{t('bulk.batchProgressTitle')}</h3><p className="muted">{t('bulk.batchProgressSubtitle')}</p></div></div>
        {loading
          ? <div className="loading">{t('common.loading')}</div>
          : batches.length
            ? <div className="batch-list">{batches.map((batch) => <div key={batch.batch_id}><BatchProgressCard batch={batch} onOpen={openBatch} />{details[batch.batch_id] && <BatchDetailsPanel details={details[batch.batch_id]} onDownload={download} />}</div>)}</div>
            : <div className="empty-state">{t('bulk.noBatches')}</div>}
      </div>
      {mode === 'issue' && <IssueModal items={availabilityItems} locations={locations} onClose={() => setMode(null)} onComplete={completed} />}
      {mode === 'return' && <ReturnModal items={availabilityItems} locations={locations} onClose={() => setMode(null)} onComplete={completed} />}
    </section>
  )
}
