import { useMemo, useState } from 'react'
import { Search } from 'lucide-react'
import { downloadApiFile } from '../../api'
import { statusText, useI18n } from '../../i18n'
import type { BulkIssueResult, Location, SigningTask, TransferAvailability } from '../../types'
import { buildIssuePayload, EMPTY_ISSUE_FORM, type IssueForm } from './transferState'
import { transferApi } from './transferApi'
import { ConditionChecklist } from './TransferChecklist'
import { ModalShell } from './TransferModalShell'
import { ConflictNotice } from './TransferConflictNotice'
import { IssueSelectionList } from './IssueSelectionList'
import { ConfirmationSummary, IssueResult } from './TransferSummary'
import { CancelBatchModal } from './CancelBatchModal'
import { SignatureStep } from './SignatureStep'

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
      const payload = buildIssuePayload(form, selected)
      const created = await transferApi.issue(payload)
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
      {step === 'sign' && signingTasks[signingIndex] && <SignatureStep tasks={signingTasks} index={signingIndex} onFinished={finishSignature} />}
      {step === 'result' && result && <><IssueResult result={result} onDownload={download} onCancel={() => setCancelOpen(true)} /><div className="actions"><button className="primary" onClick={onClose}>{t('common.done')}</button></div></>}
      {cancelOpen && result && <CancelBatchModal batch={{ batch_id: result.batch_id, batch_reference: result.batch_reference, operation: 'ISSUE', awaiting_signature_machines: result.transfers.filter((item) => item.workflow_status === 'AWAITING_SIGNATURE').length, total_machines: result.transfers.length }} onClose={() => setCancelOpen(false)} onCancelled={() => { setResult((current) => current ? { ...current, transfers: current.transfers.map((item) => ({ ...item, workflow_status: 'CANCELLED' })) } : current); setSigningTasks([]); setError(null); onComplete() }} />}
    </ModalShell>
  )
}
