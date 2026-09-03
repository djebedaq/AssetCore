import { Archive, Ban } from 'lucide-react'
import { statusText, useI18n } from '../../i18n'
import { DocumentButtons } from '../../industrialUi'
import type { BatchDetails, BatchProgress, ProtocolDocument } from '../../types'

function groupProtocolDocuments(documents: ProtocolDocument[], fallbackNumber?: string) {
  const groups = new Map<string, { number: string | null; documents: ProtocolDocument[] }>()
  documents.forEach((document, index) => {
    const number = document.document_number?.trim() || fallbackNumber?.trim() || null
    const key = number || `missing-${index}`
    const group = groups.get(key)
    if (group) group.documents.push(document)
    else groups.set(key, { number, documents: [document] })
  })
  return [...groups.values()]
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
        <article className="batch-transfer-item" data-transfer-id={transfer.transfer_id} key={transfer.transfer_id}>
          <section className="batch-transfer-machine">
            <h4>{t('bulk.batchMachine', { number: transfer.machine_number })}</h4>
            <small>{transfer.brand}</small>
            <span className={`availability-pill ${transfer.is_active ? 'blocked' : 'available'}`}>{transfer.issue_status === 'AWAITING_SIGNATURE' || transfer.return_status === 'AWAITING_SIGNATURE' ? t('bulk.awaitingSignature') : transfer.is_active ? t('transfers.stillIssued') : t('transfers.returned')}</span>
          </section>
          <div className="batch-transfer-protocols" aria-label={t('transfers.documents')}>
            {transfer.issue_status === 'COMPLETED'
              ? groupProtocolDocuments(transfer.issue_documents, transfer.protocol_number).map((protocol) => (
                  <section className="batch-transfer-protocol" data-protocol-kind="issue" key={`issue-${protocol.number || protocol.documents[0].id}`}>
                    <span>{t('bulk.issueProtocol')}</span>
                    <strong>{protocol.number || t('common.noValue')}</strong>
                    <div>{protocol.documents.map((document) => <DocumentButtons key={document.id} path={document.download_endpoint} filename={document.filename} format={document.format} />)}</div>
                  </section>
                ))
              : <section className="batch-transfer-protocol pending" data-protocol-kind="issue"><span>{t('bulk.issueProtocol')}</span><em>{t('bulk.awaitingSignature')}</em></section>}
            {transfer.return_status === 'COMPLETED'
              ? groupProtocolDocuments(transfer.return_documents).map((protocol) => (
                  <section className="batch-transfer-protocol" data-protocol-kind="return" key={`return-${protocol.number || protocol.documents[0].id}`}>
                    <span>{t('bulk.returnProtocol')}</span>
                    <strong>{protocol.number || t('common.noValue')}</strong>
                    <div>{protocol.documents.map((document) => <DocumentButtons key={document.id} path={document.download_endpoint} filename={document.filename} format={document.format} />)}</div>
                  </section>
                ))
              : transfer.return_status === 'AWAITING_SIGNATURE'
                ? <section className="batch-transfer-protocol pending" data-protocol-kind="return"><span>{t('bulk.returnProtocol')}</span><em>{t('bulk.awaitingSignature')}</em></section>
                : <p className="batch-transfer-return-pending">{t('bulk.returnNotCompleted')}</p>}
          </div>
        </article>
      ))}
    </div>
  )
}
