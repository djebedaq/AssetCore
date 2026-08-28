import { type FormEvent, useRef, useState } from 'react'
import { Ban, CheckCircle2, Download, Search } from 'lucide-react'
import { downloadApiFile } from '../../api'
import { statusText, useI18n } from '../../i18n'
import type { BulkReturnResult, SigningTask, TransferAvailability } from '../../types'
import { buildReturnPayload, CHECKLIST_ITEMS, type ReturnDraft } from './transferState'
import { transferApi } from './transferApi'
import { ConditionChecklist } from './TransferChecklist'
import { ModalShell } from './TransferModalShell'
import { ConflictNotice } from './TransferConflictNotice'
import { ConfirmationSummary } from './TransferSummary'
import { BatchProgressCard } from './BatchHistory'
import { CancelBatchModal } from './CancelBatchModal'
import { SignatureStep } from './SignatureStep'

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
  const [refreshState, setRefreshState] = useState<'idle' | 'loading' | 'error'>('idle')
  const refreshing = useRef(false)
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
      const payload = buildReturnPayload(drafts)
      const completed = await transferApi.return(payload)
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

  async function refreshResult() {
    if (!result || refreshing.current) return
    refreshing.current = true
    setRefreshState('loading')
    setError(null)
    setSigningTasks([])
    setStep('result')
    try {
      // Read only after the server confirms signing/cancellation. Publish the
      // complete snapshot together; failed/overlapping reads cannot restore it partially.
      const [operation, ...batches] = await Promise.all([
        transferApi.batch(result.batch_id),
        ...result.batches.map((batch) => transferApi.batch(batch.batch_id)),
      ])
      const returned = result.returned.map((item) => {
        const transfer = operation.transfers.find((entry) => entry.transfer_id === item.transfer_id && entry.machine_id === item.machine_id)
        if (!transfer?.return_status) throw new Error('return_progress_unavailable')
        return {
          ...item,
          workflow_status: operation.status === 'CANCELLED' ? operation.status : transfer.return_status,
          new_status: transfer.current_status,
          returned_at: transfer.returned_at,
          documents: transfer.return_documents,
        }
      })
      setResult({ ...result, returned, batches })
      setRefreshState('idle')
    } catch {
      setRefreshState('error')
    } finally {
      refreshing.current = false
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
      onComplete()
      void refreshResult()
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
      {step === 'sign' && signingTasks[signingIndex] && <SignatureStep tasks={signingTasks} index={signingIndex} onFinished={finishSignature} />}
      {step === 'result' && result && refreshState !== 'idle' && (
        <div className="operation-result" aria-busy={refreshState === 'loading'}>
          <ConfirmationSummary title={t('bulk.returnConfirmTitle')} machineNumbers={result.returned.map((item) => item.machine_number)} rows={[]} />
          {refreshState === 'loading'
            ? <p role="status">{t('common.loading')}</p>
            : <div className="conflict-notice" role="alert">{t('bulk.returnRefreshError')}</div>}
          <div className="actions"><button className="secondary" onClick={onClose}>{t('common.close')}</button><button className="primary" disabled={refreshState === 'loading'} onClick={() => void refreshResult()}>{t('bulk.refreshReturnProgress')}</button></div>
        </div>
      )}
      {step === 'result' && result && refreshState === 'idle' && (
        <div className="operation-result" role="status">
          {result.returned.every((item) => item.workflow_status === 'COMPLETED') && <CheckCircle2 size={36} />}
          <h4>{result.returned.every((item) => item.workflow_status === 'COMPLETED') ? t('bulk.returnSuccess') : result.returned.every((item) => item.workflow_status === 'CANCELLED') ? t('bulk.cancelSuccess') : t('bulk.awaitingSignature')}</h4>
          <div className="return-confirm-list">{result.returned.map((item) => <div key={item.transfer_id}><b>{t('bulk.machineName', { number: item.machine_number })}</b><span>{item.workflow_status === 'COMPLETED' ? t('bulk.newStatus', { status: statusText(t, item.new_status) }) : item.workflow_status === 'CANCELLED' ? t('status.cancelled') : t('bulk.awaitingSignature')}</span>{item.workflow_status === 'COMPLETED' && <span>{item.documents.map((document) => <button key={document.id} className="secondary compact" onClick={() => void downloadApiFile(document.download_endpoint, document.filename)}><Download size={15} />{document.format.toUpperCase()}</button>)}</span>}</div>)}</div>
          {result.batches.map((batch) => <BatchProgressCard key={batch.batch_id} batch={batch} />)}
          <div className="actions">{!result.returned.every((item) => item.workflow_status === 'COMPLETED' || item.workflow_status === 'CANCELLED') && <button className="danger" onClick={() => setCancelOpen(true)}><Ban size={17} />{t('bulk.cancelPendingAction')}</button>}<button className="primary" onClick={onClose}>{t('common.done')}</button></div>
        </div>
      )}
      {cancelOpen && result && <CancelBatchModal batch={{ batch_id: result.batch_id, batch_reference: result.batch_reference, operation: 'RETURN', awaiting_signature_machines: result.returned.filter((item) => item.workflow_status === 'AWAITING_SIGNATURE').length, total_machines: result.returned.length }} onClose={() => setCancelOpen(false)} onCancelled={() => {
        onComplete()
        void refreshResult()
      }} />}
    </ModalShell>
  )
}
