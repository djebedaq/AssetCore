import { type FormEvent, type ReactNode, useEffect, useMemo, useState } from 'react'
import { Archive, Ban, CheckCircle2, Download, RotateCcw, Search, Send, ShieldAlert, X } from 'lucide-react'
import { ApiError, api, downloadApiFile } from './api'
import { statusText, useI18n, type TranslationKey } from './i18n'
import { hasPermission } from './permissions'
import SignaturePage from './SignaturePage'
import type {
  BatchDetails,
  BatchProgress,
  CancelTransferBatchResponse,
  BulkIssueResult,
  BulkReturnResult,
  Location,
  ProtocolDocument,
  SigningTask,
  TransferAvailability,
} from './types'

type BulkTransfersProps = { onChanged: () => void }

type ChecklistCondition = 'GOOD' | 'SATISFACTORY' | 'REPAIR' | 'FAULTY' | 'MISSING' | 'NA'
type ChecklistItem = { code: string; condition: ChecklistCondition; note: string; length_m: string }
const CHECKLIST_ITEMS: ChecklistItem[] = [
  'pump', 'supply_hose', 'hp_hose', 'gun', 'nozzle', 'tips', 'cable', 'plug', 'chassis', 'body',
].map((code) => ({ code, condition: 'GOOD' as ChecklistCondition, note: '', length_m: '' }))
const LENGTH_CODES = new Set(['supply_hose', 'hp_hose', 'cable'])

type IssueForm = {
  usage_text: string
  location_id: string
  recipient_first_name: string
  recipient_middle_name: string
  recipient_last_name: string
  recipient_is_foreign_person: boolean
  recipient_name_exception_reason: string
  condition_text: string
  remarks: string
  checklist: ChecklistItem[]
}

const EMPTY_ISSUE_FORM: IssueForm = {
  usage_text: '',
  location_id: '',
  recipient_first_name: '',
  recipient_middle_name: '',
  recipient_last_name: '',
  recipient_is_foreign_person: false,
  recipient_name_exception_reason: '',
  condition_text: '',
  remarks: '',
  checklist: CHECKLIST_ITEMS.map((item) => ({ ...item })),
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
  next_status: 'READY' | 'REPAIR'
  checklist: ChecklistItem[]
}

function canOperateTransfers(): boolean {
  return hasPermission('transfers.create', 'transfers.return')
}

function canCancelTransfers(): boolean {
  return hasPermission('transfers.create')
}

function localizedErrorKey(error: Error): TranslationKey {
  if (!(error instanceof ApiError)) return 'errors.generic'
  if (error.status === 403) return 'errors.permissionDenied'
  if (error.status === 404) return 'errors.notFound'
  if (error.code === 'issue_conflict' || error.code === 'concurrent_issue_conflict') return 'errors.issueConflict'
  if (error.code === 'return_conflict' || error.code === 'return_without_active_transfer') return 'errors.returnConflict'
  if (error.code === 'document_template_unavailable') return 'errors.templateUnavailable'
  if (error.code === 'validation_error') return 'errors.validation'
  if (error.code === 'batch_not_pending') return 'errors.batchNotPending'
  if (error.code === 'batch_not_found') return 'errors.notFound'
  return 'errors.generic'
}


function ConditionChecklist({ items, onChange }: { items: ChecklistItem[]; onChange: (items: ChecklistItem[]) => void }) {
  const { t } = useI18n()
  const conditions: ChecklistCondition[] = ['GOOD', 'SATISFACTORY', 'REPAIR', 'FAULTY', 'MISSING', 'NA']
  const update = (index: number, patch: Partial<ChecklistItem>) => onChange(items.map((item, itemIndex) => itemIndex === index ? { ...item, ...patch } : item))
  return <fieldset className="wide condition-checklist"><legend>{t('bulk.checklist.title')}</legend>{items.map((item, index) => <div className="checklist-row" key={item.code}><strong>{t(`bulk.checklist.item.${item.code}` as TranslationKey)}</strong><select value={item.condition} onChange={(event) => update(index, { condition: event.target.value as ChecklistCondition })}>{conditions.map((value) => <option key={value} value={value}>{t(`bulk.checklist.condition.${value}` as TranslationKey)}</option>)}</select>{LENGTH_CODES.has(item.code) && <input type="number" min="0" step="0.1" placeholder={t('bulk.checklist.lengthPlaceholder')} value={item.length_m} onChange={(event) => update(index, { length_m: event.target.value })} />}<input placeholder={t('bulk.checklist.notePlaceholder')} value={item.note} onChange={(event) => update(index, { note: event.target.value })} /></div>)}</fieldset>
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
  const diagnosticId = error instanceof ApiError && typeof error.data.diagnostic_id === 'string'
    ? error.data.diagnostic_id
    : null
  const diagnosticStage = error instanceof ApiError && typeof error.data.stage_label === 'string'
    ? error.data.stage_label
    : error instanceof ApiError && typeof error.data.stage === 'string'
      ? error.data.stage
      : null
  const serverMessage = error instanceof ApiError
    && error.code === 'bulk_return_internal_error'
    && typeof error.data.message === 'string'
      ? error.data.message
      : null
  return (
    <div className="conflict-notice" role="alert">
      <strong>{serverMessage || t(localizedErrorKey(error))}</strong>
      {diagnosticId && <p><b>{t('bulk.diagnosticCode')}:</b> <code>{diagnosticId}</code>{diagnosticStage ? <> · <b>{t('bulk.diagnosticStage')}:</b> {diagnosticStage}</> : null}</p>}
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

export function CancelBatchModal({ batch, onClose, onCancelled }: {
  batch: Pick<BatchDetails, 'batch_id' | 'batch_reference' | 'operation' | 'awaiting_signature_machines' | 'total_machines'>
  onClose: () => void
  onCancelled: (result: CancelTransferBatchResponse) => void
}) {
  const { t } = useI18n()
  const [reason, setReason] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<Error | null>(null)
  const [result, setResult] = useState<CancelTransferBatchResponse | null>(null)
  const trimmedReason = reason.trim()
  const isReturn = batch.operation === 'RETURN'

  async function submit(event: FormEvent) {
    event.preventDefault()
    if (trimmedReason.length < 3) {
      setError(new Error('reason_required'))
      return
    }
    setBusy(true)
    setError(null)
    try {
      const cancelled = await api<CancelTransferBatchResponse>(`/transfer-batches/${batch.batch_id}/cancel`, {
        method: 'POST',
        body: JSON.stringify({ reason: trimmedReason }),
      })
      setResult(cancelled)
      onCancelled(cancelled)
    } catch (caught) {
      setError(caught instanceof Error ? caught : new Error('request_failed'))
    } finally {
      setBusy(false)
    }
  }

  return (
    <ModalShell title={t('bulk.cancelPendingTitle')} onClose={busy ? () => undefined : onClose}>
      {!result ? <form className="cancel-batch-form" onSubmit={submit}>
        <div className="cancel-batch-warning" role="alert">
          <ShieldAlert size={28} />
          <div>
            <strong>{t('bulk.cancelPendingWarning')}</strong>
            <p>{isReturn ? t('bulk.cancelReturnEffect') : t('bulk.cancelIssueEffect')}</p>
          </div>
        </div>
        <dl className="cancel-batch-summary">
          <div><dt>{t('bulk.batchReference')}</dt><dd>{batch.batch_reference}</dd></div>
          <div><dt>{t('common.machines')}</dt><dd>{batch.total_machines}</dd></div>
          <div><dt>{t('bulk.awaitingSignature')}</dt><dd>{batch.awaiting_signature_machines}</dd></div>
        </dl>
        <label className="cancel-reason-label" htmlFor={`cancel-reason-${batch.batch_id}`}>{t('bulk.cancelReason')}
          <textarea
            id={`cancel-reason-${batch.batch_id}`}
            aria-describedby={`cancel-reason-hint-${batch.batch_id}`}
            autoFocus
            required
            minLength={3}
            maxLength={1000}
            value={reason}
            onChange={(event) => setReason(event.target.value)}
            placeholder={t('bulk.cancelReasonPlaceholder')}
          />
        </label>
        <small id={`cancel-reason-hint-${batch.batch_id}`}>{t('bulk.cancelReasonHint')}</small>
        {error && <div className="error" role="alert"><strong>{error.message === 'reason_required' ? t('bulk.cancelReasonRequired') : t(localizedErrorKey(error))}</strong></div>}
        <div className="actions">
          <button type="button" className="secondary" onClick={onClose} disabled={busy}>{t('common.back')}</button>
          <button className="danger" disabled={busy || trimmedReason.length < 3}><Ban size={17} />{busy ? t('bulk.cancelling') : t('bulk.cancelConfirm')}</button>
        </div>
      </form> : <div className="operation-result cancel-result" role="status">
        <CheckCircle2 size={38} />
        <h4>{t('bulk.cancelSuccess')}</h4>
        <p>{result.batch_reference}</p>
        <div className="cancel-result-grid">
          <span><b>{result.cancelled_transfers}</b>{t('bulk.cancelledTransfers')}</span>
          <span><b>{result.invalidated_signing_sessions}</b>{t('bulk.invalidatedSessions')}</span>
        </div>
        <p className="muted">{isReturn ? t('bulk.cancelReturnComplete') : t('bulk.cancelIssueComplete')}</p>
        <button className="primary" onClick={onClose}>{t('common.done')}</button>
      </div>}
    </ModalShell>
  )
}

export function IssueResult({ result, onDownload, onCancel }: {
  result: BulkIssueResult
  onDownload: (path: string, filename: string) => void
  onCancel?: () => void
}) {
  const { t } = useI18n()
  const completed = result.transfers.every((item) => item.workflow_status === 'COMPLETED')
  const cancelled = result.transfers.every((item) => item.workflow_status === 'CANCELLED')
  return (
    <div className="operation-result" role="status">
      {completed && <CheckCircle2 size={36} />}
      <h4>{completed ? t('bulk.issueSuccess') : cancelled ? t('bulk.cancelSuccess') : t('bulk.awaitingSignature')}</h4>
      <p>{t('bulk.batchLabel', { reference: result.batch_reference })}</p>
      <div className="result-actions"><button className="primary" disabled={!completed} onClick={() => onDownload(result.zip_download_endpoint, `${result.batch_reference}-protocols.zip`)}>
        <Archive size={17} />{t('bulk.downloadAllZip')}
      </button>{!completed && !cancelled && onCancel && <button className="danger" onClick={onCancel}><Ban size={17} />{t('bulk.cancelPendingAction')}</button>}</div>
      <div className="result-protocols">
        <h4>{t('bulk.createdProtocols')}</h4>
        {result.transfers.map((item) => (
          <div key={item.transfer_id}>
            <span><b>{t('bulk.machineName', { number: item.machine_number })}</b><small>{item.protocol_number}</small></span>
            <span>{completed && item.documents.map((document) => (
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
  const [step, setStep] = useState<'select' | 'confirm' | 'sign' | 'result'>('select')
  const [result, setResult] = useState<BulkIssueResult | null>(null)
  const [signingTasks, setSigningTasks] = useState<SigningTask[]>([])
  const [signingIndex, setSigningIndex] = useState(0)
  const [error, setError] = useState<Error | null>(null)
  const [busy, setBusy] = useState(false)
  const [cancelOpen, setCancelOpen] = useState(false)

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
    const foreignExceptionInvalid = form.recipient_is_foreign_person
      && !form.recipient_middle_name.trim()
      && form.recipient_name_exception_reason.trim().length < 10
    if (!form.recipient_first_name.trim() || !form.recipient_last_name.trim()
      || (!form.recipient_is_foreign_person && !form.recipient_middle_name.trim())
      || foreignExceptionInvalid) {
      setError(new Error('recipient_required'))
      return
    }
    if (!form.location_id || !form.usage_text.trim() || !form.condition_text.trim()) {
      setError(new Error('issue_fields_required'))
      return
    }
    setError(null)
    setStep('confirm')
  }

  async function submit() {
    setBusy(true)
    setError(null)
    try {
      const {
        recipient_first_name, recipient_middle_name, recipient_last_name,
        recipient_is_foreign_person, recipient_name_exception_reason,
      } = form
      const payload = {
        machine_ids: [...selected],
        document_language: 'bg',
        usage_text: form.usage_text.trim(),
        location_id: Number(form.location_id),
        condition_text: form.condition_text.trim(),
        remarks: form.remarks.trim() || null,
        checklist: form.checklist.map((item) => ({ ...item, length_m: item.length_m === '' ? null : Number(item.length_m), note: item.note || null })),
        recipient: {
          first_name: recipient_first_name,
          middle_name: recipient_middle_name || null,
          last_name: recipient_last_name,
          is_foreign_person: recipient_is_foreign_person,
          name_exception_reason: recipient_name_exception_reason || null,
        },
      }
      const created = await api<BulkIssueResult>('/transfers/bulk-issue', { method: 'POST', body: JSON.stringify(payload) })
      setResult(created)
      const tasks = created.signing_tasks.length
        ? created.signing_tasks
        : created.transfers.flatMap((item) => item.signing_tasks)
      setSigningTasks(tasks)
      setSigningIndex(0)
      setStep(tasks.length ? 'sign' : 'result')
      if (!tasks.length) onComplete()
    } catch (caught) {
      setError(caught instanceof Error ? caught : new Error('request_failed'))
      setStep('confirm')
    } finally {
      setBusy(false)
    }
  }

  const download = (path: string, filename: string) => downloadApiFile(path, filename)
    .catch(() => setError(new Error('request_failed')))

  const finishSignature = (outcome: 'DONE' | 'REJECTED') => {
    if (outcome === 'REJECTED') {
      setError(new Error('signature_cancelled'))
      setStep('result')
      return
    }
    const next = signingIndex + 1
    if (next < signingTasks.length) setSigningIndex(next)
    else {
      setResult((current) => current ? {
        ...current,
        message: t('bulk.issueSuccess'),
        transfers: current.transfers.map((item) => ({ ...item, workflow_status: 'COMPLETED' })),
      } : current)
      setStep('result')
      onComplete()
    }
  }

  return (
    <ModalShell title={t('bulk.issue')} onClose={onClose} wide>
      {error?.message === 'selection_required' || error?.message === 'recipient_required' || error?.message === 'issue_fields_required' || error?.message === 'signature_cancelled'
        ? <div className="conflict-notice" role="alert"><strong>{error.message === 'selection_required' ? t('bulk.selectAvailableError') : error.message === 'recipient_required' ? t('bulk.recipientRequired') : error.message === 'issue_fields_required' ? t('bulk.issueFieldsRequired') : t('bulk.signatureCancelled')}</strong></div>
        : <ConflictNotice error={error} />}
      {step === 'select' && (
        <>
          <div className="bulk-step-head">
            <div><b>{t('bulk.selectedCount', { count: selected.size })}</b><small>{t('bulk.unavailableHint')}</small></div>
            <div className="search small-search"><Search size={17} /><input aria-label={t('bulk.machineSearch')} value={query} onChange={(event) => setQuery(event.target.value)} placeholder={t('bulk.machineSearchPlaceholder')} /></div>
          </div>
          <IssueSelectionList items={filtered} selected={selected} onToggle={toggle} />
          <div className="form-grid bulk-fields">
            <label>{t('bulk.systemLocation')}<select required value={form.location_id} onChange={(event) => setField('location_id', event.target.value)}><option value="">{t('bulk.selectLocation')}</option>{locations.filter((location) => location.is_active).map((location) => <option key={location.id} value={location.id}>{location.name}</option>)}</select></label>
            <label className="wide">{t('bulk.usageText')}<textarea required value={form.usage_text} onChange={(event) => setField('usage_text', event.target.value)} placeholder={t('bulk.usageExample')} /></label>
            <fieldset className="wide party-fields"><legend>{t('bulk.recipient')}</legend><div className="form-grid three-columns">
              <label>{t('profile.firstName')}<input required value={form.recipient_first_name} onChange={(event) => setField('recipient_first_name', event.target.value)} /></label>
              <label>{t('profile.middleName')}<input required={!form.recipient_is_foreign_person} value={form.recipient_middle_name} onChange={(event) => setField('recipient_middle_name', event.target.value)} /></label>
              <label>{t('profile.lastName')}<input required value={form.recipient_last_name} onChange={(event) => setField('recipient_last_name', event.target.value)} /></label>
              <label className="checkbox-row"><input type="checkbox" checked={form.recipient_is_foreign_person} onChange={(event) => setField('recipient_is_foreign_person', event.target.checked)} />{t('bulk.foreignPerson')}</label>
              {form.recipient_is_foreign_person && <label className="wide">{t('profile.exceptionReason')}<textarea required minLength={10} value={form.recipient_name_exception_reason} onChange={(event) => setField('recipient_name_exception_reason', event.target.value)} /></label>}
            </div></fieldset>
            <ConditionChecklist items={form.checklist} onChange={(checklist) => setField('checklist', checklist)} />
            <label className="wide">{t('bulk.issueCondition')}<textarea required value={form.condition_text} onChange={(event) => setField('condition_text', event.target.value)} /></label>
            <label className="wide">{t('common.notes')}<textarea value={form.remarks} onChange={(event) => setField('remarks', event.target.value)} /></label>
          </div>
          <div className="actions"><button className="secondary" onClick={onClose}>{t('common.cancel')}</button><button className="primary" onClick={continueToConfirm} disabled={!selected.size}>{t('bulk.reviewConfirm')}</button></div>
        </>
      )}
      {step === 'confirm' && (
        <>
          <ConfirmationSummary title={t('bulk.issueConfirmTitle')} machineNumbers={selectedItems.map((item) => item.machine_number)} rows={[
            [t('common.location'), locations.find((location) => String(location.id) === form.location_id)?.name || ''],
            [t('bulk.usageText'), form.usage_text],
            [t('bulk.recipient'), [form.recipient_first_name, form.recipient_middle_name, form.recipient_last_name].filter(Boolean).join(' ')],
            [t('bulk.issueCondition'), form.condition_text], [t('common.notes'), form.remarks],
          ]} />
          <p className="confirmation-warning">{t('bulk.atomicWarning')}</p>
          <div className="actions"><button className="secondary" onClick={() => setStep('select')} disabled={busy}>{t('common.back')}</button><button className="primary" onClick={submit} disabled={busy}>{busy ? t('bulk.issuing') : t('bulk.confirmIssue')}</button></div>
        </>
      )}
      {step === 'sign' && signingTasks[signingIndex] && <section className="integrated-signing"><div className="signing-progress"><strong>{t('bulk.signatureProgress', { current: signingIndex + 1, total: signingTasks.length })}</strong><span>{signingTasks[signingIndex].signer_name} · {signingTasks[signingIndex].operation_role}</span></div><SignaturePage embedded token={signingTasks[signingIndex].signing_token} onFinished={finishSignature} /></section>}
      {step === 'result' && result && <><IssueResult result={result} onDownload={download} onCancel={() => setCancelOpen(true)} /><div className="actions"><button className="primary" onClick={onClose}>{t('common.done')}</button></div></>}
      {cancelOpen && result && <CancelBatchModal batch={{ batch_id: result.batch_id, batch_reference: result.batch_reference, operation: 'ISSUE', awaiting_signature_machines: result.transfers.filter((item) => item.workflow_status === 'AWAITING_SIGNATURE').length, total_machines: result.transfers.length }} onClose={() => setCancelOpen(false)} onCancelled={() => { setResult((current) => current ? { ...current, transfers: current.transfers.map((item) => ({ ...item, workflow_status: 'CANCELLED' })) } : current); setSigningTasks([]); setError(null); onComplete() }} />}
    </ModalShell>
  )
}

export function ReturnModal({ items, onClose, onComplete }: {
  items: TransferAvailability[]
  onClose: () => void
  onComplete: () => void
}) {
  const { t } = useI18n()
  const activeItems = items.filter((item) => item.returnable)
  const [drafts, setDrafts] = useState<Record<number, ReturnDraft>>({})
  const [query, setQuery] = useState('')
  const [step, setStep] = useState<'edit' | 'confirm' | 'sign' | 'result'>('edit')
  const [result, setResult] = useState<BulkReturnResult | null>(null)
  const [signingTasks, setSigningTasks] = useState<SigningTask[]>([])
  const [signingIndex, setSigningIndex] = useState(0)
  const [error, setError] = useState<Error | null>(null)
  const [busy, setBusy] = useState(false)
  const [cancelOpen, setCancelOpen] = useState(false)
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
      next_status: 'READY',
      checklist: CHECKLIST_ITEMS.map((entry) => ({ ...entry })),
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
        document_language: 'bg',
        items: Object.values(drafts).map((draft) => ({
          ...draft,
          checklist: draft.checklist.map((entry) => ({ ...entry, length_m: entry.length_m === '' ? null : Number(entry.length_m), note: entry.note || null })),
        })),
      }
      const completed = await api<BulkReturnResult>('/transfers/bulk-return', { method: 'POST', body: JSON.stringify(payload) })
      setResult(completed)
      const tasks = completed.signing_tasks.length
        ? completed.signing_tasks
        : completed.returned.flatMap((item) => item.signing_tasks)
      setSigningTasks(tasks)
      setSigningIndex(0)
      setStep(tasks.length ? 'sign' : 'result')
      if (!tasks.length) onComplete()
    } catch (caught) {
      setError(caught instanceof Error ? caught : new Error('request_failed'))
      setStep('confirm')
    } finally {
      setBusy(false)
    }
  }

  const finishSignature = (outcome: 'DONE' | 'REJECTED') => {
    if (outcome === 'REJECTED') {
      setError(new Error('signature_cancelled'))
      setStep('result')
      return
    }
    const next = signingIndex + 1
    if (next < signingTasks.length) setSigningIndex(next)
    else {
      setResult((current) => current ? {
        ...current,
        message: t('bulk.returnSuccess'),
        returned: current.returned.map((item) => ({ ...item, workflow_status: 'COMPLETED' })),
      } : current)
      setStep('result')
      onComplete()
    }
  }

  const localValidationMessage = error?.message === 'selection_required'
    ? t('bulk.selectIssuedError')
    : error?.message === 'details_required'
      ? t('bulk.returnDetailsError')
      : error?.message === 'signature_cancelled'
        ? t('bulk.signatureCancelled')
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
                    <fieldset className="wide return-outcome"><legend>{t('bulk.afterReturn')}</legend><label><input type="radio" name={`return-outcome-${item.machine_id}`} value="READY" checked={drafts[item.machine_id].next_status === 'READY'} onChange={() => update(item.machine_id, 'next_status', 'READY')} />{t('bulk.outcomeReady')}</label><label><input type="radio" name={`return-outcome-${item.machine_id}`} value="REPAIR" checked={drafts[item.machine_id].next_status === 'REPAIR'} onChange={() => update(item.machine_id, 'next_status', 'REPAIR')} />{t('bulk.outcomeRepair')}</label></fieldset>
                    <div className="wide immutable-recipient"><b>{t('bulk.returnedBy')}:</b> {item.current_recipient_or_location || t('common.noValue')}</div>
                    <ConditionChecklist items={drafts[item.machine_id].checklist} onChange={(checklist) => update(item.machine_id, 'checklist', checklist)} />
                    <label className="wide">{t('bulk.returnCondition')}<textarea required value={drafts[item.machine_id].condition_text} onChange={(event) => update(item.machine_id, 'condition_text', event.target.value)} /></label>
                    <label className="wide">{t('bulk.returnResult')}<textarea required value={drafts[item.machine_id].result_text} onChange={(event) => update(item.machine_id, 'result_text', event.target.value)} /></label>
                    <label className="wide">{t('bulk.missingEquipment')}<textarea value={drafts[item.machine_id].missing_equipment} onChange={(event) => update(item.machine_id, 'missing_equipment', event.target.value)} /></label>
                    <label>{t('bulk.damage')}<textarea value={drafts[item.machine_id].damage} onChange={(event) => update(item.machine_id, 'damage', event.target.value)} /></label>
                    <label>{t('bulk.contamination')}<textarea value={drafts[item.machine_id].contamination} onChange={(event) => update(item.machine_id, 'contamination', event.target.value)} /></label>
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
          <ConfirmationSummary title={t('bulk.returnConfirmTitle')} machineNumbers={selectedItems.map((item) => item.machine_number)} rows={[]} />
          <div className="return-confirm-list">{selectedItems.map((item) => {
            const draft = drafts[item.machine_id]
            return <div key={item.machine_id}>
              <b>{t('bulk.returnLine', { number: item.machine_number, status: statusText(t, draft.next_status) })}</b>
              <span>{draft.condition_text}</span><span>{draft.result_text}</span>
              {draft.missing_equipment && <span>{t('bulk.missingEquipment')}: {draft.missing_equipment}</span>}
              {draft.damage && <span>{t('bulk.damage')}: {draft.damage}</span>}
              {draft.contamination && <span>{t('bulk.contamination')}: {draft.contamination}</span>}
            </div>
          })}</div>
          <p className="confirmation-warning">{t('bulk.returnOutcomeWarning')}</p>
          <div className="actions"><button className="secondary" onClick={() => setStep('edit')} disabled={busy}>{t('common.back')}</button><button className="primary" onClick={submit} disabled={busy}>{busy ? t('bulk.returning') : t('bulk.confirmReturn')}</button></div>
        </>
      )}
      {step === 'sign' && signingTasks[signingIndex] && <section className="integrated-signing"><div className="signing-progress"><strong>{t('bulk.signatureProgress', { current: signingIndex + 1, total: signingTasks.length })}</strong><span>{signingTasks[signingIndex].signer_name} · {signingTasks[signingIndex].operation_role}</span></div><SignaturePage embedded token={signingTasks[signingIndex].signing_token} onFinished={finishSignature} /></section>}
      {step === 'result' && result && (
        <div className="operation-result" role="status">
          {result.returned.every((item) => item.workflow_status === 'COMPLETED') && <CheckCircle2 size={36} />}
          <h4>{result.returned.every((item) => item.workflow_status === 'COMPLETED') ? t('bulk.returnSuccess') : result.returned.every((item) => item.workflow_status === 'CANCELLED') ? t('bulk.cancelSuccess') : t('bulk.awaitingSignature')}</h4>
          <div className="return-confirm-list">{result.returned.map((item) => <div key={item.transfer_id}><b>{t('bulk.machineName', { number: item.machine_number })}</b><span>{item.workflow_status === 'COMPLETED' ? t('bulk.newStatus', { status: statusText(t, item.new_status) }) : item.workflow_status === 'CANCELLED' ? t('status.cancelled') : t('bulk.awaitingSignature')}</span>{item.workflow_status === 'COMPLETED' && <span>{item.documents.map((document) => <button key={document.id} className="secondary compact" onClick={() => void downloadApiFile(document.download_endpoint, document.filename)}><Download size={15} />{document.format.toUpperCase()}</button>)}</span>}</div>)}</div>
          {result.batches.map((batch) => <BatchProgressCard key={batch.batch_id} batch={batch} />)}
          <div className="actions">{!result.returned.every((item) => item.workflow_status === 'COMPLETED' || item.workflow_status === 'CANCELLED') && <button className="danger" onClick={() => setCancelOpen(true)}><Ban size={17} />{t('bulk.cancelPendingAction')}</button>}<button className="primary" onClick={onClose}>{t('common.done')}</button></div>
        </div>
      )}
      {cancelOpen && result && <CancelBatchModal batch={{ batch_id: result.batch_id, batch_reference: result.batch_reference, operation: 'RETURN', awaiting_signature_machines: result.returned.filter((item) => item.workflow_status === 'AWAITING_SIGNATURE').length, total_machines: result.returned.length }} onClose={() => setCancelOpen(false)} onCancelled={() => { setResult((current) => current ? { ...current, returned: current.returned.map((item) => ({ ...item, workflow_status: 'CANCELLED' })) } : current); setSigningTasks([]); setError(null); onComplete() }} />}
    </ModalShell>
  )
}

export function BatchProgressCard({ batch, onOpen, onCancel }: { batch: BatchProgress; onOpen?: (batch: BatchProgress) => void; onCancel?: (batch: BatchProgress) => void }) {
  const { date, t } = useI18n()
  const returnedPercent = batch.total_machines ? Math.round((batch.returned_machines / batch.total_machines) * 100) : 0
  return (
    <article className="batch-card">
      <div><span className={`badge ${batch.still_issued_machines ? 'batch-active' : 'batch-complete'}`}>{statusText(t, batch.status, 'batch')}</span><h4>{batch.machine_numbers.map((number) => `№${number}`).join(', ')}</h4><small>{t('bulk.technicalReference')}: {batch.batch_reference}</small>{batch.created_at && <small>{date(batch.created_at)}</small>}{batch.awaiting_signature_machines > 0 && <small className="muted batch-awaiting">{t('bulk.awaitingSignatureCount', { count: batch.awaiting_signature_machines })}</small>}</div>
      <div className="batch-progress"><span style={{ width: `${returnedPercent}%` }} /><small>{t('bulk.returnedProgress', { returned: batch.returned_machines, issued: batch.still_issued_machines, total: batch.total_machines })}</small></div>
      <div className="batch-card-actions">{batch.awaiting_signature_machines > 0 && onCancel && <button className="danger compact" onClick={() => onCancel(batch)}><Ban size={15} />{t('bulk.cancelPendingAction')}</button>}{onOpen && <button className="secondary compact" onClick={() => onOpen(batch)}>{t('common.details')}</button>}</div>
    </article>
  )
}

export function BatchDetailsPanel({ details, onDownload, onCancel }: { details: BatchDetails; onDownload: (path: string, filename: string) => void; onCancel?: (details: BatchDetails) => void }) {
  const { t } = useI18n()
  const hasFinalDocuments = details.transfers.some((transfer) => transfer.issue_status === 'COMPLETED' || transfer.return_status === 'COMPLETED')
  return (
    <div className="batch-details">
      <div className="batch-detail-actions"><button className="secondary" disabled={!hasFinalDocuments} onClick={() => onDownload(details.zip_download_endpoint, `${details.batch_reference}-protocols.zip`)}><Archive size={16} />{hasFinalDocuments ? t('bulk.zipProtocols') : t('bulk.awaitingSignature')}</button>{details.awaiting_signature_machines > 0 && onCancel && <button className="danger" onClick={() => onCancel(details)}><Ban size={16} />{t('bulk.cancelPendingAction')}</button>}</div>
      {details.transfers.map((transfer) => (
        <div key={transfer.transfer_id}>
          <span><b>{t('bulk.batchMachine', { number: transfer.machine_number })}</b><small>{transfer.brand} · {transfer.protocol_number}</small></span>
          <span className={`availability-pill ${transfer.is_active ? 'blocked' : 'available'}`}>{transfer.issue_status === 'AWAITING_SIGNATURE' || transfer.return_status === 'AWAITING_SIGNATURE' ? t('bulk.awaitingSignature') : transfer.is_active ? t('transfers.stillIssued') : t('transfers.returned')}</span>
          <section className="transfer-document-group"><b>{t('bulk.issueProtocol')}</b><span>{transfer.issue_status === 'COMPLETED' ? transfer.issue_documents.map((document: ProtocolDocument) => <button className="link" key={document.id} onClick={() => onDownload(document.download_endpoint, document.filename)}>{document.format.toUpperCase()}</button>) : t('bulk.awaitingSignature')}</span></section>
          <section className="transfer-document-group"><b>{t('bulk.returnProtocol')}</b><span>{transfer.return_status === 'COMPLETED' ? transfer.return_documents.map((document: ProtocolDocument) => <button className="link" key={document.id} onClick={() => onDownload(document.download_endpoint, document.filename)}>{document.format.toUpperCase()}</button>) : t('bulk.returnNotCompleted')}</span></section>
        </div>
      ))}
    </div>
  )
}

export default function BulkTransfers({ onChanged }: BulkTransfersProps) {
  const { t } = useI18n()
  const allowCancel = canCancelTransfers()
  const [availabilityItems, setAvailability] = useState<TransferAvailability[]>([])
  const [locations, setLocations] = useState<Location[]>([])
  const [batches, setBatches] = useState<BatchProgress[]>([])
  const [details, setDetails] = useState<Record<number, BatchDetails>>({})
  const [mode, setMode] = useState<'issue' | 'return' | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<Error | null>(null)
  const [cancelBatch, setCancelBatch] = useState<BatchDetails | null>(null)

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
  const requestCancel = async (batch: BatchProgress | BatchDetails) => {
    try {
      const value: BatchDetails = 'transfers' in batch ? batch : details[batch.batch_id] || await api<BatchDetails>(`/transfer-batches/${batch.batch_id}`)
      setDetails((current) => ({ ...current, [value.batch_id]: value }))
      setCancelBatch(value)
      setError(null)
    } catch (caught) {
      setError(caught instanceof Error ? caught : new Error('request_failed'))
    }
  }
  const cancelled = () => {
    setDetails({})
    void load()
    onChanged()
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
            ? <div className="batch-list">{batches.map((batch) => <div key={batch.batch_id}><BatchProgressCard batch={batch} onOpen={openBatch} onCancel={allowCancel ? (value) => void requestCancel(value) : undefined} />{details[batch.batch_id] && <BatchDetailsPanel details={details[batch.batch_id]} onDownload={download} onCancel={allowCancel ? (value) => void requestCancel(value) : undefined} />}</div>)}</div>
            : <div className="empty-state">{t('bulk.noBatches')}</div>}
      </div>
      {mode === 'issue' && <IssueModal items={availabilityItems} locations={locations} onClose={() => setMode(null)} onComplete={completed} />}
      {mode === 'return' && <ReturnModal items={availabilityItems} onClose={() => setMode(null)} onComplete={completed} />}
      {cancelBatch && <CancelBatchModal batch={cancelBatch} onClose={() => setCancelBatch(null)} onCancelled={cancelled} />}
    </section>
  )
}
