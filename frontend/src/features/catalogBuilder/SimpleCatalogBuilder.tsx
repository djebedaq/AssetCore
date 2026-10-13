import { useCallback, useEffect, useState, type FormEvent } from 'react'
import { api, ApiError } from '../../api'
import Modal from './CatalogDialog'
import { useI18n } from '../../i18n'
import { hasPermission } from '../../permissions'
import './catalogBuilder.css'
import CatalogMaintenance from './CatalogMaintenance'
import GuidedWorkspace from './GuidedWorkspace'
import WizardReview from './WizardReview'
import WizardMachines from './WizardMachines'
import useDraftGuard from './useDraftGuard'
import DraftDeleteButton from './DraftDeleteButton'
import { builderBase, problemKeys, type Catalog, type Category, type Group, type Issue, type Revision, type Step, type Workflow } from './wizardTypes'

const newCatalog = { name: '', asset_category_id: '', manufacturer: '', model_reference: '', code: '', name_en: '', name_ru: '', description: '' }

export default function SimpleCatalogBuilder({ onDirtyChange, onLink }: { onDirtyChange: (dirty: boolean) => void; onLink?: () => void }) {
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
  const [maintenance, setMaintenance] = useState(false)
  const [creating, setCreating] = useState(false)
  const [editingMetadata, setEditingMetadata] = useState(false)
  const [metadata, setMetadata] = useState({ name: '', manufacturer: '', model_reference: '' })
  const [form, setForm] = useState(newCatalog)
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
      const next = revision?.status === 'DRAFT' ? 'documents' : 'review'
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
      const catalog = form.code.trim() ? await api<Catalog>(`${builderBase}/catalogs`, { method: 'POST', body: JSON.stringify({
        code: form.code.trim(), name_bg: form.name.trim(), name_en: form.name_en.trim() || form.name.trim(), name_ru: form.name_ru.trim() || form.name.trim(),
        description: form.description || null, asset_category_id: Number(form.asset_category_id), manufacturer: form.manufacturer || null, model_reference: form.model_reference || null,
      }) }) : await api<Catalog>(`${builderBase}/simple/catalogs`, { method: 'POST', body: JSON.stringify({
        name: form.name, asset_category_id: Number(form.asset_category_id), manufacturer: form.manufacturer || null, model_reference: form.model_reference || null,
      }) })
      if (!form.code.trim() && (form.name_en.trim() || form.name_ru.trim() || form.description)) {
        await api(`${builderBase}/catalogs/${catalog.id}`, { method: 'PATCH', body: JSON.stringify({
          ...(form.name_en.trim() ? { name_en: form.name_en.trim() } : {}),
          ...(form.name_ru.trim() ? { name_ru: form.name_ru.trim() } : {}), description: form.description || null,
        }) })
      }
      if (form.code.trim()) await api(`${builderBase}/catalogs/${catalog.id}/edit`, { method: 'POST' })
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
    <section hidden={!!selected} className={`panel catalog-picker ${selected ? 'catalog-picker-open' : ''}`}><div className="panel-title"><h3>{t('builder.catalogs')}</h3>
      <button className="primary" disabled={!!selected} onClick={() => { setCreating(true); setForm(newCatalog) }}>{t('builder.create')}</button></div>
      {!selected && onLink && <details><summary>{t('ref.additional')}</summary><button className="secondary" onClick={onLink}>{t('ref.link')}</button></details>}
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
      <button className="secondary" disabled={busy || dirty} onClick={() => setMaintenance(true)}>{t('catalogUx.manage')}</button>
      <button className="secondary" disabled={busy} onClick={close}>{t('common.close')}</button></div>
      <p className="catalog-context">{label(selected.asset_category)} · {selected.manufacturer} {selected.model_reference} · {t('catalogUx.revision')} {revision?.revision_code} · {revision && t(`builder.status.${revision.status}`)}</p>
      <nav aria-label={t('wizard.title')} className="catalog-navigation">{(['documents', 'parts', 'review'] as const).map((value, index) => <button key={value}
        className="secondary" aria-current={(value === 'documents' ? ['references', 'documents', 'catalog'].includes(step) : value === 'parts' ? ['extract', 'parts', 'hotspots'].includes(step) : step === 'review') ? 'step' : undefined}
        disabled={!revision || !workflow || busy || !editable && value !== 'review'} onClick={() => navigate(value)}>
        <span>{index + 1}</span> {t(value === 'documents' ? 'ux04.catalogPdf' : value === 'parts' ? 'ux04.partsMarkers' : 'ux04.publish')}
      </button>)}</nav>
      {dirty && <p className="muted" role="status">{t('wizard.unsavedNotice')}</p>}
      {!revision && <button className="primary" disabled={busy} onClick={() => void edit()}>{t('wizard.edit')}</button>}
      {!workflow && <p>{t('wizard.loading')}</p>}
      {editable && step === 'documents' && <button className="secondary" disabled={busy} onClick={() => {
        setMetadata({ name: label(selected), manufacturer: selected.manufacturer || '', model_reference: selected.model_reference || '' }); setEditingMetadata(true); navigate('catalog')
      }}>{t('wizard.editMetadata')}</button>}
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
        onNavigate={navigate} target={target} revisionId={revision.id} groups={groups} task={step} changed={refresh} onDirtyChange={documentsDirty} /></div>}
      <div hidden={step !== 'review'}><WizardReview groups={groups} catalogName={label(selected)} revisionCode={revision?.revision_code} workflow={workflow} editable={!!editable} busy={busy || editingMetadata || Object.values(dirtyChildren).some(Boolean)} onFix={fixIssue} onPublish={() => void publish()} /></div>
      {revision?.status === 'PUBLISHED' && <><p role="status">{t('wizard.published')}</p><button className="primary" disabled={busy} onClick={() => void edit()}>{t('wizard.edit')}</button></>}
      <details><summary>{t('wizard.machines')}</summary><WizardMachines catalogId={selected.id} onChanged={load} /></details>
      {editable && revision && <DraftDeleteButton kind="revision" identity={revision.id} label={t('ux04.deleteRevision')} disabled={busy || dirty} onDeleted={async () => {
        const rows = await api<Revision[]>(`${builderBase}/catalogs/${selected.id}/revisions`)
        setRevisions(rows); setRevisionId(rows[0]?.id || null); setGroups([]); setWorkflow(null); await load()
      }} />}
      {!selected.published_revision && !revisions.some(row => row.status === 'RETIRED') && <DraftDeleteButton kind="catalog" identity={selected.id} label={t('ux04.deleteCatalog')} disabled={busy || dirty} onDeleted={async () => { close(); await load() }} />}
      <details><summary>{t('wizard.history')}</summary>{revisions.map((row, index) => <p key={row.id}>
        <button className="secondary" disabled={busy || row.id === revisionId} onClick={() => {
          if (dirty && !window.confirm(t('wizard.unsaved'))) return
          setRevisionId(row.id); setDirtyChildren({})
        }}>{t('wizard.version', { number: revisions.length - index })}</button> · {t(`builder.status.${row.status}`)} · {date(row.created_at)}
      </p>)}</details>
    </section>}
    {maintenance && selected && <Modal wide title={t('catalogUx.manage')} onClose={() => { if (!dirty || window.confirm(t('wizard.unsaved'))) setMaintenance(false) }}>
      <CatalogMaintenance catalogId={selected.id} onDirtyChange={documentsDirty} onChanged={async () => { await load(); if (revisionId) await refresh(); setRevisions(await api<Revision[]>(`${builderBase}/catalogs/${selected.id}/revisions`)) }} />
    </Modal>}
    {creating && <Modal title={t('builder.create')} onClose={() => { if (!dirty || window.confirm(t('wizard.unsaved'))) setCreating(false) }}>
      <form className="form-grid" onSubmit={event => void create(event)}>
        <label>{t('wizard.name')}<input required maxLength={255} value={form.name} onChange={event => setForm({ ...form, name: event.target.value })} /></label>
        <label>{t('builder.category')}<select required value={form.asset_category_id} onChange={event => setForm({ ...form, asset_category_id: event.target.value })}>
          <option value="">{t('builder.category')}</option>{categories.map(category => <option key={category.id} value={category.id}>{label(category)}</option>)}</select></label>
        <label>{t('builder.manufacturer')}<input maxLength={255} value={form.manufacturer} onChange={event => setForm({ ...form, manufacturer: event.target.value })} /></label>
        <label>{t('builder.modelReference')}<input maxLength={255} value={form.model_reference} onChange={event => setForm({ ...form, model_reference: event.target.value })} /></label>
        <details className="wide"><summary>{t('catalogUx.catalogFields')}</summary>
          <label>{t('builder.code')}<input pattern="[A-Z][A-Z0-9_]+" value={form.code} onChange={event => setForm({ ...form, code: event.target.value.toUpperCase() })} /></label>
          {(['en', 'ru'] as const).map(language => <label key={language}>{t(`builder.name.${language}`)}<input value={form[`name_${language}`]} onChange={event => setForm({ ...form, [`name_${language}`]: event.target.value })} /></label>)}
          <label>{t('builder.description')}<textarea value={form.description} onChange={event => setForm({ ...form, description: event.target.value })} /></label>
        </details>
        <button className="primary" disabled={busy || !form.name.trim()}>{t('wizard.continue')}</button>
      </form>
    </Modal>}
  </div>
}
