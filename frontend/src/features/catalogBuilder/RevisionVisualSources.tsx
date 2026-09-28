import { useEffect, useRef, useState, type FormEvent } from 'react'
import { api, ApiError, createApiObjectUrl, downloadApiFile } from '../../api'
import { filePayload, Modal } from '../../industrialUi'
import { useI18n, type TranslationKey } from '../../i18n'

type Role = 'EXPLODED_SCHEME' | 'SPARE_PARTS_LIST'
type Assembly = { id: number; code: string; name_bg: string; name_en: string; name_ru: string;
  description: string | null; sort_order: number; artifact_count: number;
  exploded_page_count: number; spare_list_page_count: number }
type Artifact = { id: number; title: string; filename: string; sha256: string; page_count: number;
  document_reference: string | null; document_date: string | null; language: string | null }
type Assignment = { id: number; artifact_id: number; page_number: number; role: Role }
type AssemblyForm = Pick<Assembly, 'code' | 'name_bg' | 'name_en' | 'name_ru' | 'sort_order'> & { description: string }

const blank: AssemblyForm = { code: '', name_bg: '', name_en: '', name_ru: '', description: '', sort_order: 0 }
const errorKeys: Record<string, TranslationKey> = {
  catalog_assembly_not_found: 'builder.error.notFound', catalog_source_not_found: 'builder.error.notFound',
  catalog_assembly_duplicate: 'builder.error.assemblyDuplicate',
  catalog_assembly_code_immutable: 'builder.error.assemblyCode',
  catalog_assembly_code_in_use: 'builder.error.assemblyCodeInUse',
  catalog_source_duplicate: 'builder.error.sourceDuplicate',
  catalog_source_invalid_pdf: 'builder.error.invalidPdf',
  catalog_source_too_large: 'builder.error.tooLarge',
  catalog_visual_page_invalid: 'builder.error.pageInvalid',
  catalog_visual_role_invalid: 'builder.error.roleInvalid',
  catalog_visual_page_duplicate: 'builder.error.pageDuplicate',
  catalog_revision_not_draft: 'builder.error.revisionImmutable',
  catalog_inactive: 'builder.error.inactive', validation_error: 'builder.error.invalid',
}

function Thumbnail({ artifactId, pageNumber }: { artifactId: number; pageNumber: number }) {
  const { t } = useI18n()
  const ref = useRef<HTMLDivElement>(null)
  const [url, setUrl] = useState('')
  useEffect(() => {
    let active = true
    let objectUrl = ''
    const node = ref.current
    if (!node) return
    const observer = new IntersectionObserver(entries => {
      if (!entries[0]?.isIntersecting) return
      observer.disconnect()
      void createApiObjectUrl(`/admin/catalog-builder/artifacts/${artifactId}/pages/${pageNumber}/preview`)
        .then(result => { if (active) { objectUrl = result.url; setUrl(result.url) } else URL.revokeObjectURL(result.url) })
        .catch(() => { if (active) setUrl('error') })
    }, { rootMargin: '160px' })
    observer.observe(node)
    return () => { active = false; observer.disconnect(); if (objectUrl) URL.revokeObjectURL(objectUrl) }
  }, [artifactId, pageNumber])
  return <div ref={ref} className="builder-thumbnail">{url && url !== 'error' ?
    <img src={url} alt={t('builder.pageNumber', { count: pageNumber })} loading="lazy" /> :
    <span>{url === 'error' ? t('builder.previewError') : t('builder.previewPending')}</span>}</div>
}

export default function RevisionVisualSources({ revisionId, editable }: { revisionId: number; editable: boolean }) {
  const { locale, t } = useI18n()
  const [assemblies, setAssemblies] = useState<Assembly[]>([])
  const [assemblyId, setAssemblyId] = useState<number | null>(null)
  const [artifacts, setArtifacts] = useState<Artifact[]>([])
  const [artifactId, setArtifactId] = useState<number | null>(null)
  const [assignments, setAssignments] = useState<Assignment[]>([])
  const [selectedPages, setSelectedPages] = useState<number[]>([])
  const [edit, setEdit] = useState<Assembly | 'new' | null>(null)
  const [form, setForm] = useState<AssemblyForm>(blank)
  const [upload, setUpload] = useState(false)
  const [uploadTitle, setUploadTitle] = useState('')
  const [uploadFile, setUploadFile] = useState<File | null>(null)
  const [intent, setIntent] = useState<Role | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const assembly = assemblies.find(item => item.id === assemblyId)
  const artifact = artifacts.find(item => item.id === artifactId)
  const label = (item: Assembly) => item[`name_${locale}`] || item.name_bg
  const message = (caught: unknown) => t(caught instanceof ApiError && caught.code && errorKeys[caught.code]
    ? errorKeys[caught.code] : 'builder.error.generic')

  async function loadAssemblies() {
    setAssemblies(await api<Assembly[]>(`/admin/catalog-builder/revisions/${revisionId}/assemblies`))
  }
  async function loadArtifacts(id: number) {
    setArtifacts(await api<Artifact[]>(`/admin/catalog-builder/assemblies/${id}/artifacts`))
  }
  async function loadAssignments(id: number) {
    setAssignments(await api<Assignment[]>(`/admin/catalog-builder/artifacts/${id}/visual-pages`))
  }
  useEffect(() => { setAssemblyId(null); setArtifactId(null); void loadAssemblies().catch(caught => setError(message(caught))) }, [revisionId])
  useEffect(() => { setArtifactId(null); setArtifacts([]); if (assemblyId) void loadArtifacts(assemblyId).catch(caught => setError(message(caught))) }, [assemblyId])
  useEffect(() => { setAssignments([]); setSelectedPages([]); if (artifactId) void loadAssignments(artifactId).catch(caught => setError(message(caught))) }, [artifactId])

  function openAssembly(item: Assembly | 'new') {
    setEdit(item)
    setForm(item === 'new' ? blank : { code: item.code, name_bg: item.name_bg, name_en: item.name_en,
      name_ru: item.name_ru, description: item.description || '', sort_order: item.sort_order })
  }
  async function saveAssembly(event: FormEvent) {
    event.preventDefault()
    if (!edit || busy) return
    setBusy(true)
    try {
      const payload = { ...form, description: form.description || null }
      if (edit === 'new') {
        const created = await api<Assembly>(`/admin/catalog-builder/revisions/${revisionId}/assemblies`,
          { method: 'POST', body: JSON.stringify(payload) })
        setAssemblyId(created.id)
      } else {
        const { code: _code, ...changes } = payload
        void _code
        await api(`/admin/catalog-builder/assemblies/${edit.id}`, { method: 'PATCH', body: JSON.stringify(changes) })
      }
      setEdit(null); setError(''); await loadAssemblies()
    } catch (caught) { setError(message(caught)) } finally { setBusy(false) }
  }
  async function removeAssembly(item: Assembly) {
    if (!window.confirm(t('builder.deleteAssemblyConfirm'))) return
    try {
      await api(`/admin/catalog-builder/assemblies/${item.id}`, { method: 'DELETE' })
      if (assemblyId === item.id) setAssemblyId(null)
      await loadAssemblies()
    } catch (caught) { setError(message(caught)) }
  }
  async function sendUpload(event: FormEvent) {
    event.preventDefault()
    if (!assemblyId || !uploadFile || busy) return
    setBusy(true)
    try {
      const created = await api<Artifact>(`/admin/catalog-builder/assemblies/${assemblyId}/artifacts`, {
        method: 'POST', body: JSON.stringify({ title: uploadTitle, ...(await filePayload(uploadFile)) }),
      })
      setUpload(false); setUploadFile(null); setUploadTitle(''); setArtifactId(created.id)
      await Promise.all([loadArtifacts(assemblyId), loadAssemblies()])
      setError('')
    } catch (caught) {
      if (caught instanceof ApiError && caught.code === 'catalog_source_duplicate' && typeof caught.data.artifact_id === 'number') {
        setArtifactId(caught.data.artifact_id); setUpload(false); setUploadFile(null); setUploadTitle(''); await loadArtifacts(assemblyId)
      } else setError(message(caught))
    } finally { setBusy(false) }
  }
  async function removeArtifact(item: Artifact) {
    if (!window.confirm(t('builder.deleteSourceConfirm'))) return
    try {
      await api(`/admin/catalog-builder/artifacts/${item.id}`, { method: 'DELETE' })
      if (artifactId === item.id) setArtifactId(null)
      if (assemblyId) await Promise.all([loadArtifacts(assemblyId), loadAssemblies()])
    } catch (caught) { setError(message(caught)) }
  }
  async function assign(role: Role) {
    if (!artifactId || !selectedPages.length || busy) return
    setBusy(true)
    try {
      await api(`/admin/catalog-builder/artifacts/${artifactId}/visual-pages`, {
        method: 'POST', body: JSON.stringify({ role, page_numbers: selectedPages }),
      })
      setSelectedPages([]); setIntent(null)
      await Promise.all([loadAssignments(artifactId), loadAssemblies()])
      setError('')
    } catch (caught) { setError(message(caught)) } finally { setBusy(false) }
  }
  async function removeAssignment(item: Assignment) {
    if (!artifactId) return
    try {
      await api(`/admin/catalog-builder/visual-pages/${item.id}`, { method: 'DELETE' })
      await Promise.all([loadAssignments(artifactId), loadAssemblies()])
    } catch (caught) { setError(message(caught)) }
  }
  const roleLabel = (role: Role) => t(role === 'EXPLODED_SCHEME' ? 'builder.role.exploded' : 'builder.role.spare')
  return <div className="builder-workspace">
    {error && <p className="error" role="alert">{error}</p>}
    <div className="actions">{editable && <button className="primary compact" onClick={() => openAssembly('new')}>{t('builder.addAssembly')}</button>}</div>
    {!assemblies.length && <p>{t('builder.noAssemblies')}</p>}
    {assemblies.map(item => <div className="builder-row" key={item.id}>
      <span><b>{item.code}</b> · {label(item)}<small>{t('builder.sourceCount', { count: item.artifact_count })} · {t('builder.explodedCount', { count: item.exploded_page_count })} · {t('builder.spareCount', { count: item.spare_list_page_count })}</small></span>
      <div className="actions"><button className="secondary compact" onClick={() => setAssemblyId(item.id)}>{t('builder.open')}</button>
        {editable && <><button className="secondary compact" onClick={() => openAssembly(item)}>{t('common.edit')}</button>
          <button className="secondary compact" onClick={() => void removeAssembly(item)}>{t('common.remove')}</button></>}</div>
    </div>)}
    {assembly && <section className="panel"><div className="panel-title"><h4>{assembly.code} · {label(assembly)}</h4>
      <button className="secondary compact" onClick={() => setAssemblyId(null)}>{t('common.close')}</button></div>
      {editable && <div className="actions"><button className="primary compact" onClick={() => { setIntent('EXPLODED_SCHEME'); setArtifactId(null) }}>{t('builder.addExploded')}</button>
        <button className="primary compact" onClick={() => { setIntent('SPARE_PARTS_LIST'); setArtifactId(null) }}>{t('builder.addSpare')}</button>
        <button className="secondary compact" onClick={() => { setUploadFile(null); setUploadTitle(''); setUpload(true) }}>{t('builder.uploadSource')}</button></div>}
      {intent && <p>{t('builder.chooseSourceForRole', { role: roleLabel(intent) })}</p>}
      {!artifacts.length && <p>{t('builder.noSources')}</p>}
      {artifacts.map(item => <div className="builder-row" key={item.id}><span><b>{item.title}</b> · {item.filename}<small>SHA-256: {item.sha256} · {t('builder.pageCount', { count: item.page_count })}</small></span>
        <div className="actions"><button className="secondary compact" onClick={() => setArtifactId(item.id)}>{t('builder.open')}</button>
          <button className="secondary compact" onClick={() => void downloadApiFile(`/admin/catalog-builder/artifacts/${item.id}/download`, item.filename)}>{t('builder.downloadSource')}</button>
          {editable && <button className="secondary compact" onClick={() => void removeArtifact(item)}>{t('common.remove')}</button>}</div></div>)}
      {artifact && <section className="builder-pages"><h4>{artifact.title} · {t('builder.pageCount', { count: artifact.page_count })}</h4>
        <p>SHA-256: {artifact.sha256}</p>
        {editable && <div className="actions">{intent ?
          <button className="primary compact" disabled={!selectedPages.length || busy} onClick={() => void assign(intent)}>{t('builder.assignIntendedRole', { role: roleLabel(intent) })}</button> :
          <><button className="primary compact" disabled={!selectedPages.length || busy} onClick={() => void assign('EXPLODED_SCHEME')}>{t('builder.markExploded')}</button>
            <button className="primary compact" disabled={!selectedPages.length || busy} onClick={() => void assign('SPARE_PARTS_LIST')}>{t('builder.markSpare')}</button></>}</div>}
        <div className="builder-page-grid">{Array.from({ length: artifact.page_count }, (_, index) => index + 1).map(number => {
          const pageRoles = assignments.filter(item => item.page_number === number)
          return <article className="builder-page-card" key={number}>
            <Thumbnail artifactId={artifact.id} pageNumber={number} />
            <b>{t('builder.pageNumber', { count: number })}</b>
            {editable && <label><input type="checkbox" checked={selectedPages.includes(number)} onChange={() => setSelectedPages(pages => pages.includes(number) ? pages.filter(page => page !== number) : [...pages, number])} />{t('builder.selectPage')}</label>}
            {!pageRoles.length && <span className="muted">{t('builder.noRole')}</span>}
            {pageRoles.map(page => <div key={page.id} className="actions"><span className="badge">{roleLabel(page.role)}</span>{editable && <button className="secondary compact" onClick={() => void removeAssignment(page)}>{t('builder.removeRole')}</button>}</div>)}
          </article>
        })}</div>
      </section>}
    </section>}
    {edit && <Modal title={t(edit === 'new' ? 'builder.addAssembly' : 'builder.editAssembly')} onClose={() => setEdit(null)}><form className="form-grid" onSubmit={event => void saveAssembly(event)}>
      <label>{t('builder.code')}<input required pattern="[A-Z][A-Z0-9_]+" readOnly={edit !== 'new'} value={form.code} onChange={event => setForm({ ...form, code: event.target.value.toUpperCase() })} /></label>
      {(['bg', 'en', 'ru'] as const).map(language => <label key={language}>{t(`builder.name.${language}`)}<input required value={form[`name_${language}`]} onChange={event => setForm({ ...form, [`name_${language}`]: event.target.value })} /></label>)}
      <label>{t('builder.sortOrder')}<input type="number" value={form.sort_order} onChange={event => setForm({ ...form, sort_order: Number(event.target.value) })} /></label>
      <label className="wide">{t('builder.description')}<textarea value={form.description} onChange={event => setForm({ ...form, description: event.target.value })} /></label>
      <div className="actions wide"><button type="button" className="secondary" onClick={() => setEdit(null)}>{t('common.cancel')}</button><button className="primary" disabled={busy}>{t('common.save')}</button></div>
    </form></Modal>}
    {upload && <Modal title={t('builder.uploadSource')} onClose={() => { setUpload(false); setUploadFile(null) }}><form className="form-grid" onSubmit={event => void sendUpload(event)}>
      <label>{t('builder.sourceTitle')}<input required value={uploadTitle} onChange={event => setUploadTitle(event.target.value)} /></label>
      <label>{t('builder.pdfFile')}<input type="file" accept="application/pdf,.pdf" onChange={event => setUploadFile(event.target.files?.[0] || null)} /></label>
      <div className="actions wide"><button type="button" className="secondary" onClick={() => { setUpload(false); setUploadFile(null) }}>{t('common.cancel')}</button><button className="primary" disabled={busy || !uploadFile || !uploadTitle.trim()}>{t('common.save')}</button></div>
    </form></Modal>}
  </div>
}
