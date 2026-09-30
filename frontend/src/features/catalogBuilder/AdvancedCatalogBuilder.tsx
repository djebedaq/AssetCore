import { useEffect, useState, type FormEvent } from 'react'
import { api, ApiError } from '../../api'
import { Modal } from '../../industrialUi'
import { useI18n, type TranslationKey } from '../../i18n'
import { hasPermission } from '../../permissions'
import { OwnerDeleteButton } from '../administration/OwnerDeleteButton'
import RevisionVisualSources from './RevisionVisualSources'
import useDraftGuard from './useDraftGuard'

type Category = { id: number; code: string; name_bg: string; name_en: string; name_ru: string; is_active: boolean; capabilities: string[] }
type RevisionSummary = { id: number; revision_code: string }
type Catalog = {
  id: number; code: string; asset_category_id: number; asset_category: Category
  name_bg: string; name_en: string; name_ru: string; description: string | null
  manufacturer: string | null; model_reference: string | null; is_active: boolean
  bound_asset_count: number; draft_revision_count: number
  latest_revision: RevisionSummary | null; published_revision: RevisionSummary | null
}
type Asset = { id: number; inventory_number: string; name: string; brand: string; model: string | null }
type Revision = { id: number; revision_code: string; status: 'DRAFT' | 'PUBLISHED' | 'RETIRED'; change_note: string | null; created_at: string; published_at: string | null }
type Readiness = { ready: boolean; publication_digest: string; current_published_revision_id: number | null;
  errors: Array<{ code: string }>; warnings: Array<{ code: string; missing_positions?: number }>;
  summary: { assembly_count: number; artifact_count: number; part_count: number; mapped_part_count: number;
    exploded_page_count: number; spare_list_page_count: number; hotspot_count: number;
    verified_hotspot_count: number; repair_kit_count: number; repair_kit_component_count: number } }
type Form = { code: string; asset_category_id: string; name_bg: string; name_en: string; name_ru: string; description: string; manufacturer: string; model_reference: string }

const emptyForm: Form = { code: '', asset_category_id: '', name_bg: '', name_en: '', name_ru: '', description: '', manufacturer: '', model_reference: '' }

const errorKeys: Record<string, TranslationKey> = {
  catalog_definition_not_found: 'builder.error.notFound', catalog_category_not_found: 'builder.error.category',
  catalog_revision_not_found: 'builder.error.notFound', catalog_asset_not_found: 'builder.error.notFound',
  catalog_asset_binding_not_found: 'builder.error.notFound', catalog_invalid_update: 'builder.error.invalid',
  catalog_category_not_supported: 'builder.error.capability', catalog_category_inactive: 'builder.error.category',
  catalog_code_duplicate: 'builder.error.duplicate', catalog_code_immutable: 'builder.error.immutable',
  catalog_category_in_use: 'builder.error.categoryInUse', catalog_inactive: 'builder.error.inactive',
  catalog_revision_duplicate: 'builder.error.revisionDuplicate', catalog_revision_immutable: 'builder.error.revisionImmutable',
  catalog_revision_code_immutable: 'builder.error.revisionImmutable', catalog_revision_status_managed: 'builder.error.status',
  catalog_asset_category_mismatch: 'builder.error.assetCategory', catalog_asset_already_bound: 'builder.error.assetBound',
  catalog_asset_inactive: 'builder.error.assetInactive', catalog_asset_binding_protected: 'builder.error.assetProtected',
  category_capability_in_use: 'builder.error.capabilityInUse',
  catalog_publication_stale: 'builder.publication.stale',
  catalog_publication_not_ready: 'builder.publication.notReady',
  catalog_publication_conflict: 'builder.publication.conflict',
  catalog_clone_invalid: 'builder.publication.cloneInvalid',
}

const readinessKeys: Record<string, TranslationKey> = {
  catalog_publication_no_assemblies: 'builder.publication.noAssemblies',
  catalog_publication_source_invalid: 'builder.publication.sourceInvalid',
  catalog_publication_visual_page_invalid: 'builder.publication.pageInvalid',
  catalog_publication_part_mapping_invalid: 'builder.publication.mappingInvalid',
  catalog_publication_part_incomplete: 'builder.publication.partIncomplete',
  catalog_publication_hotspot_invalid: 'builder.publication.hotspotInvalid',
  catalog_publication_hotspot_unverified: 'builder.publication.hotspotUnverified',
  catalog_publication_hotspot_coverage: 'builder.publication.hotspotCoverage',
  catalog_publication_kit_incomplete: 'builder.publication.kitIncomplete',
  catalog_inactive: 'builder.error.inactive',
  catalog_category_not_supported: 'builder.error.capability',
  catalog_revision_not_draft: 'builder.error.revisionImmutable',
}

export default function AdvancedCatalogBuilder({ onDirtyChange }: { onDirtyChange?: (dirty: boolean) => void }) {
  const { locale, t, date } = useI18n()
  const [catalogs, setCatalogs] = useState<Catalog[]>([])
  const [categories, setCategories] = useState<Category[]>([])
  const [selectedId, setSelectedId] = useState<number | null>(null)
  const [assets, setAssets] = useState<Asset[]>([])
  const [eligible, setEligible] = useState<Asset[]>([])
  const [revisions, setRevisions] = useState<Revision[]>([])
  const [openRevisionId, setOpenRevisionId] = useState<number | null>(null)
  const [revisionTab, setRevisionTab] = useState<'overview' | 'sources'>('overview')
  const [search, setSearch] = useState('')
  const [tab, setTab] = useState<'overview' | 'assets' | 'revisions'>('overview')
  const [editing, setEditing] = useState<Catalog | 'new' | null>(null)
  const [form, setForm] = useState<Form>(emptyForm)
  const [revisionEdit, setRevisionEdit] = useState<Revision | 'new' | null>(null)
  const [revisionCode, setRevisionCode] = useState('')
  const [note, setNote] = useState('')
  const [cloneSource, setCloneSource] = useState<Revision | null>(null)
  const [readiness, setReadiness] = useState<Readiness | null>(null)
  const [readinessLoading, setReadinessLoading] = useState(false)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [workspaceDirty, setWorkspaceDirty] = useState(false)
  useDraftGuard(!!editing || !!revisionEdit || !!cloneSource || busy || workspaceDirty, onDirtyChange)
  const selected = catalogs.find(item => item.id === selectedId)
  const openRevision = revisions.find(item => item.id === openRevisionId)

  function message(caught: unknown): string {
    return t(caught instanceof ApiError && caught.code && errorKeys[caught.code] ? errorKeys[caught.code] : 'builder.error.generic')
  }

  async function load(): Promise<void> {
    try {
      const [items, categoryItems] = await Promise.all([api<Catalog[]>('/admin/catalog-builder/catalogs'), api<Category[]>('/categories')])
      setCatalogs(items)
      setCategories(categoryItems.filter(item => (item.capabilities || []).includes('HAS_PARTS_CATALOG')))
      setError('')
    } catch (caught) { setError(message(caught)) }
  }

  async function loadWorkspace(id: number): Promise<void> {
    try {
      const [bound, revisionItems] = await Promise.all([
        api<Asset[]>(`/admin/catalog-builder/catalogs/${id}/assets`),
        api<Revision[]>(`/admin/catalog-builder/catalogs/${id}/revisions`),
      ])
      setAssets(bound)
      setRevisions(revisionItems)
      setError('')
    } catch (caught) { setError(message(caught)) }
  }

  useEffect(() => { if (hasPermission('parts.manage')) void load() }, [])
  useEffect(() => { if (selectedId !== null) void loadWorkspace(selectedId) }, [selectedId])
  useEffect(() => {
    if (openRevisionId === null || revisionTab !== 'overview') { setReadiness(null); return }
    let active = true
    setReadinessLoading(true)
    void api<Readiness>(`/admin/catalog-builder/revisions/${openRevisionId}/publication-readiness`)
      .then(result => { if (active) setReadiness(result) })
      .catch(caught => { if (active) setError(message(caught)) })
      .finally(() => { if (active) setReadinessLoading(false) })
    return () => { active = false }
  }, [openRevisionId, revisionTab])
  useEffect(() => {
    if (selectedId === null || tab !== 'assets') return
    let active = true
    void api<Asset[]>(`/admin/catalog-builder/catalogs/${selectedId}/eligible-assets?search=${encodeURIComponent(search)}`)
      .then(items => { if (active) setEligible(items) })
      .catch(caught => { if (active) setError(message(caught)) })
    return () => { active = false }
  }, [selectedId, tab, search])

  if (!hasPermission('parts.manage')) return null

  function openForm(item: Catalog | 'new') {
    setEditing(item)
    setForm(item === 'new' ? emptyForm : {
      code: item.code, asset_category_id: String(item.asset_category_id), name_bg: item.name_bg,
      name_en: item.name_en, name_ru: item.name_ru, description: item.description || '',
      manufacturer: item.manufacturer || '', model_reference: item.model_reference || '',
    })
  }

  async function saveCatalog(event: FormEvent) {
    event.preventDefault()
    if (!editing || busy) return
    setBusy(true)
    const payload = { ...form, asset_category_id: Number(form.asset_category_id),
      description: form.description || null, manufacturer: form.manufacturer || null,
      model_reference: form.model_reference || null }
    try {
      if (editing === 'new') {
        const created = await api<Catalog>('/admin/catalog-builder/catalogs', { method: 'POST', body: JSON.stringify(payload) })
        setSelectedId(created.id)
      } else {
        const { code: _code, ...changes } = payload
        void _code
        await api(`/admin/catalog-builder/catalogs/${editing.id}`, { method: 'PATCH', body: JSON.stringify(changes) })
      }
      setEditing(null)
      await load()
    } catch (caught) { setError(message(caught)) }
    finally { setBusy(false) }
  }

  async function toggle(item: Catalog) {
    if (!window.confirm(t(item.is_active ? 'builder.deactivateConfirm' : 'builder.activateConfirm'))) return
    try {
      await api(`/admin/catalog-builder/catalogs/${item.id}`, { method: 'PATCH', body: JSON.stringify({ is_active: !item.is_active }) })
      await load()
    } catch (caught) { setError(message(caught)) }
  }

  async function bind(machine: Asset) {
    if (!selected) return
    try {
      await api(`/admin/catalog-builder/catalogs/${selected.id}/assets/${machine.id}`, { method: 'POST' })
      await Promise.all([load(), loadWorkspace(selected.id)])
      setEligible(items => items.filter(item => item.id !== machine.id))
    } catch (caught) { setError(message(caught)) }
  }

  async function unbind(machine: Asset) {
    if (!selected || !window.confirm(t('builder.removeBindingConfirm'))) return
    try {
      await api(`/admin/catalog-builder/catalogs/${selected.id}/assets/${machine.id}`, { method: 'DELETE' })
      await Promise.all([load(), loadWorkspace(selected.id)])
      setSearch(value => value + ' ')
    } catch (caught) { setError(message(caught)) }
  }

  async function saveRevision(event: FormEvent) {
    event.preventDefault()
    if (!selected || !revisionEdit || busy) return
    setBusy(true)
    try {
      if (revisionEdit === 'new') {
        await api(`/admin/catalog-builder/catalogs/${selected.id}/revisions`, {
          method: 'POST', body: JSON.stringify({ revision_code: revisionCode, change_note: note || null }),
        })
      } else {
        await api(`/admin/catalog-builder/revisions/${revisionEdit.id}`, {
          method: 'PATCH', body: JSON.stringify({ change_note: note || null }),
        })
      }
      setRevisionEdit(null)
      await Promise.all([load(), loadWorkspace(selected.id)])
    } catch (caught) { setError(message(caught)) }
    finally { setBusy(false) }
  }

  async function refreshReadiness() {
    if (!openRevisionId) return
    setReadinessLoading(true)
    try { setReadiness(await api<Readiness>(`/admin/catalog-builder/revisions/${openRevisionId}/publication-readiness`)) }
    catch (caught) { setError(message(caught)) }
    finally { setReadinessLoading(false) }
  }

  async function publishRevision() {
    if (!openRevision || !readiness?.ready || busy ||
        !window.confirm(t('builder.publication.confirm', { code: openRevision.revision_code }))) return
    setBusy(true)
    try {
      await api(`/admin/catalog-builder/revisions/${openRevision.id}/publish`, {
        method: 'POST', body: JSON.stringify({ expected_publication_digest: readiness.publication_digest,
          expected_current_published_revision_id: readiness.current_published_revision_id, confirmed: true }),
      })
      setReadiness(null)
      await Promise.all([load(), loadWorkspace(selected!.id)])
    } catch (caught) {
      await refreshReadiness()
      if (selected) await loadWorkspace(selected.id)
      setError(message(caught))
    } finally { setBusy(false) }
  }

  async function cloneRevision(event: FormEvent) {
    event.preventDefault()
    if (!cloneSource || !selected || busy) return
    setBusy(true)
    try {
      const created = await api<Revision>(`/admin/catalog-builder/revisions/${cloneSource.id}/clone`, {
        method: 'POST', body: JSON.stringify({ revision_code: revisionCode, change_note: note || null }),
      })
      setCloneSource(null)
      await Promise.all([load(), loadWorkspace(selected.id)])
      setOpenRevisionId(created.id)
      setRevisionTab('overview')
    } catch (caught) { setError(message(caught)) }
    finally { setBusy(false) }
  }

  const label = (item: { name_bg: string; name_en: string | null; name_ru: string | null }) => item[`name_${locale}`] || item.name_bg
  return <div className="builder-page">
    {error && <p className="error" role="alert">{error}</p>}
    <section className="panel">
      <div className="panel-title"><h3>{t('builder.catalogs')}</h3><button className="primary compact" onClick={() => openForm('new')}>{t('builder.create')}</button></div>
      <p className="muted">{t('builder.runtimeNotice')}</p>
      {!catalogs.length && <p>{t('builder.empty')}</p>}
      <div className="builder-list">{catalogs.map(item => <article key={item.id} className="builder-list-item">
        <div><strong>{label(item)}</strong><small>{item.code} · {label(item.asset_category)}</small></div>
        <span className="badge">{t(item.is_active ? 'builder.active' : 'builder.inactive')}</span>
        <span>{t('builder.boundCount', { count: item.bound_asset_count })}</span>
        <span>{t('builder.draftCount', { count: item.draft_revision_count })}</span>
        <span>{item.latest_revision ? `${t('builder.latest')}: ${item.latest_revision.revision_code}` : t('builder.noRevision')}</span>
        <div className="actions"><button className="secondary compact" onClick={() => { setSelectedId(item.id); setOpenRevisionId(null); setTab('overview') }}>{t('builder.open')}</button>
          <button className="secondary compact" onClick={() => openForm(item)}>{t('common.edit')}</button>
          <button className="secondary compact" onClick={() => void toggle(item)}>{t(item.is_active ? 'admin.deactivate' : 'admin.activate')}</button>
          <OwnerDeleteButton resource="catalog_definition" resourceId={item.id} identity={item.code} onDeleted={async () => { if (selectedId === item.id) setSelectedId(null); await load() }} />
        </div>
      </article>)}</div>
    </section>
    {selected && <section className="panel">
      <div className="panel-title"><h3>{label(selected)} · {selected.code}</h3><button className="secondary compact" onClick={() => setSelectedId(null)}>{t('common.close')}</button></div>
      <div className="actions builder-tabs">{(['overview', 'assets', 'revisions'] as const).map(value => <button key={value} className={tab === value ? 'primary compact' : 'secondary compact'} onClick={() => setTab(value)}>{t(`builder.${value}`)}</button>)}</div>
      {tab === 'overview' && <div className="builder-overview">
        <p><b>{t('builder.category')}:</b> {label(selected.asset_category)} ({selected.asset_category.code})</p>
        <p><b>{t('builder.manufacturer')}:</b> {selected.manufacturer || t('common.noValue')}</p>
        <p><b>{t('builder.modelReference')}:</b> {selected.model_reference || t('common.noValue')}</p>
        <p><b>{t('builder.description')}:</b> {selected.description || t('common.noValue')}</p>
        <p><b>{t('builder.publication.current')}:</b> {selected.published_revision?.revision_code || t('common.noValue')}</p>
        <p>{t('builder.nextSteps')}</p>
      </div>}
      {tab === 'assets' && <div className="builder-workspace">
        <h4>{t('builder.boundAssets')}</h4>
        {!assets.length && <p>{t('builder.noAssets')}</p>}
        {assets.map(asset => <div className="builder-row" key={asset.id}><span><b>{asset.inventory_number}</b> · {asset.name} · {asset.brand} {asset.model || ''}</span><button className="secondary compact" onClick={() => void unbind(asset)}>{t('builder.removeBinding')}</button></div>)}
        {selected.is_active && <><h4>{t('builder.addAsset')}</h4><input aria-label={t('builder.searchAssets')} placeholder={t('builder.searchAssets')} value={search} onChange={event => setSearch(event.target.value)} />
          {!eligible.length && <p>{t('builder.noEligible')}</p>}
          {eligible.map(asset => <div className="builder-row" key={asset.id}><span><b>{asset.inventory_number}</b> · {asset.name} · {asset.brand} {asset.model || ''}</span><button className="secondary compact" onClick={() => void bind(asset)}>{t('builder.addAsset')}</button></div>)}</>}
      </div>}
      {tab === 'revisions' && <div className="builder-workspace">
        {selected.is_active && <button className="primary compact" onClick={() => { setRevisionEdit('new'); setRevisionCode(''); setNote('') }}>{t('builder.createRevision')}</button>}
        {!revisions.length && <p>{t('builder.noRevision')}</p>}
        {revisions.map(revision => <div className="builder-row" key={revision.id}><span><b>{revision.revision_code}</b> · {t(`builder.status.${revision.status}`)} · {date(revision.created_at)}<small>{revision.change_note || t('common.noValue')}</small></span>
          <div className="actions"><button className="secondary compact" onClick={() => { setOpenRevisionId(revision.id); setRevisionTab('overview') }}>{t('builder.openRevision')}</button>
          {revision.status === 'DRAFT' && selected.is_active && <button className="secondary compact" onClick={() => { setRevisionEdit(revision); setRevisionCode(revision.revision_code); setNote(revision.change_note || '') }}>{t('common.edit')}</button>}
          {revision.status === 'PUBLISHED' && <button className="secondary compact" onClick={() => { setCloneSource(revision); setRevisionCode(''); setNote('') }}>{t('builder.publication.clone')}</button>}</div></div>)}
        {openRevision && <section className="panel"><div className="panel-title"><h4>{t('builder.revisionWorkspace')} · {openRevision.revision_code}</h4><button className="secondary compact" onClick={() => setOpenRevisionId(null)}>{t('common.close')}</button></div>
          <div className="actions builder-tabs"><button className={revisionTab === 'overview' ? 'primary compact' : 'secondary compact'} onClick={() => setRevisionTab('overview')}>{t('builder.overview')}</button>
            <button className={revisionTab === 'sources' ? 'primary compact' : 'secondary compact'} onClick={() => setRevisionTab('sources')}>{t('builder.assembliesSources')}</button></div>
          {revisionTab === 'overview' ? <div>
            <p>{openRevision.change_note || t('common.noValue')}</p>
            {openRevision.published_at && <p>{t('builder.publication.publishedAt')}: {date(openRevision.published_at)}</p>}
            {readinessLoading && <p>{t('builder.publication.loading')}</p>}
            {readiness && <div className="builder-publication-readiness">
              <p><b>{t(readiness.ready ? 'builder.publication.ready' : 'builder.publication.notReady')}</b> · SHA-256 {readiness.publication_digest.slice(0, 12)}</p>
              <p>{t('builder.publication.summary', { assemblies: readiness.summary.assembly_count,
                parts: readiness.summary.part_count, mapped: readiness.summary.mapped_part_count,
                schemes: readiness.summary.exploded_page_count, lists: readiness.summary.spare_list_page_count,
                hotspots: readiness.summary.verified_hotspot_count, kits: readiness.summary.repair_kit_count })}</p>
              {readiness.errors.map((item, index) => <p className="error" key={`error-${index}`}>{t(readinessKeys[item.code] || 'builder.error.generic')}</p>)}
              {readiness.warnings.map((item, index) => <p className="muted" key={`warning-${index}`}>{t(readinessKeys[item.code] || 'builder.error.generic', { count: item.missing_positions || 0 })}</p>)}
            </div>}
            <div className="actions"><button className="secondary compact" disabled={readinessLoading} onClick={() => void refreshReadiness()}>{t('builder.publication.refresh')}</button>
              {openRevision.status === 'DRAFT' && <button className="primary compact" disabled={!readiness?.ready || busy || readinessLoading} onClick={() => void publishRevision()}>{t('builder.publication.publish')}</button>}
            </div>
          </div> :
            <RevisionVisualSources revisionId={openRevision.id} editable={openRevision.status === 'DRAFT' && selected.is_active} onDirtyChange={setWorkspaceDirty} />}</section>}
      </div>}
    </section>}
    {editing && <Modal title={t(editing === 'new' ? 'builder.create' : 'builder.edit')} onClose={() => setEditing(null)} wide><form className="form-grid" onSubmit={event => void saveCatalog(event)}>
      <label>{t('builder.code')}<input required pattern="[A-Z][A-Z0-9_]+" readOnly={editing !== 'new'} value={form.code} onChange={event => setForm({ ...form, code: event.target.value.toUpperCase() })} /></label>
      <label>{t('builder.category')}<select required value={form.asset_category_id} onChange={event => setForm({ ...form, asset_category_id: event.target.value })}><option value="">{t('builder.chooseCategory')}</option>{categories.filter(item => editing !== 'new' ? item.is_active || item.id === editing.asset_category_id : item.is_active).map(item => <option key={item.id} value={item.id}>{label(item)} ({item.code})</option>)}</select></label>
      {(['bg', 'en', 'ru'] as const).map(language => <label key={language}>{t(`builder.name.${language}`)}<input required value={form[`name_${language}`]} onChange={event => setForm({ ...form, [`name_${language}`]: event.target.value })} /></label>)}
      <label>{t('builder.manufacturer')}<input value={form.manufacturer} onChange={event => setForm({ ...form, manufacturer: event.target.value })} /></label>
      <label>{t('builder.modelReference')}<input value={form.model_reference} onChange={event => setForm({ ...form, model_reference: event.target.value })} /></label>
      <label className="wide">{t('builder.description')}<textarea value={form.description} onChange={event => setForm({ ...form, description: event.target.value })} /></label>
      <div className="actions wide"><button type="button" className="secondary" onClick={() => setEditing(null)}>{t('common.cancel')}</button><button className="primary" disabled={busy}>{t('common.save')}</button></div>
    </form></Modal>}
    {revisionEdit && <Modal title={t(revisionEdit === 'new' ? 'builder.createRevision' : 'builder.editRevision')} onClose={() => setRevisionEdit(null)}><form className="form-grid" onSubmit={event => void saveRevision(event)}>
      <label>{t('builder.revisionCode')}<input required readOnly={revisionEdit !== 'new'} value={revisionCode} onChange={event => setRevisionCode(event.target.value)} /></label>
      <label className="wide">{t('builder.changeNote')}<textarea value={note} onChange={event => setNote(event.target.value)} /></label>
      <div className="actions wide"><button type="button" className="secondary" onClick={() => setRevisionEdit(null)}>{t('common.cancel')}</button><button className="primary" disabled={busy}>{t('common.save')}</button></div>
    </form></Modal>}
    {cloneSource && <Modal title={t('builder.publication.clone')} onClose={() => setCloneSource(null)}><form className="form-grid" onSubmit={event => void cloneRevision(event)}>
      <label>{t('builder.revisionCode')}<input required value={revisionCode} onChange={event => setRevisionCode(event.target.value)} /></label>
      <label className="wide">{t('builder.changeNote')}<textarea value={note} onChange={event => setNote(event.target.value)} /></label>
      <div className="actions wide"><button type="button" className="secondary" onClick={() => setCloneSource(null)}>{t('common.cancel')}</button><button className="primary" disabled={busy}>{t('builder.publication.clone')}</button></div>
    </form></Modal>}
  </div>
}
