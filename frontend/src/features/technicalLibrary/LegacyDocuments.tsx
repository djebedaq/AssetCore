import { useEffect, useMemo, useState } from 'react'
import { BookOpen } from 'lucide-react'
import { api, downloadApiFile } from '../../api'
import { useI18n } from '../../i18n'

type TechnicalDocument = {
  id: number
  brand: string
  category: string
  title: string
}

export default function Documents() {
  const { t } = useI18n()
  const [items, setItems] = useState<TechnicalDocument[]>([])
  const [error, setError] = useState('')

  useEffect(() => {
    void api<TechnicalDocument[]>('/documents').then(setItems).catch(() => setError(t('documents.loadError')))
  }, [t])

  const groups = useMemo(() => Object.entries(items.reduce<Record<string, TechnicalDocument[]>>((grouped, item) => {
    ;(grouped[item.brand] ??= []).push(item)
    return grouped
  }, {})), [items])

  const download = (id: number, name: string) => downloadApiFile(`/documents/${id}/download`, name)
    .catch(() => setError(t('documents.downloadError')))

  return (
    <>
      <div className="toolbar"><div><h3>{t('documents.title')}</h3><p className="muted">{t('documents.subtitle')}</p></div></div>
      {error && <div className="error" role="alert">{error}</div>}
      <div className="cards-list">
        {groups.map(([brand, documents]) => <div className="panel" key={brand}><div className="panel-title"><h3>{brand}</h3><BookOpen /></div><div className="activity-list">{documents.map((document) => <div key={document.id}><strong>{document.title}</strong><span>{document.category}</span><button className="link" onClick={() => download(document.id, document.title)}>{t('documents.openDownload')}</button></div>)}</div></div>)}
        {!groups.length && <div className="empty-state">{t('documents.empty')}</div>}
      </div>
    </>
  )
}
