import { useEffect, useState } from 'react'
import { api, downloadApiFile } from '../../api'
import { useI18n } from '../../i18n'
import { hasPermission } from '../../permissions'
import type { BatchDetails, BatchProgress } from '../../types'
import type { TransferEntryIntent } from '../passport/machineEntryIntent'
import { StatusBadge } from '../../ui/StatusBadge'
import { CategorySelect, DateFilters, FilterToolbar, MachineSelect, Pagination, SortSelect, queryParams, useCategories, usePage, useWorkspaceFilters } from '../../ui/workspace'
import BulkTransfers from './BulkTransfers'
import { BatchDetailsPanel, BatchProgressCard } from './BatchHistory'
import { CancelBatchModal } from './CancelBatchModal'
import { ModalShell } from './TransferModalShell'
import { TransferRecordDetails, TransferStatus, type CycleDetails, type TransferRecord } from './TransferRecordDetails'

type BatchRow = BatchProgress & { category_ids: number[]; mixed_categories: boolean; registered_machines: number }
type Tab = 'issued' | 'history'
type Scope = 'active' | 'pending' | 'awaiting_issue' | 'awaiting_return' | 'cancelled' | 'other' | 'all'
type Target = { kind: 'batch' | 'cycle'; id: number }
function routeTarget(): Target | null {
  if (window.location.pathname !== '/transfers') return null
  const params = new URLSearchParams(window.location.search)
  for (const [key, kind] of [['record_id', 'cycle'], ['batch_id', 'batch']] as const) {
    const id = Number(params.get(key))
    if (Number.isSafeInteger(id) && id > 0) return { kind, id }
  }
  return null
}
function DetailModal({ target, onClose, onBatch, onCancel, onDownload }: {
  target: Target; onClose: () => void; onBatch: (id: number) => void
  onCancel?: (id: number) => void; onDownload: (path: string, filename: string) => void
}) {
  const { date, t } = useI18n()
  const [details, setDetails] = useState<BatchDetails | CycleDetails | null>(null)
  const [failed, setFailed] = useState(false)
  useEffect(() => {
    const controller = new AbortController()
    setDetails(null); setFailed(false)
    const path = target.kind === 'batch' ? `/transfer-batches/${target.id}` : `/workspace/transfers/${target.id}`
    void api<BatchDetails | CycleDetails>(path, { signal: controller.signal })
      .then(value => { if (!controller.signal.aborted) setDetails(value) })
      .catch(() => { if (!controller.signal.aborted) setFailed(true) })
    return () => controller.abort()
  }, [target.kind, target.id])
  return <ModalShell title={t(target.kind === 'batch' ? 'transfersUX.batchDetails' : 'transfersUX.cycleDetails')} onClose={onClose} wide>
    {failed && <div className="error" role="alert">{t('transfers.loadError')}</div>}
    {!failed && !details && <div className="loading" role="status">{t('common.loading')}</div>}
    {details && 'transfers' in details && <>
      <div className="transfer-batch-summary"><strong>{details.batch_reference}</strong><small>{date(details.created_at)}</small><StatusBadge status={details.status} domain="batch" /><p>{t('bulk.returnedProgress', { returned: details.returned_machines, issued: details.still_issued_machines, total: details.total_machines })}</p></div>
      <BatchDetailsPanel details={details} onDownload={onDownload} onCancel={onCancel ? value => onCancel(value.batch_id) : undefined} onCancelOperation={onCancel} />
    </>}
    {details && !('transfers' in details) && <TransferRecordDetails details={details} onBatch={details.issue_status === 'AWAITING_SIGNATURE' || details.return_status === 'AWAITING_SIGNATURE' ? onBatch : undefined} />}
  </ModalShell>
}

export default function Transfers({ entryIntent, onEntryConsumed, initialRecordId }: { entryIntent?: TransferEntryIntent; onEntryConsumed?: () => void; initialRecordId?: number } = {}) {
  const { date, t, locale } = useI18n()
  const [refresh, setRefresh] = useState(0)
  const [tab, setTab] = useState<Tab>(() => initialRecordId || routeTarget()?.kind === 'cycle' || new URLSearchParams(window.location.search).get('view') === 'history' ? 'history' : 'issued')
  const [scope, setScope] = useState<Scope>('active')
  const [target, setTarget] = useState<Target | null>(() => initialRecordId ? { kind: 'cycle', id: initialRecordId } : routeTarget())
  const [cancelBatch, setCancelBatch] = useState<BatchDetails | null>(null)
  const [error, setError] = useState('')
  const { categories, error: categoryError } = useCategories('transfers', refresh)
  const filter = useWorkspaceFilters()
  const batchView = tab === 'issued' && (scope === 'active' || scope === 'pending')
  const params = { ...filter.params, status: tab === 'history' ? 'completed' : scope === 'all' ? undefined : scope }
  const path = `/workspace/${batchView ? 'batches' : 'transfers'}?${queryParams({ ...params, context: batchView ? scope : undefined })}`
  const batches = usePage<BatchRow>(batchView ? path : null, refresh)
  const records = usePage<TransferRecord>(batchView ? null : path, refresh)
  const result = batchView ? batches : records
  useEffect(() => { if (initialRecordId) { setTarget({ kind: 'cycle', id: initialRecordId }); setTab('history') } }, [initialRecordId])
  useEffect(() => {
    // Only operation identifiers and presentation state belong in navigation.
    if (window.location.pathname !== '/transfers') return
    const url = new URL(window.location.href)
    url.searchParams.set('view', tab)
    url.searchParams.delete('record_id'); url.searchParams.delete('batch_id')
    if (target) url.searchParams.set(target.kind === 'cycle' ? 'record_id' : 'batch_id', String(target.id))
    window.history.replaceState(window.history.state, '', url)
  }, [tab, target])
  const changed = () => { setTarget(null); setRefresh(value => value + 1) }
  async function cancel(batchId: number) {
    try { setCancelBatch(await api<BatchDetails>(`/transfer-batches/${batchId}`)) }
    catch { setError(t('transfers.loadError')) }
  }
  function download(path: string, filename: string) { void downloadApiFile(path, filename).catch(() => setError(t('transfers.downloadError'))) }
  function changeTab(value: Tab) { setTab(value); setTarget(null); filter.setPage(1) }
  function categoryName(id?: number | null) {
    const category = categories.find(item => item.id === id)
    return category?.[`name_${locale}`] || category?.name_bg || t('ux.legacy')
  }
  return <>
    <BulkTransfers hideBatchPanel entryIntent={entryIntent} onEntryConsumed={onEntryConsumed} onChanged={changed} />
    <div className="ac-context-tabs" role="tablist" aria-label={t('nav.transfers')}>
      {(['issued', 'history'] as const).map(value => <button id={`transfers-tab-${value}`} role="tab" aria-selected={value === tab} aria-controls="transfers-results" tabIndex={value === tab ? 0 : -1} key={value} type="button" onClick={() => changeTab(value)} onKeyDown={event => {
        if (['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) {
          event.preventDefault()
          const next = event.key === 'Home' ? 'issued' : event.key === 'End' ? 'history' : tab === 'issued' ? 'history' : 'issued'
          changeTab(next); document.getElementById(`transfers-tab-${next}`)?.focus()
        }
      }}>{t(value === 'issued' ? 'transfersUX.issued' : 'transfersUX.history')}</button>)}
    </div>
    <FilterToolbar query={filter.values.q} onQuery={value => filter.change('q', value)} onReset={() => { filter.reset(); setScope('active') }}>
      <CategorySelect categories={categories} value={filter.values.category} onChange={value => filter.change('category', value)} legacy mixed={batchView} />
      <MachineSelect module="transfers" category={filter.values.category} value={filter.values.machine} onChange={value => filter.change('machine', value)} />
      <DateFilters from={filter.values.from} to={filter.values.to} onFrom={value => filter.change('from', value)} onTo={value => filter.change('to', value)} />
      <SortSelect value={filter.values.sort} onChange={value => filter.change('sort', value)} />
      {tab === 'issued' && <label className="ac-filter"><span>{t('transfersUX.scope')}</span><select className="ac-native-select" aria-label={t('transfersUX.scope')} value={scope} onChange={event => { setScope(event.target.value as Scope); filter.setPage(1) }}>
        <option value="active">{t('transfersUX.active')}</option><option value="pending">{t('transfersUX.pendingBatches')}</option>
        <option value="awaiting_issue">{t('transfersUX.awaitingIssue')}</option><option value="awaiting_return">{t('transfersUX.awaitingReturn')}</option>
        <option value="cancelled">{t('status.cancelled')}</option><option value="other">{t('transfersUX.other')}</option><option value="all">{t('transfersUX.all')}</option>
      </select></label>}
    </FilterToolbar>
    <p className="ac-history-note">{t(tab === 'history' ? 'transfersUX.historyHint' : 'ux.currentCategory')}</p>
    {(error || result.error || categoryError) && <div className="error" role="alert">{error || t('transfers.loadError')}</div>}
    <section id="transfers-results" role="tabpanel" aria-labelledby={`transfers-tab-${tab}`}>
      {result.loading && <div className="loading" role="status">{t('common.loading')}</div>}
      {batchView && <div className="panel batch-panel"><div className="batch-list">{batches.data?.items.map(batch => <div key={batch.batch_id}>
        <BatchProgressCard detailsInModal batch={batch} onOpen={() => setTarget({ kind: 'batch', id: batch.batch_id })} onCancel={hasPermission('transfers.create') ? () => void cancel(batch.batch_id) : undefined} />
        <small className="ac-batch-category">{batch.category_ids.map(categoryName).join(' · ')}{batch.mixed_categories && ` · ${t('ux.mixedBatch')}`}</small>
        {batch.registered_machines !== batch.total_machines && <small>{t('ux.registeredCount', { count: batch.registered_machines })} · {t('ux.issuedCount', { count: batch.total_machines })}</small>}
      </div>)}</div>{batches.data && !batches.data.items.length && <div className="empty-state">{t(scope === 'active' ? 'ux.emptyActive' : 'bulk.noBatches')}</div>}</div>}
      {!batchView && <div className="table-card transfer-history-table"><table><thead><tr>
        <th>{t('common.machine')}</th><th>{t('machines.category')}</th><th>{t('transfersUX.issuedAt')}</th><th>{t('transfersUX.returnedAt')}</th><th>{t('bulk.technicalReference')}</th><th>{t('common.status')}</th><th>{t('common.details')}</th>
      </tr></thead><tbody>{records.data?.items.map(transfer => <tr key={transfer.id} data-cycle-id={transfer.id}>
        <td><strong>№{transfer.machine.inventory_number}</strong>{transfer.machine.name}<small>{transfer.machine.model}</small></td>
        <td>{categoryName(transfer.machine.category_id)}</td><td>{transfer.issued_at ? date(transfer.issued_at) : t('common.noValue')}</td><td>{transfer.returned_at && transfer.return_status === 'COMPLETED' ? date(transfer.returned_at) : t('common.noValue')}</td>
        <td>{transfer.batch_reference || t('common.noValue')}<small>{transfer.protocol_number}</small></td><td><TransferStatus record={transfer} /></td>
        <td><button className="secondary compact" onClick={() => setTarget({ kind: 'cycle', id: transfer.id })}>{t('common.details')}</button></td>
      </tr>)}</tbody></table>{records.data && !records.data.items.length && <div className="empty-state">{t('transfers.emptyHistory')}</div>}</div>}
      <Pagination data={result.data} onPage={filter.setPage} />
    </section>
    {target && <DetailModal key={`${target.kind}:${target.id}`} target={target} onClose={() => setTarget(null)} onBatch={id => setTarget({ kind: 'batch', id })} onDownload={download} onCancel={hasPermission('transfers.create') ? id => void cancel(id) : undefined} />}
    {cancelBatch && <CancelBatchModal batch={cancelBatch} onClose={() => setCancelBatch(null)} onCancelled={() => { setCancelBatch(null); changed() }} />}
  </>
}
