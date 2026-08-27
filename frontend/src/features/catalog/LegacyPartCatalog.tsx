import { useEffect, useMemo, useState } from 'react'
import { Search } from 'lucide-react'
import { api } from '../../api'
import { useI18n } from '../../i18n'

type CatalogPart = {
  id: number
  brand: string
  model?: string | null
  assembly?: string | null
  position?: string | null
  part_number: string
  description: string
  quantity?: number | null
  source_document?: string | null
  source_page?: number | null
}

export default function PartCatalog() {
  const { t } = useI18n()
  const [items, setItems] = useState<CatalogPart[]>([])
  const [query, setQuery] = useState('')
  const [brand, setBrand] = useState('')
  const [error, setError] = useState(false)

  useEffect(() => {
    void api<CatalogPart[]>(`/catalog/parts?q=${encodeURIComponent(query)}&brand=${encodeURIComponent(brand)}`)
      .then((records) => {
        setItems(records)
        setError(false)
      })
      .catch(() => setError(true))
  }, [brand, query])

  const brands = useMemo(() => [...new Set(items.map((item) => item.brand))].sort(), [items])

  return (
    <>
      <div className="toolbar"><div><h3>{t('catalog.title')}</h3><p className="muted">{t('catalog.subtitle')}</p></div></div>
      <div className="filters">
        <div className="searchbox"><Search size={18} /><input aria-label={t('common.search')} value={query} onChange={(event) => setQuery(event.target.value)} placeholder={t('catalog.searchPlaceholder')} /></div>
        <select aria-label={t('machines.columnBrand')} value={brand} onChange={(event) => setBrand(event.target.value)}><option value="">{t('common.allBrands')}</option>{brands.map((item) => <option key={item}>{item}</option>)}</select>
      </div>
      {error && <div className="error" role="alert">{t('errors.generic')}</div>}
      <div className="table-card">
        <table><thead><tr><th>{t('catalog.brandModel')}</th><th>{t('catalog.assembly')}</th><th>{t('catalog.position')}</th><th>{t('common.partNumber')}</th><th>{t('catalog.description')}</th><th>{t('common.quantity')}</th><th>{t('catalog.source')}</th></tr></thead>
          <tbody>{items.map((item) => <tr key={item.id}><td><strong>{item.brand}</strong><small>{item.model}</small></td><td>{item.assembly || t('common.noValue')}</td><td>{item.position || t('common.noValue')}</td><td><strong>{item.part_number}</strong></td><td>{item.description}</td><td>{item.quantity || t('common.noValue')}</td><td>{item.source_document ? `${item.source_document.split('/').pop()} · ${t('common.page')} ${item.source_page || t('common.noValue')}` : t('common.noValue')}</td></tr>)}</tbody>
        </table>
        {!items.length && <div className="empty-state">{t('catalog.empty')}</div>}
      </div>
    </>
  )
}
