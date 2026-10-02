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

export default function GuidedWorkspace({ revisionId, groups, task, changed, onDirtyChange, target }: {
  revisionId: number; groups: Group[]; task: Step; changed: () => Promise<void>; onDirtyChange: (dirty: boolean) => void; target?: { assembly_id?: number; reference_page_id?: number }
}) {
  const { t, locale } = useI18n()
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
  useEffect(() => { setName(''); setRenaming(null); setDirty(false); setKitDirty(false) }, [task])
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
  function canNavigate() { return !(dirty || titleDirty || kitDirty) || window.confirm(t('wizard.unsaved')) }
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
  return <section className="guided-workspace">
    {error && <p className="error" role="alert">{error}</p>}
    {task === 'references' ? <>
      <h4>{t('guided.references')}</h4>
      <div className="builder-list">{groups.map((group, index) => <article className="builder-list-item" key={group.id}>
        <strong>{label(group)}</strong><div className="actions">
          <button className="secondary" disabled={busy} onClick={() => { setRenaming(group.id); setName(label(group)) }}>{t('common.edit')}</button>
          <button className="secondary" disabled={busy} onClick={() => void action(() => api(`${builderBase}/assemblies/${group.id}`, { method: 'DELETE' }))}>{t('guided.delete')}</button>
          <button className="secondary" disabled={busy || !index} onClick={() => void action(async () => {
            const ordered = groups.map(row => row.id)
            ;[ordered[index - 1], ordered[index]] = [ordered[index], ordered[index - 1]]
            await api(`${builderBase}/revisions/${revisionId}/references/reorder`, { method: 'POST', body: JSON.stringify({ expected_ids: groups.map(row => row.id), ordered_ids: ordered }) })
          })}>{t('guided.moveUp')}</button>
        </div></article>)}</div>
      <form onSubmit={event => { event.preventDefault(); void saveReference() }} className="form-grid">
        <label>{t('guided.reference')}<input required maxLength={255} disabled={busy} value={name} onChange={event => setName(event.target.value)} /></label>
        <button className="primary" disabled={busy || !name.trim()}>{t(renaming ? 'common.save' : 'guided.addReference')}</button>
        {renaming && <button type="button" className="secondary" onClick={() => { setName(''); setRenaming(null) }}>{t('common.cancel')}</button>}
      </form>
    </> : <>
      <label>{t('guided.reference')}<select disabled={busy} value={assemblyId ?? ''} onChange={event => { if (canNavigate()) setAssemblyId(Number(event.target.value)) }}>
        <option value="">{t('guided.select')}</option>{groups.map(group => <option key={group.id} value={group.id}>{label(group)}</option>)}
      </select></label>
      <nav className="actions" aria-label={t('guided.pages')}>{pages.map((item, index) => <button key={item.id} disabled={busy}
        className={pageId === item.id ? 'primary' : 'secondary'} aria-current={pageId === item.id ? 'page' : undefined}
        onClick={() => { if (canNavigate()) setPageId(item.id) }}>{t('guided.page', { number: index + 1 })} · {t(`guided.${item.status}`)}</button>)}
        {assemblyId && task === 'documents' && <button className="secondary" disabled={busy || dirty} onClick={() => void action(async () => {
          const created = await api<ReferencePage>(`${builderBase}/assemblies/${assemblyId}/reference-pages`, { method: 'POST', body: '{}' }); setPageId(created.id)
        })}>{t('guided.addPage')}</button>}
      </nav>
      {page && assembly ? <>
        <p className="guided-breadcrumb">{label(assembly)} › {t('guided.page', { number: pages.indexOf(page) + 1 })} › {t(task === 'documents' ? 'guided.pages' : `wizard.${task}`)}</p>
        <p role="status">{t('guided.dashboard', { schemes: page.scheme_count, lists: page.spare_list_count, parts: page.part_count,
          mapped: page.mapped_position_count, positions: page.position_count })}</p>
        {task === 'documents' && <>
          <GuidedSources key={page.id} revisionId={revisionId} page={page} changed={refresh} onDirtyChange={setDirty} />
          <details><summary>{t('guided.advanced')}</summary><form className="form-grid" onSubmit={event => { event.preventDefault(); void action(() => api(`${builderBase}/reference-pages/${page.id}`, { method: 'PATCH', body: JSON.stringify({ expected_version: page.version, title: pageTitle.trim() || null }) })) }}>
            <label>{t('builder.title')}<input value={pageTitle} maxLength={255} disabled={busy} onChange={event => setPageTitle(event.target.value)} /></label>
            <button className="secondary" disabled={busy || !titleDirty}>{t('common.save')}</button>
          </form><div className="actions">
            <button className="secondary" disabled={busy || dirty || !pages.indexOf(page)} onClick={() => void action(async () => {
              const ordered = [...pages]; const index = pages.indexOf(page)
              ;[ordered[index - 1], ordered[index]] = [ordered[index], ordered[index - 1]]
              await api(`${builderBase}/assemblies/${assemblyId}/reference-pages/reorder`, { method: 'POST', body: JSON.stringify({ pages: ordered.map(row => ({ id: row.id, expected_version: row.version })) }) })
            })}>{t('guided.moveUp')}</button>
            <button className="secondary" disabled={busy || dirty} onClick={() => void action(() => api(`${builderBase}/reference-pages/${page.id}?expected_version=${page.version}`, { method: 'DELETE' }))}>{t('guided.delete')}</button>
          </div></details>
        </>}
        {task === 'parts' && <GuidedParts key={page.id} page={page} changed={refresh} onDirtyChange={setDirty} />}
        {task === 'hotspots' && <>
          <RevisionHotspotEditor key={page.id} assemblyId={assembly.id} referencePageId={page.id} editable simple onDirtyChange={setDirty} onChanged={refresh} />
          <details><summary>{t('wizard.optionalKits')}</summary><RevisionRepairKits assemblyId={assembly.id} editable onDirtyChange={setKitDirty} /></details>
        </>}
      </> : <p role="status">{t('guided.choosePage')}</p>}
    </>}
  </section>
}
