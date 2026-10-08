import { useEffect, useRef, useState } from 'react'
import { api, downloadApiFile } from '../../api'
import { useI18n } from '../../i18n'
import { hasPermission } from '../../permissions'
import type { BatchDetails, BatchProgress, Machine } from '../../types'
import type { TransferEntryIntent } from '../passport/machineEntryIntent'
import { StatusBadge } from '../../ui/StatusBadge'
import { CategorySelect, DateFilters, FilterToolbar, MachineSelect, Pagination, SortSelect, queryParams, useCategories, usePage, useWorkspaceFilters } from '../../ui/workspace'
import BulkTransfers from './BulkTransfers'
import { BatchDetailsPanel, BatchProgressCard } from './BatchHistory'
import { CancelBatchModal } from './CancelBatchModal'

type BatchRow = BatchProgress & { category_ids: number[]; mixed_categories: boolean; registered_machines: number }
type TransferRecord = {
  id: number; protocol_number: string; batch_reference?: string | null; batch_id?: number | null
  is_active: boolean; issue_status: string; return_status?: string | null
  company_unit?: string | null; vessel?: string | null; location_text?: string | null
  issued_at?: string | null; returned_at?: string | null; created_at: string; machine: Machine
}
type Context = 'active' | 'completed' | 'pending' | 'individual'
export default function Transfers({ entryIntent, onEntryConsumed, initialRecordId }: { entryIntent?: TransferEntryIntent; onEntryConsumed?: () => void; initialRecordId?: number } = {}) {
  const { date, t, locale } = useI18n()
  const [refresh, setRefresh] = useState(0)
  const [context, setContext] = useState<Context>(initialRecordId ? 'individual' : 'active')
  const [recordId, setRecordId] = useState(initialRecordId)
  const [details, setDetails] = useState<Record<number, BatchDetails>>({})
  const [opening, setOpening] = useState<number | null>(null)
  const [cancelBatch, setCancelBatch] = useState<BatchDetails | null>(null)
  const [error, setError] = useState('')
  const generation = useRef(0)
  const { categories, error: categoryError } = useCategories('transfers', refresh)
  const filter = useWorkspaceFilters()
  const path = `/workspace/${context === 'individual' ? 'transfers' : 'batches'}?${queryParams({ ...filter.params, context: context === 'individual' ? undefined : context, status: context === 'individual' && !recordId ? 'completed' : undefined, record_id: recordId })}`
  const batches = usePage<BatchRow>(context === 'individual' ? null : path, refresh)
  const records = usePage<TransferRecord>(context === 'individual' ? path : null, refresh)
  const result = context === 'individual' ? records : batches
  useEffect(() => {
    generation.current++; setDetails({}); setOpening(null)
  }, [path, refresh])
  useEffect(() => { if (initialRecordId) { setRecordId(initialRecordId); setContext('individual') } }, [initialRecordId])
  const changed = () => { setDetails({}); setRefresh(value => value + 1) }
  async function toggleBatch(batchId: number) {
    if (details[batchId]) { setDetails(current => { const next = { ...current }; delete next[batchId]; return next }); return }
    const version = generation.current
    setOpening(batchId)
    try {
      const value = await api<BatchDetails>(`/transfer-batches/${batchId}`)
      if (version === generation.current) { setDetails(current => ({ ...current, [batchId]: value })); setError('') }
    } catch { if (version === generation.current) setError(t('transfers.loadError')) }
    finally { if (version === generation.current) setOpening(null) }
  }
  async function cancel(batchId: number) {
    try { setCancelBatch(details[batchId] || await api<BatchDetails>(`/transfer-batches/${batchId}`)) }
    catch { setError(t('transfers.loadError')) }
  }
  function download(path: string, filename: string) { void downloadApiFile(path, filename).catch(() => setError(t('transfers.downloadError'))) }
  function changeContext(value: Context) { setContext(value); setRecordId(undefined); filter.setPage(1) }
  return <>
    <BulkTransfers hideBatchPanel entryIntent={entryIntent} onEntryConsumed={onEntryConsumed} onChanged={changed} />
    <div className="ac-context-tabs" role="group" aria-label={t('transfers.historyTitle')}>
      {(['active', 'completed', 'pending', 'individual'] as const).map(value => <button key={value} type="button" aria-pressed={value === context} onClick={() => changeContext(value)}>{t(value === 'active' ? 'ux.activeBatches' : value === 'completed' ? 'ux.completedBatches' : value === 'pending' ? 'ux.pendingBatches' : 'ux.individualRecords')}</button>)}
    </div>
    <FilterToolbar query={filter.values.q} onQuery={value => { setRecordId(undefined); filter.change('q', value) }} onReset={() => { setRecordId(undefined); filter.reset() }}>
      <CategorySelect categories={categories} value={filter.values.category} onChange={value => { setRecordId(undefined); filter.change('category', value) }} legacy mixed={context !== 'individual'} />
      <MachineSelect module="transfers" category={filter.values.category} value={filter.values.machine} onChange={value => { setRecordId(undefined); filter.change('machine', value) }} />
      <DateFilters from={filter.values.from} to={filter.values.to} onFrom={value => filter.change('from', value)} onTo={value => filter.change('to', value)} />
      <SortSelect value={filter.values.sort} onChange={value => filter.change('sort', value)} />
    </FilterToolbar>
    <p className="ac-history-note">{t('ux.currentCategory')}</p>
    {(error || result.error || categoryError) && <div className="error" role="alert">{error || t('transfers.loadError')}</div>}
    {result.loading && <div className="loading" role="status">{t('common.loading')}</div>}
    {context !== 'individual' && <div className="panel batch-panel"><div className="batch-list">{batches.data?.items.map(batch => <div key={batch.batch_id}>
      <BatchProgressCard batch={batch} expanded={Boolean(details[batch.batch_id])} onOpen={() => void toggleBatch(batch.batch_id)} onCancel={hasPermission('transfers.create') ? () => void cancel(batch.batch_id) : undefined} />
      <small className="ac-batch-category">{batch.category_ids.map(id => { const category = categories.find(item => item.id === id); return category?.[`name_${locale}`] || category?.name_bg || t('ux.legacy') }).join(' · ')}{batch.mixed_categories && ` · ${t('ux.mixedBatch')}`}</small>
      {batch.registered_machines !== batch.total_machines && <small>{t('ux.registeredCount', { count: batch.registered_machines })} · {t('ux.issuedCount', { count: batch.total_machines })}</small>}
      {opening === batch.batch_id && <div role="status">{t('common.loading')}</div>}
      {details[batch.batch_id] && <BatchDetailsPanel details={details[batch.batch_id]} onDownload={download} onCancel={hasPermission('transfers.create') ? value => void cancel(value.batch_id) : undefined} onCancelOperation={hasPermission('transfers.create') ? id => void cancel(id) : undefined} />}
    </div>)}</div>{batches.data && !batches.data.items.length && <div className="empty-state">{t(context === 'active' ? 'ux.emptyActive' : context === 'completed' ? 'ux.emptyCompleted' : 'bulk.noBatches')}</div>}</div>}
    {context === 'individual' && <div className="table-card"><table><thead><tr><th>{t('transfers.number')}</th><th>{t('transfers.batch')}</th><th>{t('common.machine')}</th><th>{t('common.status')}</th><th>{t('transfers.companyLocation')}</th><th>{t('transfers.issueReturn')}</th><th>{t('transfers.documents')}</th></tr></thead><tbody>
      {records.data?.items.map(transfer => <tr key={transfer.id}><td><strong>{transfer.protocol_number}</strong></td><td>{transfer.batch_reference || t('common.noValue')}</td><td>{transfer.machine.name}</td>
        <td><StatusBadge status={transfer.issue_status !== 'COMPLETED' ? transfer.issue_status : transfer.return_status === 'COMPLETED' ? 'RETURNED' : transfer.is_active ? 'ACTIVE' : transfer.return_status || 'COMPLETED'} domain="batch" /></td>
        <td>{[transfer.company_unit, transfer.vessel, transfer.location_text].filter(Boolean).join(' · ') || t('common.noValue')}</td><td>{date(transfer.issued_at || transfer.created_at)}{transfer.returned_at && <small>{t('transfers.returnedAt', { date: date(transfer.returned_at) })}</small>}</td>
        <td>{transfer.issue_status === 'COMPLETED' && <><button className="link" onClick={() => download(`/transfers/${transfer.id}/docx`, `${transfer.protocol_number}.docx`)}>{t('common.word')}</button> · <button className="link" onClick={() => download(`/transfers/${transfer.id}/pdf`, `${transfer.protocol_number}.pdf`)}>{t('common.pdf')}</button></>}{transfer.batch_id && <button className="link" aria-expanded={Boolean(details[transfer.batch_id])} aria-controls={`batch-detail-${transfer.batch_id}`} onClick={() => void toggleBatch(transfer.batch_id!)}>{t('common.details')}</button>}</td>
      </tr>)}
    </tbody></table>{records.data && !records.data.items.length && <div className="empty-state">{t('transfers.emptyHistory')}</div>}
      {records.data?.items.filter(item => item.batch_id && details[item.batch_id]).filter((item, index, values) => values.findIndex(candidate => candidate.batch_id === item.batch_id) === index).map(item => <BatchDetailsPanel key={item.batch_id} details={details[item.batch_id!]} onDownload={download} />)}
    </div>}
    <Pagination data={result.data} onPage={filter.setPage} />
    {cancelBatch && <CancelBatchModal batch={cancelBatch} onClose={() => setCancelBatch(null)} onCancelled={() => { setCancelBatch(null); changed() }} />}
  </>
}
