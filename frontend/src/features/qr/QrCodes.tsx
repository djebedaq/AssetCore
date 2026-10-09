import { useEffect, useRef, useState } from 'react'
import { api, createApiObjectUrl } from '../../api'
import AuthenticatedImage from '../../AuthenticatedImage'
import { useI18n } from '../../i18n'
import type { Machine, RegistryCategory } from '../../types'
import { Select } from '../../ui/Select'
import { Pagination, queryParams, usePage, type PageData } from '../../ui/workspace'

type PrintLabel = { machine: Machine; url: string }

export default function QrCodes() {
  const { t, locale } = useI18n()
  const [categories, setCategories] = useState<RegistryCategory[]>([])
  const [selectedCode, setSelectedCode] = useState('')
  const [page, setPage] = useState(1)
  const [error, setError] = useState(false)
  const [preparing, setPreparing] = useState(false)
  const [printLabels, setPrintLabels] = useState<PrintLabel[] | null>(null)
  const alive = useRef(true)
  const selectedCategory = categories.find(category => category.code === selectedCode)
  const categoryParams = { category_id: selectedCode === 'ALL' ? undefined : selectedCategory?.id }
  const { data, loading, error: pageError } = usePage<Machine>(selectedCode ? `/workspace/machines?${queryParams({ ...categoryParams, page, page_size: 24, sort: 'oldest' })}` : null)
  useEffect(() => {
    alive.current = true
    void api<RegistryCategory[]>('/machines/category-navigation').then(value => { if (alive.current) setCategories(value) }).catch(() => { if (alive.current) setError(true) })
    return () => { alive.current = false }
  }, [])
  useEffect(() => {
    const done = () => setPrintLabels(null)
    window.addEventListener('afterprint', done)
    return () => window.removeEventListener('afterprint', done)
  }, [])
  useEffect(() => () => { printLabels?.forEach(label => URL.revokeObjectURL(label.url)) }, [printLabels])

  function chooseCategory(code: string) { setSelectedCode(code); setPage(1); setPrintLabels(null); setError(false) }

  async function preparePrint() {
    if (!selectedCode || preparing || !data?.total) return
    setPreparing(true); setError(false)
    const labels: PrintLabel[] = []
    try {
      const machines: Machine[] = []
      let next = 1
      let hasNext = true
      while (hasNext) {
        const result = await api<PageData<Machine>>(`/workspace/machines?${queryParams({ ...categoryParams, page: next, page_size: 100, sort: 'oldest' })}`)
        machines.push(...result.items); hasNext = result.has_next; next += 1
      }
      if (!machines.length || new Set(machines.map(machine => machine.id)).size !== machines.length || machines.length !== data.total) throw new Error('qr_scope_changed')
      // Print is explicit; ordinary display only loads one page of images.
      for (let start = 0; start < machines.length; start += 6) {
        const batch = await Promise.allSettled(machines.slice(start, start + 6).map(async machine => {
          const { url } = await createApiObjectUrl(`/machines/${machine.id}/qr`)
          labels.push({ machine, url })
          const image = new Image(); image.src = url; await image.decode()
        }))
        if (batch.some(result => result.status === 'rejected')) throw new Error('qr_image_failed')
      }
      if (!alive.current) { labels.forEach(label => URL.revokeObjectURL(label.url)); return }
      setPrintLabels(labels.sort((a, b) => machines.indexOf(a.machine) - machines.indexOf(b.machine)))
      await new Promise<void>(resolve => requestAnimationFrame(() => requestAnimationFrame(() => resolve())))
      window.print()
    } catch {
      labels.forEach(label => URL.revokeObjectURL(label.url))
      if (alive.current) { setPrintLabels(null); setError(true) }
    } finally { if (alive.current) setPreparing(false) }
  }

  const categoryName = (category: RegistryCategory) => category[`name_${locale}`] || category.name_bg
  return <>
    <div className="machine-category-nav" aria-label={t('machines.categories')}>
      <div className="machine-category-pills">
        {categories.map(category => <button type="button" disabled={preparing} key={category.id} aria-pressed={selectedCode === category.code} className={`machine-category${selectedCode === category.code ? ' active' : ''}`} onClick={() => chooseCategory(category.code)}><span>{categoryName(category)}</span><b>{category.asset_count}</b></button>)}
        {categories.length > 0 && <button type="button" disabled={preparing} className={`machine-category${selectedCode === 'ALL' ? ' active' : ''}`} aria-pressed={selectedCode === 'ALL'} onClick={() => chooseCategory('ALL')}>{t('machines.allCategories')}</button>}
      </div>
      <label className="machine-category-mobile">{t('machines.categories')}<Select disabled={preparing} label={t('machines.categories')} value={selectedCode} onChange={chooseCategory} placeholder={t('machines.selectCategory')} options={[...categories.map(category => ({ value: category.code, label: `${categoryName(category)} (${category.asset_count})` })), { value: 'ALL', label: t('machines.allCategories') }]} /></label>
    </div>
    <div className="toolbar qr-toolbar"><h3>{t('nav.qr')}</h3><button className="primary" disabled={!selectedCode || !data?.total || loading || preparing} onClick={() => { void preparePrint() }}>{preparing ? t('qr.preparing') : t('qr.printCount', { count: data?.total || 0 })}</button></div>
    {(error || pageError) && <div className="error" role="alert">{t('errors.generic')}</div>}
    {!selectedCode && <div className="empty-state">{t('machines.selectCategory')}</div>}
    {loading && <p role="status">{t('common.loading')}</p>}
    <div className="qr-grid qr-screen-grid">
      {data?.items.map(machine => <div className="qr-card" key={machine.id}>
        <AuthenticatedImage src={`/machines/${machine.id}/qr`} alt={t('qr.alt', { number: machine.inventory_number })} />
        <strong>{machine.name}</strong><span>{machine.brand}{machine.pressure_bar != null ? ` · ${machine.pressure_bar} bar` : ''}</span>
      </div>)}
      {selectedCode && data?.total === 0 && <div className="empty-state">{t('qr.empty')}</div>}
    </div>
    <Pagination data={data} onPage={setPage} />
    {printLabels && <div className="qr-grid qr-print-grid printable-qr-labels">{printLabels.map(({ machine, url }) => <div className="qr-card" key={machine.id}><img src={url} alt={t('qr.alt', { number: machine.inventory_number })} /><strong>{machine.name}</strong><span>{machine.brand}{machine.pressure_bar != null ? ` · ${machine.pressure_bar} bar` : ''}</span></div>)}</div>}
  </>
}
