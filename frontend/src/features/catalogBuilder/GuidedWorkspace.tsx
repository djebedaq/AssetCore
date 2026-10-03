import { useEffect, useState } from 'react'
import { api } from '../../api'
import { useI18n } from '../../i18n'
import { guidedError } from './guidedErrors'
import GuidedParts from './GuidedParts'
import GuidedSources from './GuidedSources'
import RevisionHotspotEditor from './RevisionHotspotEditor'
import RevisionRepairKits from './RevisionRepairKits'
import type { ReferencePage } from './guidedTypes'
import { builderBase, type Group, type Step } from './wizardTypes'

const localTask = (step: Step): Step => step === 'parts' || step === 'hotspots' ? step : 'documents'

export default function GuidedWorkspace({ revisionId, groups, task: initialTask, changed, onDirtyChange, target }: {
  revisionId: number; groups: Group[]; task: Step; changed: () => Promise<void>; onDirtyChange: (dirty: boolean) => void; target?: { assembly_id?: number; reference_page_id?: number }
}) {
  const { t, locale } = useI18n()
  const [task, setTask] = useState<Step>(localTask(initialTask))
  const [overview, setOverview] = useState<Record<number, ReferencePage[]>>({})
  const [assemblyId, setAssemblyId] = useState<number | null>(groups[0]?.id || null)
  const [pages, setPages] = useState<ReferencePage[]>([])
  const [pageId, setPageId] = useState<number | null>(null)
  const [pageTitle, setPageTitle] = useState('')
  const [name, setName] = useState('')
  const [renaming, setRenaming] = useState<number | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [dirty, setDirty] = useState(false)
  const [kitDirty, setKitDirty] = useState(false)
  const page = pages.find(item => item.id === pageId)
  const titleDirty = !!page && pageTitle !== (page.title || '')
  useEffect(() => { setPageTitle(page?.title || '') }, [page?.id, page?.title])
  const assembly = groups.find(item => item.id === assemblyId)
  const label = (group: Group) => group[`name_${locale}`] || group.name_bg
  useEffect(() => { onDirtyChange(busy || !!name || dirty || titleDirty || kitDirty); return () => onDirtyChange(false) }, [busy, name, dirty, titleDirty, kitDirty, onDirtyChange])
  useEffect(() => { if (target) setTask(localTask(initialTask)) }, [target, initialTask])
  useEffect(() => {
    let active = true
    void Promise.all(groups.map(async group => [group.id, await api<ReferencePage[]>(`${builderBase}/assemblies/${group.id}/reference-pages`)] as const))
      .then(rows => { if (active) setOverview(Object.fromEntries(rows)) }).catch(() => { if (active) setError(t('guided.error')) })
    return () => { active = false }
  }, [groups])
  useEffect(() => { if (target?.assembly_id) setAssemblyId(target.assembly_id) }, [target])
  useEffect(() => { setAssemblyId(id => groups.some(group => group.id === id) ? id : groups[0]?.id || null) }, [groups])
  async function load() {
    if (!assemblyId) { setPages([]); setPageId(null); return }
    const rows = await api<ReferencePage[]>(`${builderBase}/assemblies/${assemblyId}/reference-pages`)
    setPages(rows); setPageId(id => rows.some(item => item.id === id) ? id : rows[0]?.id || null)
  }
  useEffect(() => {
    let active = true
    setPages([]); setPageId(null)
    if (assemblyId) void api<ReferencePage[]>(`${builderBase}/assemblies/${assemblyId}/reference-pages`).then(rows => {
      if (active) { setPages(rows); setPageId(rows.find(row => row.id === target?.reference_page_id)?.id || rows[0]?.id || null) }
    }).catch(() => { if (active) setError(t('guided.error')) })
    return () => { active = false }
  }, [assemblyId, target])
  async function refresh() { await load(); await changed() }
  async function action(work: () => Promise<unknown>) {
    if (busy) return
    setBusy(true); setError('')
    try { await work(); await refresh() } catch (caught) { setError(t(guidedError(caught))) } finally { setBusy(false) }
  }
  function canNavigate() { return !busy && (!(dirty || titleDirty || kitDirty || name) || window.confirm(t('wizard.unsaved'))) }
  async function saveReference() {
    if (!name.trim()) return
    await action(async () => {
      if (renaming) await api(`${builderBase}/assemblies/${renaming}`, { method: 'PATCH', body: JSON.stringify({ name_bg: name.trim(), name_en: name.trim(), name_ru: name.trim() }) })
      else {
        const created = await api<Group>(`${builderBase}/revisions/${revisionId}/groups`, { method: 'POST', body: JSON.stringify({ name }) })
        setAssemblyId(created.id)
      }
      setName(''); setRenaming(null)
    })
  }
  function navigateTask(next: Step) { if (canNavigate()) { setTask(next); setDirty(false); setKitDirty(false) } }
  const nextTask: Step = !page?.scheme_count || !page?.spare_list_count ? 'documents' : !page.part_count ? 'parts' : 'hotspots'
  return <section className="guided-workspace">
    {error && <p className="error" role="alert">{error}</p>}
    <aside className="reference-sidebar">
      <h4>{t('guided.references')}</h4>
      <nav aria-label={t('guided.references')}>{groups.map((group, index) => <div key={group.id} className="reference-row">
        <button className="secondary reference-link" disabled={busy} aria-current={assemblyId === group.id ? 'page' : undefined}
          onClick={() => { if (canNavigate()) { setAssemblyId(group.id); setTask('documents'); setDirty(false); setName(''); setRenaming(null) } }}>
          <span>{label(group)}</span><small>{overview[group.id]?.length ? overview[group.id].every(item => item.status === 'COMPLETE') ? t('guided.COMPLETE') : t('workspace.pageCount', { count: overview[group.id].length }) : t('guided.NOT_STARTED')}</small>
        </button>
        <details className="reference-menu"><summary aria-label={t('workspace.referenceOptions', { name: label(group) })}>⋯</summary><div>
          <button className="secondary" disabled={busy} onClick={() => { if (canNavigate()) { setRenaming(group.id); setName(label(group)) } }}>{t('common.edit')}</button>
          <button className="secondary" disabled={busy} onClick={() => { if (canNavigate() && window.confirm(t('workspace.deleteReferenceConfirm'))) void action(() => api(`${builderBase}/assemblies/${group.id}`, { method: 'DELETE' })) }}>{t('guided.delete')}</button>
          <button className="secondary" disabled={busy || !index} onClick={() => void action(async () => {
            const ordered = groups.map(row => row.id)
            ;[ordered[index - 1], ordered[index]] = [ordered[index], ordered[index - 1]]
            await api(`${builderBase}/revisions/${revisionId}/references/reorder`, { method: 'POST', body: JSON.stringify({ expected_ids: groups.map(row => row.id), ordered_ids: ordered }) })
          })}>{t('guided.moveUp')}</button>
        </div></details>
      </div>)}</nav>
      <form onSubmit={event => { event.preventDefault(); void saveReference() }} className="form-grid">
        <label>{t('guided.reference')}<input required maxLength={255} disabled={busy} value={name} onChange={event => setName(event.target.value)} /></label>
        <button className="primary" disabled={busy || !name.trim()}>{t(renaming ? 'common.save' : 'guided.addReference')}</button>
        {renaming && <button type="button" className="secondary" onClick={() => { setName(''); setRenaming(null) }}>{t('common.cancel')}</button>}
      </form>
    </aside>
    <fieldset className="reference-content" disabled={busy} aria-busy={busy}>
      <h4 className="guided-breadcrumb">{assembly ? label(assembly) : t('guided.addReference')}</h4>
      <nav className="page-tabs" aria-label={t('guided.pages')}>{pages.map((item, index) => <button key={item.id} disabled={busy}
        className="secondary" aria-current={pageId === item.id ? 'page' : undefined}
        onClick={() => { if (canNavigate()) { setPageId(item.id); setTask('documents'); setDirty(false); setKitDirty(false) } }}>
          {t('guided.page', { number: index + 1 })}<small>{t(`guided.${item.status}`)}</small></button>)}
        {assemblyId && <button className="secondary" aria-label={t('guided.addPage')} disabled={busy || dirty || titleDirty || kitDirty} onClick={() => void action(async () => {
          const created = await api<ReferencePage>(`${builderBase}/assemblies/${assemblyId}/reference-pages`, { method: 'POST', body: '{}' }); setPageId(created.id); setTask('documents')
        })}>+ {t('guided.addPage')}</button>}
      </nav>
      {page && assembly ? <>
        <p role="status">{t('guided.dashboard', { schemes: page.scheme_count, lists: page.spare_list_count, parts: page.part_count,
          mapped: page.mapped_position_count, positions: page.position_count })}</p>
        <div className="page-workflow">
          <nav aria-label={t('workspace.pageWork')}>
            {(['documents', 'parts', 'hotspots'] as const).map(value => <button key={value} className="secondary" aria-current={task === value ? 'page' : undefined}
              onClick={() => navigateTask(value)}>{t(value === 'documents' ? 'workspace.sources' : `wizard.${value}`)}</button>)}
          </nav>
          {page.status === 'COMPLETE' ? <span role="status">✓ {t('workspace.pageComplete')}</span> : task !== nextTask && <button className="primary" onClick={() => navigateTask(nextTask)}>{t(nextTask === 'documents' ? 'workspace.sources' : nextTask === 'parts' ? 'guided.extract' : 'wizard.hotspots')}</button>}
        </div>
        {task === 'documents' && <>
          <GuidedSources key={page.id} revisionId={revisionId} page={page} contextLabel={`${label(assembly)} › ${t('guided.page', { number: pages.indexOf(page) + 1 })}`} changed={refresh} onDirtyChange={setDirty} />
          <details><summary>{t('guided.advanced')}</summary><form className="form-grid" onSubmit={event => { event.preventDefault(); void action(() => api(`${builderBase}/reference-pages/${page.id}`, { method: 'PATCH', body: JSON.stringify({ expected_version: page.version, title: pageTitle.trim() || null }) })) }}>
            <label>{t('builder.title')}<input value={pageTitle} maxLength={255} disabled={busy} onChange={event => setPageTitle(event.target.value)} /></label>
            <button className="secondary" disabled={busy || !titleDirty}>{t('common.save')}</button>
          </form><div className="actions">
            <button className="secondary" disabled={busy || dirty || !pages.indexOf(page)} onClick={() => void action(async () => {
              const ordered = [...pages]; const index = pages.indexOf(page)
              ;[ordered[index - 1], ordered[index]] = [ordered[index], ordered[index - 1]]
              await api(`${builderBase}/assemblies/${assemblyId}/reference-pages/reorder`, { method: 'POST', body: JSON.stringify({ pages: ordered.map(row => ({ id: row.id, expected_version: row.version })) }) })
            })}>{t('guided.moveUp')}</button>
            <button className="secondary" disabled={busy || dirty} onClick={() => { if (window.confirm(t('workspace.deletePageConfirm'))) void action(() => api(`${builderBase}/reference-pages/${page.id}?expected_version=${page.version}`, { method: 'DELETE' })) }}>{t('guided.delete')}</button>
          </div></details>
        </>}
        {task === 'parts' && <GuidedParts key={page.id} page={page} changed={refresh} onDirtyChange={setDirty} />}
        {task === 'hotspots' && <>
          <RevisionHotspotEditor key={page.id} assemblyId={assembly.id} contextLabel={`${label(assembly)} › ${t('guided.page', { number: pages.indexOf(page) + 1 })}`} referencePageId={page.id} editable simple onDirtyChange={setDirty} onChanged={refresh} />
          <details><summary>{t('wizard.optionalKits')}</summary><RevisionRepairKits assemblyId={assembly.id} editable onDirtyChange={setKitDirty} /></details>
        </>}
      </> : <p role="status">{t('guided.choosePage')}</p>}
    </fieldset>
  </section>
}
