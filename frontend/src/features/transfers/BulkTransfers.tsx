import { useEffect, useState } from 'react'
import { RotateCcw, Send } from 'lucide-react'
import { downloadApiFile } from '../../api'
import { useI18n } from '../../i18n'
import { hasPermission } from '../../permissions'
import type { BatchDetails, BatchProgress, Location, TransferAvailability } from '../../types'
import { transferApi } from './transferApi'
import { ConflictNotice } from './TransferConflictNotice'
import { BatchDetailsPanel, BatchProgressCard } from './BatchHistory'
import { IssueModal } from './IssueFlow'
import { ReturnModal } from './ReturnFlow'
import { CancelBatchModal } from './CancelBatchModal'

type BulkTransfersProps = { onChanged: () => void }

function canOperateTransfers(): boolean {
  return hasPermission('transfers.create', 'transfers.return')
}

function canCancelTransfers(): boolean {
  return hasPermission('transfers.create')
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
        transferApi.availability(),
        transferApi.locations(),
        transferApi.batches(),
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
      const value = await transferApi.batch(batch.batch_id)
      setDetails((current) => ({ ...current, [batch.batch_id]: value }))
    } catch (caught) {
      setError(caught instanceof Error ? caught : new Error('request_failed'))
    }
  }
  const requestCancel = async (batch: BatchProgress | BatchDetails) => {
    try {
      const value: BatchDetails = 'transfers' in batch ? batch : details[batch.batch_id] || await transferApi.batch(batch.batch_id)
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
