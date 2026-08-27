import { useEffect, useState } from 'react'
import { BarChart3, Boxes, Gauge, PackageSearch, ShieldCheck, Wrench } from 'lucide-react'
import { api } from '../../api'
import { statusText, useI18n } from '../../i18n'

type DashboardData = {
  total_machines: number
  ready: number
  in_use: number
  open_repairs: number
  pending_parts: number
  status_breakdown: Record<string, number>
  recent_repairs: Array<{
    id: number
    machine: string
    problem: string
    status: string
  }>
}

export default function Dashboard() {
  const { t, number } = useI18n()
  const [data, setData] = useState<DashboardData | null>(null)
  const [error, setError] = useState(false)

  useEffect(() => {
    void api<DashboardData>('/dashboard').then(setData).catch(() => setError(true))
  }, [])

  if (error) return <div className="error" role="alert">{t('errors.generic')}</div>
  if (!data) return <div className="loading">{t('common.loading')}</div>

  const cards = [
    ['dashboard.totalMachines', data.total_machines, Boxes],
    ['dashboard.ready', data.ready, ShieldCheck],
    ['dashboard.inUse', data.in_use, Gauge],
    ['dashboard.openRepairs', data.open_repairs, Wrench],
    ['dashboard.pendingRequests', data.pending_parts, PackageSearch],
  ] as const

  return (
    <>
      <div className="stats-grid">
        {cards.map(([label, value, Icon]) => (
          <div className="stat-card" key={label}>
            <div className="stat-icon"><Icon size={23} /></div>
            <div><span>{t(label)}</span><strong>{number(value)}</strong></div>
          </div>
        ))}
      </div>
      <div className="panel-grid">
        <div className="panel">
          <div className="panel-title"><h3>{t('dashboard.machineStatus')}</h3><BarChart3 /></div>
          <div className="status-list">
            {Object.entries(data.status_breakdown).map(([status, count]) => (
              <div key={status}>
                <span>{statusText(t, status)}</span>
                <div className="bar">
                  <i style={{ width: `${Math.max(8, (count / Math.max(data.total_machines, 1)) * 100)}%` }} />
                </div>
                <b>{number(count)}</b>
              </div>
            ))}
          </div>
        </div>
        <div className="panel">
          <div className="panel-title"><h3>{t('dashboard.recentRepairs')}</h3><Wrench /></div>
          <div className="activity-list">
            {data.recent_repairs.length ? data.recent_repairs.map((repair) => (
              <div key={repair.id}>
                <strong>{repair.machine}</strong>
                <span>{repair.problem}</span>
                <em>{statusText(t, repair.status, 'repair')}</em>
              </div>
            )) : <p className="muted">{t('dashboard.noRepairs')}</p>}
          </div>
        </div>
      </div>
    </>
  )
}
