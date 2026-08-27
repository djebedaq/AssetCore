import { Archive, Ban } from 'lucide-react'
import { statusText, useI18n } from '../../i18n'
import type { BatchDetails, BatchProgress, ProtocolDocument } from '../../types'

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
