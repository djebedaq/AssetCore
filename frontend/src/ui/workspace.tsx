import { useEffect, useState, type ReactNode } from 'react'
import { ArrowLeft, ArrowRight, Search, RotateCcw } from 'lucide-react'
import { api } from '../api'
import { useI18n } from '../i18n'
import type { Machine, RegistryCategory } from '../types'
import { Select } from './Select'

export type PageData<T> = { items: T[]; total: number; page: number; page_size: number; total_pages: number; has_previous: boolean; has_next: boolean }
export type WorkspaceModule = 'machines' | 'transfers' | 'repairs' | 'requests' | 'catalog'
export function useDebounced<T>(value: T, delay = 250) {
  const [result, setResult] = useState(value)
  useEffect(() => { const timer = window.setTimeout(() => setResult(value), delay); return () => window.clearTimeout(timer) }, [value, delay])
  return result
}
export function usePage<T>(path: string | null, refresh = 0) {
  const [data, setData] = useState<PageData<T> | null>(null)
  const [error, setError] = useState(false)
  const [loading, setLoading] = useState(false)
  useEffect(() => {
    const controller = new AbortController()
    setData(null); setError(false); setLoading(Boolean(path))
    if (!path) return
    void api<PageData<T>>(path, { signal: controller.signal }).then(value => { if (!controller.signal.aborted) setData(value) })
      .catch(() => { if (!controller.signal.aborted) setError(true) }).finally(() => { if (!controller.signal.aborted) setLoading(false) })
    return () => controller.abort()
  }, [path, refresh])
  return { data, error, loading }
}
export function useCategories(module: WorkspaceModule, refresh = 0) {
  const [categories, setCategories] = useState<RegistryCategory[]>([])
  const [error, setError] = useState(false)
  useEffect(() => {
    const controller = new AbortController()
    void api<RegistryCategory[]>(`/workspace/categories?module=${module}`, { signal: controller.signal }).then(value => { if (!controller.signal.aborted) { setCategories(value); setError(false) } }).catch(() => { if (!controller.signal.aborted) setError(true) })
    return () => controller.abort()
  }, [module, refresh])
  return { categories, error }
}
export function categoryParams(category: string) { return category === 'legacy' || category === 'mixed' ? { scope: category } : category ? { category_id: category } : {} }
const INITIAL_FILTERS = { category: '', status: '', q: '', from: '', to: '', sort: 'newest', machine: '' }
export function useWorkspaceFilters() {
  const [values, setValues] = useState(INITIAL_FILTERS)
  const [page, setPage] = useState(1)
  const q = useDebounced(values.q)
  const change = (key: keyof typeof INITIAL_FILTERS, value: string) => { setValues(current => ({ ...current, [key]: value, ...(key === 'category' ? { machine: '' } : {}) })); setPage(1) }
  const reset = () => { setValues(INITIAL_FILTERS); setPage(1) }
  return { values, change, reset, page, setPage, params: { ...categoryParams(values.category), q, status: values.status, date_from: values.from, date_to: values.to, sort: values.sort, machine_id: values.machine, page } }
}

export function MachineSelect({ module, category = '', value, onChange, disabled = false, status = '', label }: { module: WorkspaceModule; category?: string; value: string; onChange: (value: string) => void; disabled?: boolean; status?: string; label?: string }) {
  const { t } = useI18n()
  const [query, setQuery] = useState('')
  const q = useDebounced(query)
  const { data, loading, error } = usePage<Machine>(disabled ? null : `/workspace/machines?${queryParams({ module, ...categoryParams(category), status, active_only: status === 'READY' ? 'true' : undefined, q, page_size: 100, sort: 'oldest' })}`)
  const [selected, setSelected] = useState<Machine | null>(null)
  useEffect(() => {
    let active = true
    if (!value) { setSelected(null); return }
    void api<Machine>(`/machines/${value}`).then(machine => { if (active) setSelected(machine) }).catch(() => { if (active) setSelected(null) })
    return () => { active = false }
  }, [value])
  const machines = data?.items || []
  const options = selected && !machines.some(item => item.id === selected.id) ? [selected, ...machines] : machines
  return <label className="ac-filter"><span>{label || t('common.machine')}</span><Select label={label || t('common.machine')} value={value} onChange={onChange} disabled={disabled} onSearch={setQuery} loading={loading} invalid={error}
    placeholder={t(disabled ? 'ux.categoryFirst' : 'catalog.chooseMachinePlaceholder')}
    options={[{ value: '', label: t('catalog.chooseMachinePlaceholder') }, ...options.map(machine => ({ value: String(machine.id), label: `№${machine.inventory_number} · ${machine.name} · ${machine.brand}` }))]} />
    {error && <small role="alert">{t('errors.generic')}</small>}
    {data?.has_next && <small>{t('ux.moreMachines', { count: data.page_size })}</small>}
  </label>
}
export function queryParams(values: Record<string, string | number | undefined>) {
  return new URLSearchParams(Object.entries(values).filter(([, value]) => value !== '' && value !== undefined).map(([key, value]) => [key, String(value)])).toString()
}
export function CategorySelect({ categories, value, onChange, legacy = false, mixed = false, all = true }: { categories: RegistryCategory[]; value: string; onChange: (value: string) => void; legacy?: boolean; mixed?: boolean; all?: boolean }) {
  const { t, locale } = useI18n()
  return <label className="ac-filter"><span>{t('machines.category')}</span><Select label={t('machines.category')} value={value} onChange={onChange}
    placeholder={t('machines.selectCategory')} options={[
      ...(all ? [{ value: '', label: t('machines.allCategories') }] : []),
      ...categories.map(category => ({ value: String(category.id), label: `${category[`name_${locale}`] || category.name_bg}${!category.is_active ? ` · ${t('admin.inactive')}` : ''}` })),
      ...(legacy ? [{ value: 'legacy', label: t('ux.legacy') }] : []), ...(mixed ? [{ value: 'mixed', label: t('ux.mixed') }] : []),
    ]} /></label>
}
export function FilterToolbar({ query, onQuery, onReset, children, searchLabel, searchPlaceholder }: { searchLabel?: string; searchPlaceholder?: string; query?: string; onQuery?: (value: string) => void; onReset: () => void; children: ReactNode }) {
  const { t } = useI18n()
  return <div className="ac-filter-toolbar" role="group" aria-label={t('ux.filters')}>
    {children}{onQuery && <label className="ac-filter ac-filter-search"><span>{searchLabel || t('common.search')}</span><div className="search"><Search size={16} aria-hidden="true" /><input aria-label={searchLabel || t('common.search')} value={query || ''} placeholder={searchPlaceholder || t('ux.searchHint')} onChange={event => onQuery(event.target.value)} /></div></label>}
    <button type="button" className="secondary compact ac-reset" onClick={onReset}><RotateCcw size={14} aria-hidden="true" />{t('ux.reset')}</button>
  </div>
}
export function SortSelect({ value, onChange }: { value: string; onChange: (value: string) => void }) {
  const { t } = useI18n()
  return <label className="ac-filter"><span>{t('ux.sort')}</span><Select label={t('ux.sort')} value={value} onChange={onChange} searchable={false} options={[{ value: 'newest', label: t('ux.newest') }, { value: 'oldest', label: t('ux.oldest') }]} /></label>
}
export function DateFilters({ from, to, onFrom, onTo }: { from: string; to: string; onFrom: (value: string) => void; onTo: (value: string) => void }) {
  const { t } = useI18n()
  return <><label className="ac-filter ac-filter-date"><span>{t('ux.from')}</span><input aria-label={t('ux.from')} type="date" value={from} max={to || undefined} onChange={event => onFrom(event.target.value)} /></label><label className="ac-filter ac-filter-date"><span>{t('ux.to')}</span><input aria-label={t('ux.to')} type="date" value={to} min={from || undefined} onChange={event => onTo(event.target.value)} /></label></>
}
export function Pagination({ data, onPage }: { data: Omit<PageData<unknown>, 'items'> | null; onPage: (page: number) => void }) {
  const { t } = useI18n()
  if (!data) return null
  return <nav className="ac-pagination" aria-label={t('ux.pagination')}>
    <span role="status">{t('ux.resultCount', { count: data.total })}</span>
    <div><button type="button" className="secondary compact" disabled={!data.has_previous} onClick={() => onPage(data.page - 1)}><ArrowLeft size={14} />{t('timeline.previous')}</button>
      <span>{t('timeline.page', { page: data.page, pages: Math.max(1, data.total_pages) })}</span><button type="button" className="secondary compact" disabled={!data.has_next} onClick={() => onPage(data.page + 1)}>{t('timeline.next')}<ArrowRight size={14} /></button></div>
  </nav>
}

export type OperationTarget = { module: 'transfers' | 'repairs' | 'parts' | 'documents'; recordId: number; machineId?: number }
export function openOperation(target: OperationTarget) { window.dispatchEvent(new CustomEvent('assetcore:operation', { detail: target })) }
