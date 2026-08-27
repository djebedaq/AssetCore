import { type ReactNode, useEffect, useMemo, useState } from 'react'
import { Download, Search } from 'lucide-react'
import { api, downloadApiFile } from '../../api'
import { useI18n } from '../../i18n'

type AuditEntry = {
  id: number
  created_at: string
  user_name?: string | null
  entity_type: string
  entity_id?: number | null
  action: string
  details?: string | null
  operation_reference?: string | null
}

function AuditDetails({ details }: { details?: string | null }) {
  const { t } = useI18n()

  const renderValue = (value: unknown): ReactNode => {
    if (value === null || value === undefined || value === '') return t('common.noValue')
    if (Array.isArray(value)) {
      return <ul>{value.map((item, index) => <li key={index}>{renderValue(item)}</li>)}</ul>
    }
    if (typeof value === 'object') {
      return (
        <dl className="audit-detail-list">
          {Object.entries(value).map(([key, nested]) => (
            <div key={key}><dt>{key.replaceAll('_', ' ')}</dt><dd>{renderValue(nested)}</dd></div>
          ))}
        </dl>
      )
    }
    if (typeof value === 'boolean') return value ? t('common.yes') : t('common.no')
    return String(value)
  }

  if (!details) return <small>{t('common.noValue')}</small>
  try {
    const parsed = JSON.parse(details) as Record<string, unknown>
    return <dl className="audit-detail-list">{Object.entries(parsed).map(([key, value]) => <div key={key}><dt>{key.replaceAll('_', ' ')}</dt><dd>{renderValue(value)}</dd></div>)}</dl>
  } catch {
    return <small>{details}</small>
  }
}

export default function Audit() {
  const { date, t } = useI18n()
  const [items, setItems] = useState<AuditEntry[]>([])
  const [error, setError] = useState('')
  const [query, setQuery] = useState('')
  useEffect(() => {
    void api<AuditEntry[]>('/audit').then(setItems).catch(() => setError(t('audit.restricted')))
  }, [t])
  const filtered = useMemo(() => items.filter((entry) => (
    `${entry.user_name || ''} ${entry.entity_type} ${entry.entity_id || ''} ${entry.action} ${entry.operation_reference || ''} ${entry.details || ''}`
      .toLowerCase()
      .includes(query.toLowerCase())
  )), [items, query])
  const exportLog = () => downloadApiFile('/audit/export.json', 'assetcore-audit.json')
    .catch(() => setError(t('audit.exportError')))
  return (
    <>
      <div className="toolbar"><div><h3>{t('audit.title')}</h3><p className="muted">{t('audit.subtitle')}</p></div><button className="secondary" onClick={exportLog}><Download size={16} />{t('audit.export')}</button></div>
      <div className="filters"><div className="searchbox"><Search size={18} /><input aria-label={t('audit.search')} value={query} onChange={(event) => setQuery(event.target.value)} placeholder={t('audit.searchPlaceholder')} /></div></div>
      {error && <div className="error" role="alert">{error}</div>}
      <div className="table-card"><table><thead><tr><th>{t('audit.date')}</th><th>{t('audit.user')}</th><th>{t('audit.entity')}</th><th>{t('audit.action')}</th><th>{t('audit.details')}</th></tr></thead><tbody>{filtered.map((entry) => <tr key={entry.id}><td>{date(entry.created_at)}</td><td>{entry.user_name || t('common.system')}</td><td>{entry.entity_type} #{entry.entity_id || t('common.noValue')}</td><td>{entry.action}</td><td><AuditDetails details={entry.details} /></td></tr>)}</tbody></table>{!filtered.length && !error && <div className="empty-state">{t('audit.empty')}</div>}</div>
    </>
  )
}
