import { useEffect, useRef, useState, type CSSProperties } from 'react'
import { BarChart3, Boxes, Gauge, History, PackageSearch, ShieldCheck, Wrench } from 'lucide-react'
import { api } from '../../api'
import { useI18n } from '../../i18n'
import { translatedEventCode } from '../../industrialUi'
import { hasPermission } from '../../permissions'
import type { RegistryCategory } from '../../types'
import { StatusBadge } from '../../ui/StatusBadge'
import { openOperation } from '../../ui/workspace'

export type Activity = { event_key: string; event_type: string; module: 'transfers' | 'repairs' | 'parts'; record_id: number; occurred_at: string; machine_id: number | null; inventory_number: string | null; reference: string | null; status: string | null }
export type DashboardData = {
  total_machines: number; ready: number; in_use: number; open_repairs: number; pending_parts: number
  status_breakdown: Record<string, number>; categories: RegistryCategory[]; uncategorized_assets: number; recent_activity: Activity[]
  recent_repairs: Array<{ id: number; machine: string; problem: string; status: string }>
}
export function AnimatedNumber({ value }: { value: number }) {
  const { number } = useI18n()
  const previous = useRef(0)
  const [display, setDisplay] = useState(() => window.matchMedia?.('(prefers-reduced-motion: reduce)').matches ? value : 0)
  useEffect(() => {
    const from = previous.current; previous.current = value
    if (window.matchMedia?.('(prefers-reduced-motion: reduce)').matches || from === value) { setDisplay(value); return }
    let frame = 0
    const start = performance.now()
    function tick(now: number) {
      const progress = Math.min((now - start) / 500, 1)
      setDisplay(Math.round(from + (value - from) * (1 - (1 - progress) ** 3)))
      if (progress < 1) frame = requestAnimationFrame(tick)
    }
    frame = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(frame)
  }, [value])
  return <><span aria-hidden="true">{number(display)}</span><span className="sr-only">{number(value)}</span></>
}
const delay = (index: number) => ({ '--ac-delay': `${index * 45}ms` } as CSSProperties)

export default function Dashboard() {
  const { t, number, locale, date } = useI18n()
  const [data, setData] = useState<DashboardData | null>(null)
  const [error, setError] = useState(false)
  const [barsReady, setBarsReady] = useState(false)
  useEffect(() => {
    const controller = new AbortController()
    void api<DashboardData>('/dashboard', { signal: controller.signal }).then(value => { if (!controller.signal.aborted) setData(value) }).catch(() => { if (!controller.signal.aborted) setError(true) })
    return () => controller.abort()
  }, [])
  useEffect(() => {
    if (!data) return
    const frame = requestAnimationFrame(() => setBarsReady(true))
    return () => cancelAnimationFrame(frame)
  }, [data])
  if (error) return <div className="error" role="alert">{t('errors.generic')}</div>
  if (!data) return <div className="loading" role="status">{t('common.loading')}</div>
  const cards = [
    ['dashboard.totalMachines', data.total_machines, Boxes], ['dashboard.ready', data.ready, ShieldCheck],
    ['dashboard.inUse', data.in_use, Gauge], ['dashboard.openRepairs', data.open_repairs, Wrench],
    ['dashboard.pendingRequests', data.pending_parts, PackageSearch],
  ] as const
  return <div className="ac-dashboard">
    <div className="stats-grid">{cards.map(([label, value, Icon], index) => <div className="stat-card" key={label} style={delay(index)}>
      <div className="stat-icon"><Icon size={21} /></div><div><span>{t(label)}</span><strong><AnimatedNumber value={value} /></strong></div>
    </div>)}</div>
    <div className="panel-grid">
      <section className="panel" style={delay(2)}><div className="panel-title"><h3>{t('dashboard.machineStatus')}</h3><BarChart3 size={19} /></div>
        <div className="status-list">{Object.entries(data.status_breakdown).map(([status, count]) => {
          const percentage = count / Math.max(data.total_machines, 1) * 100
          return <div key={status}><StatusBadge status={status} /><div className="bar" role="meter" aria-label={t('dashboard.machineStatus')} aria-valuemin={0} aria-valuemax={data.total_machines} aria-valuenow={count}>
            <i style={{ width: `${barsReady ? percentage : 0}%` }} /></div><b>{number(count)}</b></div>
        })}</div>
      </section>
      <section className="panel" style={delay(3)}><div className="panel-title"><h3>{t('ux.categoryCounts')}</h3><Boxes size={19} /></div>
        <div className="ac-category-counts">{(data.categories || []).map(category => <div key={category.id}><span>{category[`name_${locale}`] || category.name_bg}{!category.is_active && <small> · {t('admin.inactive')}</small>}</span><b>{number(category.asset_count)}</b></div>)}
          {data.uncategorized_assets > 0 && <div><span>{t('ux.uncategorized')}</span><b>{number(data.uncategorized_assets)}</b></div>}
          <div className="ac-category-total"><span>{t('ux.totalAssets')}</span><b>{number(data.total_machines)}</b></div>
        </div>
      </section>
      <section className="panel" style={delay(4)}><div className="panel-title"><h3>{t('ux.recentActivity')}</h3><History size={19} /></div>
        {(data.recent_activity || []).length ? <ol className="ac-activity">{data.recent_activity.map(item => <li key={item.event_key}>
          <button type="button" disabled={!hasPermission(item.module === 'parts' ? 'requests.view' : item.module === 'repairs' ? 'repairs.view' : 'transfers.view')}
            onClick={() => openOperation({ module: item.module, recordId: item.record_id, machineId: item.machine_id || undefined })}>
            <time dateTime={item.occurred_at}>{date(item.occurred_at)}</time><span><strong>{translatedEventCode(t, item.event_type)}</strong>
              <small>{item.inventory_number ? t('ux.activityAsset', { number: item.inventory_number }) : t('ux.activityGeneral')}{item.reference && ` · ${item.reference}`} · {t(item.module === 'parts' ? 'nav.parts' : item.module === 'repairs' ? 'nav.repairs' : 'nav.transfers')}</small>
            </span>
          </button>
        </li>)}</ol> : <p className="muted">{t('ux.noActivity')}</p>}
      </section>
      <section className="panel" style={delay(5)}><div className="panel-title"><h3>{t('dashboard.recentRepairs')}</h3><Wrench size={19} /></div>
        <div className="activity-list">{data.recent_repairs.length ? data.recent_repairs.map(repair => <div key={repair.id}><button className="link" onClick={() => openOperation({ module: 'repairs', recordId: repair.id })}>{repair.machine}</button><span>{repair.problem}</span><StatusBadge status={repair.status} domain="repair" /></div>) : <p className="muted">{t('dashboard.noRepairs')}</p>}</div>
      </section>
    </div>
  </div>
}
