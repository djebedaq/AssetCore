import { useCallback, useEffect, useState, type FormEvent } from 'react'
import { api, ApiError } from '../../api'
import { Modal } from '../../industrialUi'
import { useI18n } from '../../i18n'
import { hasPermission } from '../../permissions'
import GuidedWorkspace from './GuidedWorkspace'
import WizardReview from './WizardReview'
import WizardMachines from './WizardMachines'
import useDraftGuard from './useDraftGuard'
import { builderBase, problemKeys, type Catalog, type Category, type Group, type Issue, type Revision, type Step, type Workflow } from './wizardTypes'

export default function SimpleCatalogBuilder({ onDirtyChange }: { onDirtyChange: (dirty: boolean) => void }) {
  const { locale, t, date } = useI18n()
  const [catalogs, setCatalogs] = useState<Catalog[]>([])
  const [categories, setCategories] = useState<Category[]>([])
  const [selectedId, setSelectedId] = useState<number | null>(null)
  const [revisions, setRevisions] = useState<Revision[]>([])
  const [revisionId, setRevisionId] = useState<number | null>(null)
  const [groups, setGroups] = useState<Group[]>([])
  const [workflow, setWorkflow] = useState<Workflow | null>(null)
  const [target, setTarget] = useState<Issue | undefined>()
  const [step, setStep] = useState<Step>('catalog')
  const [creating, setCreating] = useState(false)
  const [editingMetadata, setEditingMetadata] = useState(false)
  const [metadata, setMetadata] = useState({ name: '', manufacturer: '', model_reference: '' })
  const [form, setForm] = useState({ name: '', asset_category_id: '', manufacturer: '', model_reference: '' })
  const [dirtyChildren, setDirtyChildren] = useState<Record<string, boolean>>({})
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const selected = catalogs.find(catalog => catalog.id === selectedId)
  const revision = revisions.find(item => item.id === revisionId)
  const editable = revision?.status === 'DRAFT'
  const dirty = busy || editingMetadata || creating && !!form.name || Object.values(dirtyChildren).some(Boolean)
  useDraftGuard(dirty, onDirtyChange)
  const documentsDirty = useCallback((value: boolean) => setDirtyChildren(current => ({ ...current, documents: value })), [])
  const label = (value: { name_bg: string; name_en: string; name_ru: string }) => value[`name_${locale}`] || value.name_bg
  const report = (caught: unknown) => setError(t(caught instanceof ApiError && caught.code ? problemKeys[caught.code] || 'builder.error.generic' : 'builder.error.generic'))
  async function load() {
    const [rows, options] = await Promise.all([api<Catalog[]>(`${builderBase}/catalogs`), api<Category[]>('/categories')])
    setCatalogs(rows); setCategories(options.filter(category => category.is_active && category.capabilities.includes('HAS_PARTS_CATALOG')))
  }
  useEffect(() => { if (hasPermission('parts.manage')) void load().catch(report) }, [])
  useEffect(() => {
    if (!selectedId) return
    let active = true
    setRevisions([]); setRevisionId(null); setWorkflow(null); setGroups([])
    setEditingMetadata(false)
    void api<Revision[]>(`${builderBase}/catalogs/${selectedId}/revisions`).then(rows => {
      if (!active) return
      setRevisions(rows); setRevisionId((rows.find(row => row.status === 'DRAFT') || rows.find(row => row.status === 'PUBLISHED') || rows[0])?.id || null)
    }).catch(report)
    return () => { active = false }
  }, [selectedId])
  useEffect(() => {
    if (!revisionId) return
    let active = true
    setWorkflow(null); setGroups([]); setEditingMetadata(false)
    void Promise.all([api<Group[]>(`${builderBase}/revisions/${revisionId}/assemblies`),
      api<Workflow>(`${builderBase}/revisions/${revisionId}/workflow`)]).then(([rows, summary]) => {
      if (!active) return
      setGroups(rows); setWorkflow(summary)
      const next = revision?.status === 'DRAFT' ? 'references' : 'review'
      setStep(next);
    }).catch(report)
    return () => { active = false }
  }, [revisionId])
  async function refresh() {
    if (!revisionId) return
    const [rows, summary] = await Promise.all([api<Group[]>(`${builderBase}/revisions/${revisionId}/assemblies`),
      api<Workflow>(`${builderBase}/revisions/${revisionId}/workflow`)])
    setGroups(rows); setWorkflow(summary);
  }
  function navigate(next: Step) {
    if (Object.values(dirtyChildren).some(Boolean) && !window.confirm(t('wizard.unsaved'))) return
    setStep(next);
    if (next === 'review') void refresh().catch(report)
  }
  function close() {
    if (dirty && !window.confirm(t('wizard.unsaved'))) return
    setSelectedId(null); setRevisionId(null); setDirtyChildren({}); setError(''); setEditingMetadata(false)
  }
  async function create(event: FormEvent) {
    event.preventDefault()
    if (busy) return
    setBusy(true); setError('')
    try {
      const catalog = await api<Catalog>(`${builderBase}/simple/catalogs`, { method: 'POST', body: JSON.stringify({
        ...form, asset_category_id: Number(form.asset_category_id), manufacturer: form.manufacturer || null, model_reference: form.model_reference || null,
      }) })
      await load(); setCreating(false); setSelectedId(catalog.id)
    } catch (caught) { report(caught) } finally { setBusy(false) }
  }
  async function edit() {
    if (!selected || busy) return
    setBusy(true); setError('')
    try {
      const draft = await api<Revision>(`${builderBase}/catalogs/${selected.id}/edit`, { method: 'POST' })
      setRevisions(await api<Revision[]>(`${builderBase}/catalogs/${selected.id}/revisions`))
      setRevisionId(draft.id); await load()
    } catch (caught) { report(caught) } finally { setBusy(false) }
  }
  async function saveMetadata(event: FormEvent) {
    event.preventDefault()
    if (!selected || !editable || busy) return
    setBusy(true); setError('')
    try {
      const names: Record<string, string> = { [`name_${locale}`]: metadata.name.trim() }
      for (const language of ['bg', 'en', 'ru'] as const) {
        if (!selected[`name_${language}`] || selected[`name_${language}`] === label(selected)) names[`name_${language}`] = metadata.name.trim()
      }
      await api(`${builderBase}/catalogs/${selected.id}`, { method: 'PATCH', body: JSON.stringify({
        ...names, manufacturer: metadata.manufacturer || null, model_reference: metadata.model_reference || null,
      }) })
      await load(); await refresh(); setEditingMetadata(false)
    } catch (caught) { report(caught) } finally { setBusy(false) }
  }
  async function publish() {
    if (!revision || !workflow?.ready || busy || editingMetadata || Object.values(dirtyChildren).some(Boolean) ||
        !window.confirm(t(workflow.current_published_revision_id ? 'wizard.publishUpdate' : 'wizard.publish'))) return
    setBusy(true); setError('')
    try {
      await api(`${builderBase}/revisions/${revision.id}/publish`, { method: 'POST', body: JSON.stringify({
        expected_publication_digest: workflow.publication_digest,
        expected_current_published_revision_id: workflow.current_published_revision_id, confirmed: true,
      }) })
      setRevisions(await api<Revision[]>(`${builderBase}/catalogs/${selectedId}/revisions`)); await load(); await refresh()
    } catch (caught) { report(caught); await refresh().catch(report) } finally { setBusy(false) }
  }
  function fixIssue(issue: Issue) {
    setTarget(issue)
    navigate(issue.step === 'kits' ? 'hotspots' : issue.step || 'review')
  }
  if (!hasPermission('parts.manage')) return null
  return <div className="builder-page catalog-workbench">
    {error && <p className="error" role="alert">{error}</p>}
    <section className={`panel catalog-picker ${selected ? 'catalog-picker-open' : ''}`}><div className="panel-title"><h3>{t('builder.catalogs')}</h3>
      <button className="primary" disabled={!!selected} onClick={() => { setCreating(true); setForm({ name: '', asset_category_id: '', manufacturer: '', model_reference: '' }) }}>{t('builder.create')}</button></div>
      {!catalogs.length && <p>{t('builder.empty')}</p>}
      <div className="builder-list">{catalogs.map(catalog => <article className="builder-list-item" key={catalog.id}>
        <div><strong>{label(catalog)}</strong><small>{label(catalog.asset_category)} · {catalog.manufacturer} {catalog.model_reference}</small></div>
        <span className="badge">{t(catalog.published_revision ? 'wizard.current' : 'builder.status.DRAFT')}</span>
        <button className="secondary" disabled={!catalog.is_active || busy || catalog.id === selectedId} onClick={() => {
          if (dirty && !window.confirm(t('wizard.unsaved'))) return
          setSelectedId(catalog.id); setDirtyChildren({}); setError('')
        }}>{t(catalog.draft_revision_count ? 'wizard.resume' : 'builder.open')}</button>
      </article>)}</div>
    </section>
    {selected && <section className="panel"><div className="panel-title"><h3>{label(selected)}</h3>
      <button className="secondary" disabled={busy} onClick={close}>{t('common.close')}</button></div>
      <nav aria-label={t('wizard.title')} className="catalog-navigation">{(['references', 'catalog', 'review'] as const).map(value => <button key={value}
        className="secondary" aria-current={(value === 'references' ? !['catalog', 'review'].includes(step) : step === value) ? 'page' : undefined}
        disabled={!revision || busy || !editable && value === 'references'} onClick={() => navigate(value)}>
        {t(value === 'references' ? 'workspace.work' : `wizard.${value}`)}
      </button>)}</nav>
      {dirty && <p className="muted" role="status">{t('wizard.unsavedNotice')}</p>}
      {!workflow && <p>{t('wizard.loading')}</p>}
      <div hidden={step !== 'catalog'}><p><b>{t('builder.category')}:</b> {label(selected.asset_category)}</p>
        <p className="muted">{t('wizard.categoryLocked')}</p>
        <p><b>{t('builder.manufacturer')}:</b> {selected.manufacturer || t('common.noValue')}</p>
        <p><b>{t('builder.modelReference')}:</b> {selected.model_reference || t('common.noValue')}</p>
        {editable && !editingMetadata && <button className="secondary" disabled={busy} onClick={() => {
          setMetadata({ name: label(selected), manufacturer: selected.manufacturer || '', model_reference: selected.model_reference || '' }); setEditingMetadata(true)
        }}>{t('wizard.editMetadata')}</button>}
        {editable && editingMetadata && <form className="form-grid" onSubmit={event => void saveMetadata(event)}>
          <label>{t('wizard.name')}<input required maxLength={255} disabled={busy} value={metadata.name} onChange={event => setMetadata({ ...metadata, name: event.target.value })} /></label>
          <label>{t('builder.manufacturer')}<input maxLength={255} disabled={busy} value={metadata.manufacturer} onChange={event => setMetadata({ ...metadata, manufacturer: event.target.value })} /></label>
          <label>{t('builder.modelReference')}<input maxLength={255} disabled={busy} value={metadata.model_reference} onChange={event => setMetadata({ ...metadata, model_reference: event.target.value })} /></label>
          <button className="primary" disabled={busy || !metadata.name.trim()}>{t('common.save')}</button>
          <button type="button" className="secondary" disabled={busy} onClick={() => setEditingMetadata(false)}>{t('common.cancel')}</button>
        </form>}
        {!revision && <button className="primary" disabled={busy} onClick={() => void edit()}>{t('wizard.edit')}</button>}
      </div>
      {editable && revision && <div hidden={['catalog', 'review'].includes(step)}><GuidedWorkspace
        target={target} revisionId={revision.id} groups={groups} task={step} changed={refresh} onDirtyChange={documentsDirty} /></div>}
      <div hidden={step !== 'review'}><WizardReview workflow={workflow} editable={!!editable} busy={busy || editingMetadata || Object.values(dirtyChildren).some(Boolean)} onFix={fixIssue} onPublish={() => void publish()} /></div>
      {revision?.status === 'PUBLISHED' && <><p role="status">{t('wizard.published')}</p><button className="primary" disabled={busy} onClick={() => void edit()}>{t('wizard.edit')}</button>
        <WizardMachines catalogId={selected.id} onChanged={load} /></>}
      <details><summary>{t('wizard.history')}</summary>{revisions.map((row, index) => <p key={row.id}>
        <button className="secondary" disabled={busy || row.id === revisionId} onClick={() => {
          if (dirty && !window.confirm(t('wizard.unsaved'))) return
          setRevisionId(row.id); setDirtyChildren({})
        }}>{t('wizard.version', { number: revisions.length - index })}</button> · {t(`builder.status.${row.status}`)} · {date(row.created_at)}
      </p>)}</details>
    </section>}
    {creating && <Modal title={t('builder.create')} onClose={() => { if (!dirty || window.confirm(t('wizard.unsaved'))) setCreating(false) }}>
      <form className="form-grid" onSubmit={event => void create(event)}>
        <label>{t('wizard.name')}<input required maxLength={255} value={form.name} onChange={event => setForm({ ...form, name: event.target.value })} /></label>
        <label>{t('builder.category')}<select required value={form.asset_category_id} onChange={event => setForm({ ...form, asset_category_id: event.target.value })}>
          <option value="">{t('builder.category')}</option>{categories.map(category => <option key={category.id} value={category.id}>{label(category)}</option>)}</select></label>
        <label>{t('builder.manufacturer')}<input maxLength={255} value={form.manufacturer} onChange={event => setForm({ ...form, manufacturer: event.target.value })} /></label>
        <label>{t('builder.modelReference')}<input maxLength={255} value={form.model_reference} onChange={event => setForm({ ...form, model_reference: event.target.value })} /></label>
        <button className="primary" disabled={busy || !form.name.trim()}>{t('wizard.continue')}</button>
      </form>
    </Modal>}
  </div>
}
