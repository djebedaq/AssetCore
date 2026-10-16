import { useI18n } from '../../i18n'
import { DocumentButtons } from '../../industrialUi'
import type { Machine } from '../../types'
import { StatusBadge } from '../../ui/StatusBadge'

export type TransferRecord = {
  id: number; protocol_number: string; batch_reference?: string | null; batch_id?: number | null
  is_active: boolean; issue_status: string; return_status?: string | null
  issued_at?: string | null; returned_at?: string | null; created_at?: string; machine: Machine
}
export type CycleDetails = TransferRecord & { category?: { name_bg: string; name_en?: string | null; name_ru?: string | null } | null; documents: Array<{
  document_type: string; document_number: string; official_document_id?: number | null
  version?: number | null; created_at: string; finalized_at?: string | null
  files: Array<{ format: string; download_endpoint: string }>
}> }

export function TransferStatus({ record }: { record: TransferRecord }) {
  const { t } = useI18n()
  const completed = record.issue_status === 'COMPLETED' && record.return_status === 'COMPLETED' && !record.is_active && !!record.issued_at && !!record.returned_at
  const status = completed ? 'RETURNED' : record.issue_status !== 'COMPLETED' ? record.issue_status : record.return_status === 'AWAITING_SIGNATURE' ? 'AWAITING_SIGNATURE' : record.is_active ? 'ACTIVE' : record.return_status || 'INCOMPLETE'
  const label = completed ? t('transfersUX.completed') : !['ACTIVE', 'AWAITING_SIGNATURE', 'CANCELLED'].includes(status) ? t('transfersUX.incomplete') : undefined
  return <><StatusBadge domain="batch" status={status} label={label} />{record.return_status === 'CANCELLED' && <small>{t('transfersUX.returnCancelled')}</small>}</>
}

export function TransferRecordDetails({ details, onBatch }: { details: CycleDetails; onBatch?: (id: number) => void }) {
  const { date, locale, t } = useI18n()
  const machine = details.machine
  const category = details.category
  return <div className="transfer-cycle-details" data-cycle-id={details.id}>
    <TransferStatus record={details} />
    <dl className="detail-grid">
      <div><dt>{t('common.machine')}</dt><dd>№{machine.inventory_number} · {machine.name}</dd></div>
      <div><dt>{t('machines.brand')} / {t('machines.model')}</dt><dd>{[machine.brand, machine.model].filter(Boolean).join(' · ') || t('common.noValue')}</dd></div>
      <div><dt>{t('machines.category')}</dt><dd>{category?.[`name_${locale}`] || category?.name_bg || machine.category || t('ux.legacy')}</dd></div>
      <div><dt>{t('bulk.technicalReference')}</dt><dd>{details.batch_reference || t('common.noValue')}</dd></div>
      <div><dt>{t('transfersUX.issuedAt')}</dt><dd>{details.issued_at ? date(details.issued_at) : t('common.noValue')}</dd></div>
      <div><dt>{t('transfersUX.returnedAt')}</dt><dd>{details.returned_at ? date(details.returned_at) : t('common.noValue')}</dd></div>
    </dl>
    <div className="transfer-cycle-protocols">
      {(['TRANSFER_ISSUE', 'TRANSFER_RETURN'] as const).map(kind => <section key={kind} aria-label={t(kind === 'TRANSFER_ISSUE' ? 'bulk.issueProtocol' : 'bulk.returnProtocol')}>
        <h4>{t(kind === 'TRANSFER_ISSUE' ? 'bulk.issueProtocol' : 'bulk.returnProtocol')}</h4>
        {details.documents.filter(document => document.document_type === kind).map(document => <article key={`${document.official_document_id || document.document_number}:${document.version || 0}`}>
          <strong>{document.document_number}</strong><small>{date(document.finalized_at || document.created_at)}</small>
          <div className="document-actions-inline">{[...document.files].sort((a, b) => Number(b.format === 'pdf') - Number(a.format === 'pdf')).map(file => <DocumentButtons previewFirst key={file.format} path={file.download_endpoint} filename={`${document.document_number}.${file.format}`} format={file.format} />)}</div>
        </article>)}
        {!details.documents.some(document => document.document_type === kind) && <p className="muted">{t('transfersUX.noArchivedDocument')}</p>}
      </section>)}
    </div>
    {onBatch && details.batch_id && <button className="secondary" onClick={() => onBatch(details.batch_id!)}>{t('transfersUX.operationDetails')}</button>}
  </div>
}
