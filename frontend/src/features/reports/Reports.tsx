import { useState } from 'react'
import { FileText } from 'lucide-react'
import { downloadApiFile } from '../../api'
import { useI18n } from '../../i18n'

export default function Reports() {
  const { t } = useI18n()
  const [error, setError] = useState('')
  const download = () => downloadApiFile('/reports/daily.pdf', 'assetcore-daily-report.pdf')
    .catch(() => setError(t('reports.downloadError')))
  return (
    <div className="panel">
      <div className="panel-title"><div><h3>{t('reports.title')}</h3><p className="muted">{t('reports.subtitle')}</p></div><FileText /></div>
      {error && <div className="error" role="alert">{error}</div>}
      <div className="report-options"><button className="primary" onClick={download}>{t('reports.downloadDaily')}</button><div className="report-description">{t('reports.description')}</div></div>
    </div>
  )
}
