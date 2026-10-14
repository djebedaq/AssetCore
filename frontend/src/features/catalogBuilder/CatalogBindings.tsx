import { useEffect, useRef, useState } from 'react'
import { api, ApiError } from '../../api'
import { useI18n } from '../../i18n'
import { MachineSelect } from '../../ui/workspace'
import { hasPermission } from '../../permissions'
import CatalogDialog from './CatalogDialog'
import { builderBase, problemKeys, type Catalog, type Category, type Names } from './wizardTypes'

type Compatibility = 'EXACT' | 'AMBIGUOUS' | 'INCOMPATIBLE'
type Machine = { id: number; inventory_number: string; name: string; brand: string; model: string | null;
  serial_number: string | null; is_active: boolean; bound?: boolean; compatibility?: Compatibility; code?: string | null }
type Binding = { id: number; catalog_id: number; machine_id: number; category_id: number; machine: Machine;
  catalog: Names & { code: string }; status: 'ACTIVE' | 'PENDING_PUBLICATION'; expected_digest: string;
  published_revision: { id: number; revision_code: string } | null }
type Page<T> = { items: T[]; total: number; offset: number; limit: number }
type Plan = { ready: boolean; digest: string; machines: Machine[]; published_revision: { id: number; revision_code: string } | null }
const empty = <T,>(): Page<T> => ({ items: [], total: 0, offset: 0, limit: 50 })
const post = (body: unknown) => ({ method: 'POST', body: JSON.stringify(body) })

export default function CatalogBindings({ catalogs, categories, catalogId, onClose, onChanged }: {
  catalogs: Catalog[]; categories: Category[]; catalogId?: number; onClose: () => void; onChanged: () => Promise<void>
}) {
  const { t, locale } = useI18n()
  const initial = catalogs.find(row => row.id === catalogId)
  const [mode, setMode] = useState<'connect' | 'active'>('connect')
  const [category, setCategory] = useState(initial?.asset_category_id || 0)
  const [catalog, setCatalog] = useState(catalogId || 0)
  const [machineFilter, setMachineFilter] = useState(0)
  const [search, setSearch] = useState('')
  const [offset, setOffset] = useState(0)
  const [machines, setMachines] = useState<Page<Machine>>(empty)
  const [links, setLinks] = useState<Page<Binding>>(empty)
  const [selected, setSelected] = useState<Record<number, Machine>>({})
  const [removing, setRemoving] = useState<Record<number, Binding>>({})
  const [removalPreview, setRemovalPreview] = useState<Binding[] | null>(null)
  const [confirmed, setConfirmed] = useState<number[]>([])
  const [plan, setPlan] = useState<Plan | null>(null)
  const [stage, setStage] = useState<'select' | 'review' | 'remove'>('select')
  const [closeWarning, setCloseWarning] = useState(false)
  const [pendingCategory, setPendingCategory] = useState<number | null>(null)
  const [loading, setLoading] = useState(false)
  const [previewLoading, setPreviewLoading] = useState(false)
  const [busy, setBusy] = useState(false)
  const busyRef = useRef(false)
  const [refresh, setRefresh] = useState(0)
  const [error, setError] = useState('')
  const [issues, setIssues] = useState<Machine[]>([])
  const [success, setSuccess] = useState('')
  const heading = useRef<HTMLHeadingElement>(null)
  const categoryControl = useRef<HTMLSelectElement>(null)
  const categoryWarningOpened = useRef(false)
  const chosen = catalogs.find(row => row.id === catalog)
  const name = (row: Names) => row[`name_${locale}`] || row.name_bg
  const reason = (code?: string | null) => code ? t(problemKeys[code] || 'builder.error.generic') : ''
  const rows = Object.values(selected)
  const removals = Object.values(removing)
  const removalTargets = removalPreview || removals
  const dirty = rows.length > 0 || removals.length > 0 || !!removalPreview?.length
  useEffect(() => { heading.current?.focus() }, [stage, closeWarning])
  useEffect(() => {
    if (pendingCategory !== null) { heading.current?.focus(); categoryWarningOpened.current = true }
    else if (categoryWarningOpened.current) { categoryControl.current?.focus(); categoryWarningOpened.current = false }
  }, [pendingCategory])
  useEffect(() => {
    const before = (event: BeforeUnloadEvent) => { if (dirty || busy) event.preventDefault() }
    window.addEventListener('beforeunload', before)
    return () => window.removeEventListener('beforeunload', before)
  }, [dirty, busy])
  useEffect(() => {
    let active = true
    if (mode === 'connect' && !category) { setMachines(empty()); setLoading(false); return }
    setLoading(true); setError(''); setMachines(empty()); setLinks(empty())
    const query = new URLSearchParams({ offset: String(offset), limit: '50', search })
    if (category) query.set('category_id', String(category))
    if (catalog) query.set('catalog_id', String(catalog))
    if (machineFilter && mode === 'active') query.set('machine_id', String(machineFilter))
    const timer = window.setTimeout(() => {
      void (mode === 'connect' ? api<Page<Machine>>(`${builderBase}/bindings/machines?${query}`).then(value => { if (active) setMachines(value) })
        : api<Page<Binding>>(`${builderBase}/bindings?${query}`).then(value => { if (active) setLinks(value) }))
        .catch(() => { if (active) setError(t('builder.error.generic')) })
        .finally(() => { if (active) setLoading(false) })
    }, 200)
    return () => { active = false; window.clearTimeout(timer) }
  }, [mode, category, catalog, machineFilter, search, offset, refresh, t])
  useEffect(() => {
    let active = true
    setPlan(null); setPreviewLoading(false)
    if (mode !== 'connect' || !catalog || !Object.keys(selected).length) return
    setPreviewLoading(true)
    void api<Plan>(`${builderBase}/bindings/preview`, post({ catalog_id: catalog, machine_ids: Object.values(selected).map(row => row.id), confirmed_machine_ids: confirmed }))
      .then(value => { if (active) setPlan(value) }).catch(() => { if (active) setError(t('builder.error.generic')) })
      .finally(() => { if (active) setPreviewLoading(false) })
    return () => { active = false }
  }, [catalog, selected, confirmed, mode, refresh, t])
  function close() { if (busyRef.current) return; if (dirty) setCloseWarning(true); else onClose() }
  function applyCategory(next: number) {
    setCategory(next); setCatalog(0); setMachineFilter(0); setOffset(0)
    setSelected({}); setConfirmed([]); setPlan(null); setPreviewLoading(false)
    setPendingCategory(null)
  }
  function changeCategory(next: number) {
    if (busyRef.current || next === category) return
    // Category is shared by both views; never retain a hidden connection
    // selection from a different category when changing the active filters.
    if (rows.length) setPendingCategory(next)
    else applyCategory(next)
  }
  function resetSelection() {
    if (mode === 'connect') { setSelected({}); setConfirmed([]); setPlan(null) }
    else setRemoving({})
    setRemovalPreview(null); setStage('select')
  }
  function toggleMachine(row: Machine, checked: boolean) {
    setSelected(current => { const next = { ...current }; if (checked && Object.keys(next).length < 500) next[row.id] = row; else if (!checked) delete next[row.id]; return next })
    setConfirmed(current => current.filter(id => id !== row.id))
  }
  function toggleBinding(row: Binding, checked: boolean) {
    setRemoving(current => { const next = { ...current }; if (checked && Object.keys(next).length < 500) next[row.id] = row; else if (!checked) delete next[row.id]; return next })
  }
  async function reload() {
    if (busyRef.current) return
    busyRef.current = true; setBusy(true); setError('')
    try { await onChanged(); setRefresh(value => value + 1) }
    catch { setError(t('builder.error.generic')) }
    finally { busyRef.current = false; setBusy(false) }
  }
  async function save() {
    if (busyRef.current || stage === 'review' && (!plan?.ready || previewLoading)) return
    busyRef.current = true; setBusy(true); setError(''); setIssues([]); setSuccess('')
    try {
      if (stage === 'review') {
        const result = await api<{ count: number; machines: Machine[] }>(`${builderBase}/bindings/batch`, post({
          catalog_id: catalog, machine_ids: rows.map(row => row.id), confirmed_machine_ids: confirmed, expected_digest: plan?.digest,
        }))
        setSuccess(`${t('ux06.connected', { count: result.count })} · ${chosen ? name(chosen) : ''} · ${result.machines.map(row => row.inventory_number).join(', ')}`)
      } else {
        const result = await api<{ count: number }>(`${builderBase}/bindings/batch-deactivate`, post({ bindings: removalTargets.map(row => ({
          binding_id: row.id, catalog_id: row.catalog_id, machine_id: row.machine_id, expected_digest: row.expected_digest,
        })) }))
        setSuccess(`${t('ux06.removed', { count: result.count })} · ${removalTargets.map(row => `${row.machine.inventory_number} / ${name(row.catalog)}`).join(', ')}`)
      }
      if (stage === 'review') resetSelection()
      else {
        setRemoving(current => Object.fromEntries(Object.entries(current).filter(([, row]) => !removalTargets.some(target => target.id === row.id))))
        setRemovalPreview(null); setStage('select')
      }
      setRefresh(value => value + 1)
      await onChanged()
    } catch (caught) {
      setError(caught instanceof ApiError ? reason(caught.code) : t('builder.error.generic'))
      if (caught instanceof ApiError && Array.isArray(caught.data.issues)) setIssues(caught.data.issues as Machine[])
      setPlan(null)
      // Keep the exact removal snapshot on failure: refreshing its digests must
      // require a new explicit selection and review, never silently approve ABA.
    } finally { busyRef.current = false; setBusy(false) }
  }
  if (!hasPermission('parts.manage')) return null
  const page = mode === 'connect' ? machines : links
  const eligiblePage = machines.items.filter(row => row.is_active && !row.bound)
  return <CatalogDialog wide title={t('ux06.title')} onClose={close}>
    <div className="catalog-bindings" aria-busy={busy || loading}>
      {error && <div role="alert" className="error"><p>{error}</p>{issues.map(row => <p key={row.id}>{row.inventory_number || row.id} · {reason(row.code)}</p>)}
        <button className="secondary" disabled={busy} onClick={() => { resetSelection(); setRefresh(value => value + 1); setError(''); setIssues([]) }}>{t('ux06.reload')}</button></div>}
      {success && <p role="status" className="success">{success}</p>}
      {closeWarning ? <section><h4 ref={heading} tabIndex={-1}>{t('ux06.discard')}</h4><div className="actions">
        <button className="secondary" onClick={() => setCloseWarning(false)}>{t('common.cancel')}</button>
        <button className="danger" onClick={onClose}>{t('common.close')}</button></div></section> : pendingCategory !== null ? <section>
        <h4 ref={heading} tabIndex={-1}>{t('ux06.changeCategory')}</h4>
        <p>{t('ux06.categorySelectionWarning')}</p><p>{t('ux06.selected', { count: rows.length })}</p>
        <div className="actions"><button className="secondary" onClick={() => setPendingCategory(null)}>{t('common.cancel')}</button>
          <button className="danger" onClick={() => applyCategory(pendingCategory)}>{t('ux06.clearAndChangeCategory')}</button></div>
      </section> : stage !== 'select' ? <section>
        <h4 ref={heading} tabIndex={-1}>{t(stage === 'review' ? 'ux06.preview' : 'ux06.removePreview')}</h4>
        {stage === 'review' ? <><p><b>{chosen && name(chosen)}</b> · {chosen && name(chosen.asset_category)} · {plan?.published_revision?.revision_code}</p>
          <p>{t('ux06.selected', { count: rows.length })} · {(['EXACT', 'AMBIGUOUS', 'INCOMPATIBLE'] as const).map(code => `${t(`ux06.${code}`)}: ${plan?.machines.filter(row => row.compatibility === code).length || 0}`).join(' · ')} · {t('ux06.already')}: {plan?.machines.filter(row => row.code === 'catalog_asset_already_bound').length || 0}</p>
          {previewLoading && <p role="status">{t('wizard.loading')}</p>}
          {plan?.machines.map(row => <article className="binding-card" key={row.id}><div><b>{row.inventory_number || row.id}</b> · {row.name}<p>{t(`ux06.${row.compatibility || 'INCOMPATIBLE'}`)} · {reason(row.code)}</p>
            {row.compatibility === 'AMBIGUOUS' && <label><input type="checkbox" disabled={busy} checked={confirmed.includes(row.id)} onChange={event => setConfirmed(current => event.target.checked ? [...current, row.id] : current.filter(id => id !== row.id))} />{t('ux06.confirmMachine', { machine: row.inventory_number })}</label>}</div>
            <button className="secondary" disabled={busy} onClick={() => toggleMachine(row, false)}>{t('ux06.deselect')}</button></article>)}
        </> : <><p>{t('ux06.removeWarning')}</p><p>{t('ux06.selectedLinks', { count: removalTargets.length })}</p>
          {removalTargets.map(row => <article className="binding-card" key={row.id}><b>{row.machine.inventory_number} · {row.machine.name}</b><span>{name(row.catalog)} · {row.catalog.code} · {row.published_revision?.revision_code || t('ux06.pending')}</span></article>)}</>}
        <div className="actions"><button className="secondary" disabled={busy} onClick={() => { setRemovalPreview(null); setStage('select') }}>{t('common.cancel')}</button>
          <button className={stage === 'remove' ? 'danger' : 'primary'} disabled={busy || stage === 'review' && (!plan?.ready || previewLoading || !rows.length) || stage === 'remove' && !removalTargets.length} onClick={() => void save()}>{t(stage === 'remove' ? 'ux06.confirmRemove' : 'ux06.confirmBind')}</button></div>
      </section> : <>
        <nav className="actions" aria-label={t('ux06.title')}>{(['connect', 'active'] as const).map(value => <button className="secondary" disabled={busy} aria-pressed={mode === value} key={value} onClick={() => { setMode(value); setOffset(0); setSearch(''); setMachineFilter(0); setStage('select') }}>{t(`ux06.${value}`)}</button>)}
          <button className="secondary" disabled={busy} onClick={() => void reload()}>{t('ux06.refresh')}</button></nav>
        <div className="binding-filters">
          <label>{t('builder.category')}<select ref={categoryControl} aria-label={t('builder.category')} value={category} onChange={event => changeCategory(Number(event.target.value))}><option value="">{t(mode === 'active' ? 'ux06.allCategories' : 'guided.select')}</option>{categories.filter(row => row.capabilities.includes('HAS_PARTS_CATALOG') && (mode === 'active' || row.is_active)).map(row => <option key={row.id} value={row.id}>{name(row)}</option>)}</select></label>
          <label>{t('ux06.search')}<input type="search" maxLength={120} value={search} onChange={event => { setSearch(event.target.value); setOffset(0) }} /></label>
        </div>
        {mode === 'connect' ? <>
          <p>{t('ux06.selected', { count: rows.length })} · {t('ux06.pageHelp')} · {t('ux06.limit')}</p>
          <div className="binding-selection">{rows.map(row => <button className="secondary" key={row.id} onClick={() => toggleMachine(row, false)} aria-label={t('ux06.deselectMachine', { machine: row.inventory_number })}>{row.inventory_number} ×</button>)}</div>
          {!!machines.items.length && <label className="binding-select-page"><input type="checkbox" checked={eligiblePage.length > 0 && eligiblePage.every(row => !!selected[row.id])} disabled={!eligiblePage.length || rows.length + eligiblePage.filter(row => !selected[row.id]).length > 500} onChange={event => { const checked = event.target.checked; setSelected(current => { const next = { ...current }; eligiblePage.forEach(row => { if (checked) next[row.id] = row; else delete next[row.id] }); return next }); if (!checked) setConfirmed(current => current.filter(id => !eligiblePage.some(row => row.id === id))) }} />{t('ux06.selectPage', { count: eligiblePage.length })}</label>}
          {machines.items.map(row => <article className="binding-card" key={row.id}><label><input type="checkbox" disabled={!row.is_active || row.bound || rows.length >= 500 && !selected[row.id]} checked={!!selected[row.id]} onChange={event => toggleMachine(row, event.target.checked)} /><span><b>{row.inventory_number}</b> · {row.name}<small>{row.brand} · {row.model} · {row.serial_number || t('common.noValue')}</small></span></label>
            <span>{row.bound ? t('ux06.already') : !row.is_active ? t('ux06.inactiveMachine') : row.compatibility ? t(`ux06.${row.compatibility}`) : t('ux06.chooseCatalog')}</span></article>)}
          <label>{t('ux06.catalog')}<select aria-label={t('ux06.catalog')} value={catalog} disabled={!category} onChange={event => { setCatalog(Number(event.target.value)); setConfirmed([]); setOffset(0) }}><option value="">{t('guided.select')}</option>{catalogs.filter(row => row.asset_category_id === category).map(row => <option key={row.id} value={row.id} disabled={!row.is_active || !row.published_revision}>{name(row)} · {name(row.asset_category)} · {row.manufacturer} · {row.model_reference} · {row.code} · {row.published_revision?.revision_code || t('ux06.publishFirst')} · {t('ux06.boundCount', { count: row.active_asset_count || 0 })}{!row.is_active ? ` · ${t('builder.inactive')}` : ''}</option>)}</select></label>
          <p className="muted">{t('ux06.publishFirst')}</p>
          {chosen && <p>{name(chosen)} · {chosen.published_revision?.revision_code || t('ux06.pending')} · {chosen.manufacturer} · {chosen.model_reference}</p>}
          <button className="primary" disabled={!rows.length || !chosen?.is_active || !chosen.published_revision || previewLoading || !plan} onClick={() => setStage('review')}>{t('ux06.preview')}</button>
        </> : <>
          <div className="binding-filters"><label>{t('ux06.catalog')}<select aria-label={t('ux06.catalog')} value={catalog} onChange={event => { setCatalog(Number(event.target.value)); setOffset(0) }}><option value="">{t('ux06.allCatalogs')}</option>{catalogs.filter(row => !category || row.asset_category_id === category).map(row => <option key={row.id} value={row.id}>{name(row)} · {row.code}</option>)}</select></label>
            <MachineSelect module="catalog" category={String(category || '')} label={t('ux06.machineFilter')} value={String(machineFilter || '')} onChange={value => { setMachineFilter(Number(value)); setOffset(0) }} /></div>
          <p>{t('ux06.selectedLinks', { count: removals.length })} · {t('ux06.pageHelp')} · {t('ux06.limit')}</p>
          {!!links.items.length && <label className="binding-select-page"><input type="checkbox" checked={links.items.every(row => !!removing[row.id])} disabled={removals.length + links.items.filter(row => !removing[row.id]).length > 500} onChange={event => { const checked = event.target.checked; setRemoving(current => { const next = { ...current }; links.items.forEach(row => { if (checked) next[row.id] = row; else delete next[row.id] }); return next }) }} />{t('ux06.selectPage', { count: links.items.length })}</label>}
          {links.items.map(row => <article className="binding-card" key={row.id}><label><input type="checkbox" disabled={removals.length >= 500 && !removing[row.id]} checked={!!removing[row.id]} onChange={event => toggleBinding(row, event.target.checked)} /><span><b>{row.machine.inventory_number}</b> · {row.machine.name}<small>{name(row.catalog)} · {row.catalog.code} · {row.published_revision?.revision_code || t('ux06.pending')}</small><small>{t(row.status === 'ACTIVE' ? 'ux06.activeBinding' : 'ux06.pending')}</small></span></label>
            <button className="danger" onClick={() => { setRemovalPreview([row]); setStage('remove') }}>{t('ux06.remove')}</button></article>)}
          {!!removals.length && <div className="binding-selection">{removals.map(row => <button className="secondary" key={row.id} onClick={() => toggleBinding(row, false)}>{row.machine.inventory_number} / {row.catalog.code} ×</button>)}</div>}
          <button className="danger" disabled={!removals.length} onClick={() => { setRemovalPreview(removals); setStage('remove') }}>{t('ux06.removeSelected')}</button>
        </>}
        {loading ? <p role="status">{t('wizard.loading')}</p> : !page.items.length && <p>{t('builder.empty')}</p>}
        <div className="binding-pagination"><button className="secondary" disabled={loading || offset === 0} onClick={() => setOffset(Math.max(0, offset - 50))}>{t('ux06.previous')}</button>
          <span>{t('ux06.results', { start: page.total ? offset + 1 : 0, end: Math.min(offset + page.items.length, page.total), total: page.total })}</span>
          <button className="secondary" disabled={loading || offset + 50 >= page.total} onClick={() => setOffset(offset + 50)}>{t('ux06.next')}</button></div>
      </>}
    </div>
  </CatalogDialog>
}
