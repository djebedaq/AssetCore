import { useEffect, useId, useRef, useState } from 'react'
import { ChevronLeft, ChevronRight } from 'lucide-react'
import { useI18n } from '../../i18n'
import { StatusBadge } from '../../ui/StatusBadge'
import { Pagination, SortSelect, openOperation, queryParams, usePage, type PageData } from '../../ui/workspace'
import { useReportDate, useReportText, type Asset, type Kind, type MachineStats, type Metric, type RecordRow, type Section } from './reportData'

export function ReportTabs({ tabs, active, onSelect }: { tabs: Section[]; active: Section; onSelect: (tab: Section) => void }) {
  const text = useReportText(), { locale } = useI18n(), id = useId(), nav = useRef<HTMLElement>(null)
  const [overflow, setOverflow] = useState({ left: false, right: false }), tabKey = tabs.join(',')
  function update() {
    const element = nav.current
    if (element) setOverflow(previous => {
      const next = { left: element.scrollLeft > 1, right: element.scrollWidth - element.clientWidth - element.scrollLeft > 1 }
      return previous.left === next.left && previous.right === next.right ? previous : next
    })
  }
  useEffect(() => {
    update()
    const observer = typeof ResizeObserver === 'undefined' ? null : new ResizeObserver(update)
    if (nav.current) observer?.observe(nav.current)
    window.addEventListener('resize', update)
    return () => { observer?.disconnect(); window.removeEventListener('resize', update) }
  }, [tabKey, locale])
  return <div className="reports-tab-strip"><nav ref={nav} id={id} className="reports-tabs" aria-label={text('title')} aria-describedby={overflow.left || overflow.right ? `${id}-hint` : undefined} onScroll={update}>{tabs.map(tab => <button type="button" aria-current={active === tab ? 'page' : undefined} key={tab} onFocus={event => event.currentTarget.scrollIntoView?.({ block: 'nearest', inline: 'nearest', behavior: 'auto' })} onClick={() => onSelect(tab)}>{text(tab)}</button>)}</nav>
    {(overflow.left || overflow.right) && <div className="reports-tab-arrows"><span id={`${id}-hint`} className="sr-only">{text('moreDirections')}</span><button type="button" aria-label={text('previousDirections')} aria-controls={id} disabled={!overflow.left} onClick={() => nav.current?.scrollBy({ left: -nav.current.clientWidth * .8, behavior: 'auto' })}><ChevronLeft size={18} aria-hidden="true" /></button><button type="button" aria-label={text('nextDirections')} aria-controls={id} disabled={!overflow.right} onClick={() => nav.current?.scrollBy({ left: nav.current.clientWidth * .8, behavior: 'auto' })}><ChevronRight size={18} aria-hidden="true" /></button></div>}
  </div>
}

export function MetricCards({ metrics, onDrill, comparison = false }: { metrics: Metric[]; onDrill: (metric: Metric) => void; comparison?: boolean }) {
  const text = useReportText(), { number } = useI18n()
  return <div className="reports-metrics">{metrics.map(metric => <button type="button" className="reports-metric" key={metric.key} onClick={() => onDrill(metric)} disabled={!metric.drill} title={metric.unit === 'hours' ? text('usageHelp') : text('methodology')}>
    <span>{text(metric.key)}</span><strong>{metric.value == null ? <small>{text('insufficient')}</small> : number(Math.round(metric.value * 100) / 100)} <small>{metric.value != null && text(metric.unit)}</small></strong>
    {metric.current && <small>{text('current')}</small>}{metric.sample != null && <small>{text('sample', { count: metric.sample })}</small>}
    {comparison && metric.previous != null && <small>{text('previous')}: {number(metric.previous)} · Δ {number(metric.change || 0)} · {metric.percent == null ? text('noBase') : `${number(metric.percent)}%`}</small>}
  </button>)}</div>
}
export function Records({ kind, metric, params, initial, onPassport, delayed = false }: { kind: Kind; metric: string; params: Record<string, string | number | undefined>; initial?: PageData<RecordRow> | null; onPassport: (id: number) => void; delayed?: boolean }) {
  const text = useReportText(), date = useReportDate(), { t, number } = useI18n()
  const [page, setPage] = useState(1), [sort, setSort] = useState('newest'), [issuesFor, setIssuesFor] = useState<Asset | null>(null)
  const issueTrigger = useRef<HTMLButtonElement | null>(null)
  const path = initial && page === 1 && sort === 'newest' ? null : `/reports/records?${queryParams({ ...params, kind, metric, page, sort })}`
  const remote = usePage<RecordRow>(path), data = path ? remote.data : initial
  const unique = kind === 'usage' && metric === 'unique_issued'
  const dateBasis = data?.items[0]?.date_basis || 'date'
  return <div className="reports-records"><SortSelect value={sort} onChange={value => { setSort(value); setPage(1) }} />
    {remote.error && <p className="error" role="alert">{t('errors.generic')}</p>}{remote.loading && <p role="status">{t('common.loading')}</p>}
    {data && <><div className="reports-table" tabIndex={0} role="region" aria-label={text('records')}><table><thead><tr><th>{text(unique ? 'issues' : 'reference')}</th><th>{text('machineLabel')}</th><th>{text(dateBasis)}</th>{!unique && <th>{delayed ? text('remaining') : text('description')}</th>}<th>{text('status')}</th></tr></thead><tbody>{data.items.map(row => <tr key={row.id}>
      <td>{unique && row.machine ? <button type="button" className="link" aria-expanded={issuesFor?.id === row.machine.id} onClick={event => { issueTrigger.current = event.currentTarget; setIssuesFor(issuesFor?.id === row.machine!.id ? null : row.machine!) }}>{text('viewIssues', { count: row.issue_count })}</button> : row.module ? <button type="button" className="link" aria-label={`${text('openOriginal')}: ${row.official_number || row.request_reference || row.repair_reference || row.protocol_number || row.id}`} onClick={() => openOperation({ module: row.module!, recordId: row.original_id || row.id, machineId: row.machine_id })}>{row.official_number || row.request_reference || row.repair_reference || row.protocol_number || row.id}</button> : row.inventory_number}{row.batch_id && <small>#{row.batch_id}</small>}</td>
      <td>{row.machine ? <button type="button" className="link" onClick={() => onPassport(row.machine!.id)}>№{row.machine.inventory_number} · {row.machine.name}</button> : kind === 'machines' ? <button type="button" className="link" onClick={() => onPassport(row.id)}>№{row.inventory_number} · {row.name}</button> : text('general')}</td>
      <td><RecordDate row={row} />{delayed && <>{row.ordered_at && <small>{text('ordered_at')}: {date(row.ordered_at)}</small>}<small>{text('elapsed')}: {number(row.elapsed_days || 0)}</small></>}</td>
      {!unique && <td>{delayed ? <><strong>{text('unfulfilled')}: {row.remaining_lines}</strong>{row.remaining?.map(line => <small key={line.id}>{line.description}: {line.quantity} {line.unit || '—'}</small>)}</> : row.reported_problem || row.part_name || '—'}</td>}
      <td>{(row.status || row.return_status || row.issue_status) && <StatusBadge status={kind === 'usage' && !unique ? row.return_status === 'COMPLETED' ? 'RETURNED' : row.is_active ? 'ISSUED' : 'COMPLETED' : row.status || ''} domain={kind === 'repairs' ? 'repair' : kind === 'requests' ? 'part' : 'machine'} />}</td></tr>)}</tbody></table>{!data.items.length && <p className="reports-empty">{text('empty')}</p>}</div><Pagination data={data} onPage={setPage} /></>}
    {unique && issuesFor && <section className="reports-machine-issues" aria-label={`${text('issues')} · №${issuesFor.inventory_number}`}><div className="reports-section-title"><h4>{text('issues')} · №{issuesFor.inventory_number}</h4><button type="button" className="secondary compact" onClick={() => { setIssuesFor(null); issueTrigger.current?.focus() }}>{text('closeIssues')}</button></div><Records key={issuesFor.id} kind="usage" metric="issues" params={{ ...params, machine_ids: '', machine_id: issuesFor.id }} onPassport={onPassport} /></section>}
  </div>
}
function RecordDate({ row }: { row: RecordRow }) {
  const date = useReportDate(), text = useReportText()
  // Additive date metadata is authoritative; retain compatibility with older API responses.
  const when = row.date_basis ? row.metric_date : row.issued_at || row.opened_at || row.created_at
  return <>{when ? date(when) : '—'}{row.date_basis === 'issued_at' && row.return_status === 'COMPLETED' && row.returned_at && <small>{text('end')}: {date(row.returned_at)}</small>}</>
}
export function Comparison({ items, drill }: { items: MachineStats[]; drill: (machine: Asset, metric: Metric, kind: Kind) => void }) {
  const text = useReportText(), { number } = useI18n()
  const keys = ['issues', 'completed_cycles', 'issue_hours', 'opened', 'calendar_hours', 'labor_minutes', 'created', 'returned_repair'].filter(key => items.some(item => Object.values(item.metrics).flat().some(m => m.key === key)))
  return <div className="reports-table" tabIndex={0} role="region" aria-label={text('compare')}><table><thead><tr><th>{text('description')}</th>{items.map(item => <th key={item.machine.id}>№{item.machine.inventory_number}<small>{item.machine.name}</small></th>)}</tr></thead><tbody>{keys.map(key => <tr key={key}><th>{text(key)}</th>{items.map(item => {
    const entry = Object.entries(item.metrics).find(([, values]) => values?.some(m => m.key === key)), metric = entry?.[1]?.find(m => m.key === key)
    return <td key={item.machine.id}>{metric ? <button type="button" className="link" onClick={() => drill(item.machine, metric, entry![0] as Kind)}>{metric.value == null ? text('insufficient') : `${number(Math.round(metric.value * 100) / 100)} ${text(metric.unit)}`}</button> : text('unavailable')}{metric?.sample != null && <small>{text('sample', { count: metric.sample })}</small>}</td>
  })}</tr>)}</tbody></table></div>
}
