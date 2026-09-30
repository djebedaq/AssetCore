import { useCallback, useEffect, useState, type FormEvent } from 'react'
import { api, ApiError } from '../../api'
import { Modal } from '../../industrialUi'
import { useI18n } from '../../i18n'
import { hasPermission } from '../../permissions'
import RevisionHotspotEditor from './RevisionHotspotEditor'
import RevisionRepairKits from './RevisionRepairKits'
import WizardDocuments from './WizardDocuments'
import WizardParts from './WizardParts'
import WizardReview from './WizardReview'
import WizardMachines from './WizardMachines'
import useDraftGuard from './useDraftGuard'
import { builderBase, problemKeys, steps, type Catalog, type Category, type Group, type Issue, type Revision, type Step, type Workflow } from './wizardTypes'

export default function SimpleCatalogBuilder({ onDirtyChange }: { onDirtyChange: (dirty: boolean) => void }) {
  const { locale, t, date } = useI18n()
  const [catalogs, setCatalogs] = useState<Catalog[]>([])
  const [categories, setCategories] = useState<Category[]>([])
  const [selectedId, setSelectedId] = useState<number | null>(null)
  const [revisions, setRevisions] = useState<Revision[]>([])
  const [revisionId, setRevisionId] = useState<number | null>(null)
  const [groups, setGroups] = useState<Group[]>([])
  const [groupId, setGroupId] = useState<number | null>(null)
  const [workflow, setWorkflow] = useState<Workflow | null>(null)
  const [step, setStep] = useState<Step>('catalog')
  const [visited, setVisited] = useState<Step[]>([])
  const [creating, setCreating] = useState(false)
  const [form, setForm] = useState({ name: '', asset_category_id: '', manufacturer: '', model_reference: '' })
  const [dirtyChildren, setDirtyChildren] = useState<Record<string, boolean>>({})
  const [fix, setFix] = useState<Issue | null>(null)
  const [kits, setKits] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const selected = catalogs.find(catalog => catalog.id === selectedId)
  const revision = revisions.find(item => item.id === revisionId)
  const editable = revision?.status === 'DRAFT'
  const dirty = busy || creating && !!form.name || Object.values(dirtyChildren).some(Boolean)
  useDraftGuard(dirty, onDirtyChange)
  const documentsDirty = useCallback((value: boolean) => setDirtyChildren(current => ({ ...current, documents: value })), [])
  const importDirty = useCallback((value: boolean) => setDirtyChildren(current => ({ ...current, import: value })), [])
  const partsDirty = useCallback((value: boolean) => setDirtyChildren(current => ({ ...current, parts: value })), [])
  const hotspotsDirty = useCallback((value: boolean) => setDirtyChildren(current => ({ ...current, hotspots: value })), [])
  const kitsDirty = useCallback((value: boolean) => setDirtyChildren(current => ({ ...current, kits: value })), [])
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
    void api<Revision[]>(`${builderBase}/catalogs/${selectedId}/revisions`).then(rows => {
      if (!active) return
      setRevisions(rows); setRevisionId((rows.find(row => row.status === 'DRAFT') || rows.find(row => row.status === 'PUBLISHED') || rows[0])?.id || null)
    }).catch(report)
    return () => { active = false }
  }, [selectedId])
  useEffect(() => {
    if (!revisionId) return
    let active = true
    setWorkflow(null); setGroups([]); setVisited([]); setFix(null); setKits(false)
    void Promise.all([api<Group[]>(`${builderBase}/revisions/${revisionId}/assemblies`),
      api<Workflow>(`${builderBase}/revisions/${revisionId}/workflow`)]).then(([rows, summary]) => {
      if (!active) return
      setGroups(rows); setGroupId(rows[0]?.id || null); setWorkflow(summary)
      const next = revision?.status === 'DRAFT' ? summary.resume_step : 'review'
      setStep(next); setVisited([next])
    }).catch(report)
    return () => { active = false }
  }, [revisionId])
  async function refresh() {
    if (!revisionId) return
    const [rows, summary] = await Promise.all([api<Group[]>(`${builderBase}/revisions/${revisionId}/assemblies`),
      api<Workflow>(`${builderBase}/revisions/${revisionId}/workflow`)])
    setGroups(rows); setWorkflow(summary); setGroupId(id => rows.some(row => row.id === id) ? id : rows[0]?.id || null)
  }
  function navigate(next: Step) {
    setStep(next); setVisited(values => values.includes(next) ? values : [...values, next])
    if (next === 'review') void refresh().catch(report)
  }
  function changeGroup(id: number) {
    if ((dirtyChildren.parts || dirtyChildren.hotspots || dirtyChildren.kits) && !window.confirm(t('wizard.unsaved'))) return false
    setGroupId(id)
    return true
  }
  function close() {
    if (dirty && !window.confirm(t('wizard.unsaved'))) return
    setSelectedId(null); setRevisionId(null); setVisited([]); setDirtyChildren({}); setError('')
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
  async function publish() {
    if (!revision || !workflow?.ready || busy || Object.values(dirtyChildren).some(Boolean) ||
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
    if (issue.assembly_id && !changeGroup(issue.assembly_id)) return
    setFix(issue)
    if (issue.step === 'kits') { setKits(true); navigate('hotspots') }
    else navigate(issue.step || 'documents')
  }
  if (!hasPermission('parts.manage')) return null
  return <div className="builder-page">
    {error && <p className="error" role="alert">{error}</p>}
    <section className="panel"><div className="panel-title"><h3>{t('builder.catalogs')}</h3>
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
      <nav aria-label={t('wizard.title')} className="wizard-progress">{steps.map((value, index) => <button key={value}
        aria-label={`${index + 1} ${t(`wizard.${value}`)}`} className={step === value ? 'primary' : 'secondary'} aria-current={step === value ? 'step' : undefined}
        disabled={!revision || busy || !editable && value !== 'catalog' && value !== 'review'} onClick={() => navigate(value)}>
        <span>{index + 1}</span>{t(`wizard.${value}`)}
      </button>)}</nav>
      {dirty && <p className="muted" role="status">{t('wizard.unsavedNotice')}</p>}
      {!workflow && <p>{t('wizard.loading')}</p>}
      {workflow && <p>{t('wizard.progress', workflow.progress)}</p>}
      <div hidden={step !== 'catalog'}><p><b>{t('builder.category')}:</b> {label(selected.asset_category)}</p>
        <p><b>{t('builder.manufacturer')}:</b> {selected.manufacturer || t('common.noValue')}</p>
        <p><b>{t('builder.modelReference')}:</b> {selected.model_reference || t('common.noValue')}</p>
        {!revision && <button className="primary" disabled={busy} onClick={() => void edit()}>{t('wizard.edit')}</button>}
      </div>
      {editable && revision && <>
        {visited.includes('documents') && <div hidden={step !== 'documents'}><WizardDocuments revisionId={revision.id} groups={groups} onChanged={refresh} onDirtyChange={documentsDirty}
          targetPage={fix?.step === 'documents' && fix.code === '' ? fix.visual_page_id : undefined}
          targetArtifactId={fix?.step === 'documents' ? fix.artifact_id : undefined} /></div>}
        {visited.includes('parts') && <div hidden={step !== 'parts'}><WizardParts revisionId={revision.id} groups={groups} groupId={groupId} setGroupId={changeGroup}
          onChanged={refresh} incompleteOnly={fix?.step === 'parts'} onDirtyChange={importDirty} onEditorDirtyChange={partsDirty} editorDirty={!!dirtyChildren.parts}
          onDocumentProblem={page => { setFix({ code: '', step: 'documents', visual_page_id: page }); navigate('documents') }} /></div>}
        {visited.includes('hotspots') && <div hidden={step !== 'hotspots'}>
          <label>{t('wizard.group')}<select value={groupId ?? ''} onChange={event => changeGroup(Number(event.target.value))}>{groups.map(group => <option key={group.id} value={group.id}>{label(group)}</option>)}</select></label>
          {groupId && <RevisionHotspotEditor key={groupId} assemblyId={groupId} editable simple
            initialFilter={fix?.step === 'hotspots' ? fix.code.includes('coverage') ? 'unmarked' : 'unverified' : 'all'}
            initialPageId={fix?.visual_page_id} initialPosition={fix?.position} onDirtyChange={hotspotsDirty} />}
          <button className="secondary" onClick={() => { if (kits && dirtyChildren.kits && !window.confirm(t('wizard.unsaved'))) return; setKits(value => !value) }}>{t('wizard.optionalKits')}</button>
          {kits && groupId && <RevisionRepairKits key={groupId} assemblyId={groupId} editable onDirtyChange={kitsDirty} />}
        </div>}
      </>}
      <div hidden={step !== 'review'}><WizardReview workflow={workflow} editable={!!editable} busy={busy || Object.values(dirtyChildren).some(Boolean)} onFix={fixIssue} onPublish={() => void publish()} /></div>
      {editable && <div className="actions wizard-navigation"><button className="secondary" disabled={steps.indexOf(step) === 0} onClick={() => navigate(steps[steps.indexOf(step) - 1])}>{t('wizard.back')}</button>
        <button className="primary" disabled={step === 'review'} onClick={() => { setFix(null); navigate(steps[steps.indexOf(step) + 1]) }}>{t('wizard.continue')}</button></div>}
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
