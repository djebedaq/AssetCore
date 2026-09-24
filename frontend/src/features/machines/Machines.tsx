import { useEffect, useMemo, useState } from 'react'
import { Plus, Search } from 'lucide-react'
import { api } from '../../api'
import { statusText, useI18n } from '../../i18n'
import { hasPermission } from '../../permissions'
import type { Department, Location, Machine, RegistryCategory } from '../../types'
import MachineModal from './MachineModal'
import { LazyMachinePassportModal as MachinePassportModal } from '../passport/LazyMachinePassportModal'

const ALL = 'ALL'
const categoryFromUrl = () => new URLSearchParams(window.location.search).get('category')
const categoryLabel = (category: RegistryCategory, locale: 'bg' | 'en' | 'ru') => category[`name_${locale}`] || category.name_bg

export default function Machines({ onOpenCatalog, onOpenPassport }: { onOpenCatalog: (machineId: number) => void; onOpenPassport?: (machineId: number) => void }) {
  const { locale, t } = useI18n()
  const [items, setItems] = useState<Machine[]>([])
  const [loadedCode, setLoadedCode] = useState<string | null>(null)
  const [locations, setLocations] = useState<Location[]>([])
  const [departments, setDepartments] = useState<Department[]>([])
  const [categories, setCategories] = useState<RegistryCategory[]>([])
  const [navigationReady, setNavigationReady] = useState(false)
  const [requestedCode, setRequestedCode] = useState<string | null>(categoryFromUrl)
  const [refresh, setRefresh] = useState(0)
  const [query, setQuery] = useState('')
  const [selected, setSelected] = useState<Machine | null>(null)
  const [showNew, setShowNew] = useState(false)
  const [passportId, setPassportId] = useState<number | null>(null)
  const [error, setError] = useState(false)
  const [navigationFailed, setNavigationFailed] = useState(false)
  const [loadingItems, setLoadingItems] = useState(false)
  const showTechnicalDetails = hasPermission('documents.view')

  useEffect(() => {
    const synchronize = () => setRequestedCode(categoryFromUrl())
    window.addEventListener('popstate', synchronize)
    window.addEventListener('assetcore:routechange', synchronize)
    return () => { window.removeEventListener('popstate', synchronize); window.removeEventListener('assetcore:routechange', synchronize) }
  }, [])

  useEffect(() => {
    let active = true
    const supporting = showTechnicalDetails
      ? Promise.all([api<Location[]>('/locations'), api<Department[]>('/departments')])
      : Promise.resolve([[], []] as [Location[], Department[]])
    void Promise.all([api<RegistryCategory[]>('/machines/category-navigation'), supporting])
      .then(([navigation, [locationItems, departmentItems]]) => {
        if (!active) return
        setCategories(navigation)
        setLocations(locationItems)
        setDepartments(departmentItems)
        setNavigationReady(true)
        setNavigationFailed(false)
        setError(false)
      })
      .catch(() => { if (active) { setNavigationReady(true); setNavigationFailed(true); setError(true) } })
    return () => { active = false }
  }, [refresh, showTechnicalDetails])

  const selectedCode = requestedCode === ALL ? ALL
    : categories.some((category) => category.code === requestedCode) ? requestedCode
    : categories.length === 1 ? categories[0].code : null
  const selectedCategory = categories.find((category) => category.code === selectedCode)
  const showPressure = showTechnicalDetails && Boolean(selectedCategory?.has_pressure)

  useEffect(() => {
    if (!navigationReady || !requestedCode || selectedCode === requestedCode) return
    const url = new URL(window.location.href)
    url.searchParams.delete('category')
    window.history.replaceState(window.history.state, '', url.pathname + url.search + url.hash)
    setRequestedCode(null)
  }, [navigationReady, requestedCode, selectedCode])

  useEffect(() => {
    if (!navigationReady || navigationFailed || !selectedCode) { setItems([]); setLoadedCode(null); return }
    let active = true
    setItems([])
    setLoadedCode(null)
    setLoadingItems(true)
    const path = selectedCode === ALL ? '/machines' : `/machines?category_id=${selectedCategory?.id}`
    void api<Machine[]>(path)
      .then((machines) => { if (active) { setItems(machines); setLoadedCode(selectedCode); setError(false) } })
      .catch(() => { if (active) setError(true) })
      .finally(() => { if (active) setLoadingItems(false) })
    return () => { active = false }
  }, [navigationReady, navigationFailed, selectedCode, selectedCategory?.id, refresh])

  function chooseCategory(code: string) {
    setQuery('')
    setRequestedCode(code)
    const url = new URL(window.location.href)
    url.pathname = '/machines'
    url.searchParams.set('category', code)
    window.history.pushState({ ...window.history.state, assetcorePage: 'machines' }, '', url.pathname + url.search + url.hash)
  }

  const filtered = useMemo(() => (loadedCode === selectedCode ? items : []).filter((machine) => (
    `${machine.inventory_number} ${machine.name} ${machine.brand} ${machine.model || ''} ${statusText(t, machine.status)} ${machine.location?.name || ''}`
      .toLowerCase().includes(query.toLowerCase())
  )), [items, loadedCode, selectedCode, query, t])

  return <>
    <div className="machine-category-nav" aria-label={t('machines.categories')}>
      <div className="machine-category-pills">
        {categories.map((category) => <button type="button" key={category.id} aria-pressed={selectedCode === category.code} className={selectedCode === category.code ? 'machine-category active' : 'machine-category'} onClick={() => chooseCategory(category.code)}>
          <span>{categoryLabel(category, locale)}{!category.is_active && <small> · {t('admin.inactive')}</small>}</span><b>{category.asset_count}</b>
        </button>)}
        {categories.length > 0 && <button type="button" aria-pressed={selectedCode === ALL} className={selectedCode === ALL ? 'machine-category active' : 'machine-category'} onClick={() => chooseCategory(ALL)}><span>{t('machines.allCategories')}</span></button>}
      </div>
      {categories.length > 0 && <label className="machine-category-mobile">{t('machines.categories')}
        <select aria-label={t('machines.categories')} value={selectedCode || ''} onChange={(event) => chooseCategory(event.target.value)}>
          <option value="" disabled>{t('machines.selectCategory')}</option>
          {categories.map((category) => <option key={category.id} value={category.code}>{categoryLabel(category, locale)} ({category.asset_count}){!category.is_active ? ` · ${t('admin.inactive')}` : ''}</option>)}
          <option value={ALL}>{t('machines.allCategories')}</option>
        </select>
      </label>}
    </div>
    <div className="toolbar machine-registry-toolbar">
      <div className="search"><Search size={18} /><input aria-label={t('common.search')} placeholder={t('machines.searchPlaceholder')} value={query} onChange={(event) => setQuery(event.target.value)} disabled={!selectedCode} /></div>
      {hasPermission('assets.create') && <button className="primary" onClick={() => setShowNew(true)}><Plus size={18} />{t('machines.new')}</button>}
    </div>
    {error && <div className="error" role="alert">{t('errors.generic')}</div>}
    {!selectedCode && navigationReady ? <div className="empty-state">{t('machines.selectCategory')}</div> : selectedCode && <div className="table-card machine-registry-table">
      <table><thead><tr>
        <th>{t('machines.columnMachine')}</th>
        {selectedCode === ALL && <th>{t('machines.category')}</th>}
        <th>{t('machines.columnBrand')}</th>
        {showPressure && <th>{t('machines.columnPressure')}</th>}
        <th>{t('machines.columnStatus')}</th><th>{t('machines.columnLocation')}</th><th />
      </tr></thead><tbody>
        {filtered.map((machine) => {
          const category = categories.find((candidate) => candidate.id === machine.category_id || candidate.code === machine.category)
          return <tr key={machine.id}>
            <td><strong>{machine.name}</strong><small>{t('machines.inventoryPrefix', { number: machine.inventory_number })}</small></td>
            {selectedCode === ALL && <td>{category ? categoryLabel(category, locale) : machine.category || t('common.notSpecified')}</td>}
            <td>{machine.brand}<small>{machine.model}</small></td>
            {showPressure && <td>{machine.pressure_bar != null ? `${machine.pressure_bar} bar` : t('common.notSpecified')}</td>}
            <td><span className="badge">{statusText(t, machine.status)}</span></td>
            <td>{machine.location?.name || t('common.notSpecified')}</td>
            <td><button className="link" onClick={() => onOpenPassport ? onOpenPassport(machine.id) : setPassportId(machine.id)}>{t('passport.tab.passport')}</button>{hasPermission('assets.edit') && <button className="link" onClick={() => setSelected(machine)}>{t('common.details')}</button>}</td>
          </tr>
        })}
      </tbody></table>
      {!loadingItems && loadedCode === selectedCode && !filtered.length && <div className="empty-state">{query ? t('machines.empty') : t('machines.emptyCategory')}</div>}
    </div>}
    {selected && <MachineModal machine={selected} locations={locations} departments={departments} categories={categories} onClose={() => setSelected(null)} onSaved={() => { setSelected(null); setRefresh((value) => value + 1) }} />}
    {showNew && <MachineModal initialCategoryId={selectedCategory?.is_active ? selectedCategory.id : undefined} locations={locations} departments={departments} categories={categories} onClose={() => setShowNew(false)} onSaved={() => { setShowNew(false); setRefresh((value) => value + 1) }} />}
    {passportId && <MachinePassportModal machineId={passportId} onClose={() => setPassportId(null)} onOpenCatalog={() => { setPassportId(null); onOpenCatalog(passportId) }} />}
  </>
}
