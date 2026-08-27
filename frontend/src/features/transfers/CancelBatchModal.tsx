import { type FormEvent, useState } from 'react'
import { Ban, CheckCircle2, ShieldAlert } from 'lucide-react'
import { useI18n } from '../../i18n'
import type { BatchDetails, CancelTransferBatchResponse } from '../../types'
import { transferApi } from './transferApi'
import { ModalShell } from './TransferModalShell'
import { localizedErrorKey } from './TransferConflictNotice'

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
      const cancelled = await transferApi.cancel(batch.batch_id, trimmedReason)
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
