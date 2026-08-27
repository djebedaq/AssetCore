import { Archive, Ban, CheckCircle2, Download } from 'lucide-react'
import { useI18n } from '../../i18n'
import type { BulkIssueResult } from '../../types'

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
