import { useEffect, useState, type FormEvent } from 'react'
import { api } from '../../api'
import { DownloadButton, filePayload } from '../../industrialUi'
import { useI18n, type TranslationKey } from '../../i18n'
import type { Locale } from '../../locale'
import { hasPermission } from '../../permissions'
import { VisualEditor } from './VisualEditor'
import { studioError, type Draft, type StudioTemplate } from './shared'

const workflows = ['TRANSFER_ISSUE', 'TRANSFER_RETURN', 'REPAIR_PROTOCOL', 'PART_REQUEST'] as const
const typeKey = (value: string): TranslationKey => workflows.includes(value as typeof workflows[number]) ? `studio.${value}` as TranslationKey : 'studio.OTHER'

function TemplateDetails({ template, reload, onDirty }: { template: StudioTemplate; reload: () => Promise<void>; onDirty: (d: boolean) => void }) {
  const { t, locale } = useI18n()
  const editable = hasPermission('templates.manage')
  const [language, setLanguage] = useState<Locale>(locale)
  const [title, setTitle] = useState('')
  const [base, setBase] = useState('')
  const [design, setDesign] = useState('professional')
  const [selections, setSelections] = useState<{ revision: number; selection_kind: string; version_id: number; created_at: string; reason: string }[]>([])
  const [drafts, setDrafts] = useState<Draft[]>([])
  const [opened, setOpened] = useState<Draft | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<TranslationKey | null>(null)
  const [file, setFile] = useState<File | null>(null)
  const [note, setNote] = useState('')
  const [draftDirty, setDraftDirty] = useState(false)
  const [activationNote, setActivationNote] = useState('')
  const formDirty = !!title || !!file || !!note
  useEffect(() => { onDirty(draftDirty || formDirty || busy); return () => onDirty(false) }, [draftDirty, formDirty, busy, onDirty])
  useEffect(() => {
    let live = true
    void api<Draft[]>(`/studio/templates/${template.id}/drafts`).then(rows => { if (live) setDrafts(rows) }).catch(e => { if (live) setError(studioError(e)) })
    return () => { live = false }
  }, [template.id])
  useEffect(() => { void api<typeof selections>(`/studio/selections/${template.document_type}/${language}`).then(setSelections).catch(e => setError(studioError(e))) }, [template.document_type, template.versions, language])
  async function create(event: FormEvent) {
    event.preventDefault(); setBusy(true); setError(null)
    try {
      const item = await api<Draft>(`/studio/templates/${template.id}/drafts`, { method: 'POST', body: JSON.stringify({ title, language, design, base_version_id: base ? Number(base) : null }) })
      setDrafts(current => [item, ...current]); setOpened(item); setTitle('')
    } catch (e) { setError(studioError(e)) } finally { setBusy(false) }
  }
  async function importFile(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!file) return
    if (file.size > 12_000_000) { setError('studio.invalidDocx'); return }
    const form = event.currentTarget
    setBusy(true); setError(null)
    try {
      const payload = await filePayload(file)
      await api(`/studio/templates/${template.id}/import`, { method: 'POST', body: JSON.stringify({ filename: file.name, content_base64: payload.content_base64, language, change_note: note }) })
      setFile(null); setNote(''); form.reset(); await reload()
    } catch (e) { setError(studioError(e)) } finally { setBusy(false) }
  }
  const date = (value: string) => new Intl.DateTimeFormat(locale, { dateStyle: 'medium', timeZone: 'UTC' }).format(new Date(/[Z+]$|[+-]\d{2}:\d{2}$/.test(value) ? value : `${value}Z`))
  if (opened) return <VisualEditor key={opened.id} draft={opened} documentType={template.document_type} published={reload} saved={next => { setOpened(next); setDrafts(rows => rows.map(row => row.id === next.id ? next : row)) }} onDirty={setDraftDirty} close={() => setOpened(null)} />
  return <section className="panel studio-template-details">
    <div className="panel-title"><div><h3>{template[`name_${locale}`] || template.name_bg}</h3><small>{template.code} · {t(typeKey(template.document_type))}</small></div></div>
    {error && <p className="error" role="alert">{t(error)}</p>}
    <h4>{t('studio.versions')}</h4>
    {editable && template.versions.some(v => v.studio) && <label>{t('editor.activationReason')}<textarea maxLength={2000} value={activationNote} onChange={e => setActivationNote(e.target.value)} /></label>}
    {!template.versions.length && <p className="muted">{t('studio.noVersions')}</p>}
    {template.versions.map(version => <article className="studio-version" key={version.id}>
      <div className="studio-version-heading"><b>{t('studio.version', { number: version.version })} · {t(`language.${version.language}`)}</b><span className={`studio-status ${version.status}`}>{t(`studio.${version.status}`)}</span><span className="studio-status">{t(`studio.${version.validation_status}`)}</span></div>
      {version.change_note && <p>{version.change_note}</p>}
      <dl><dt>{t('studio.created')}</dt><dd>{date(version.created_at)}</dd>{version.published_at && <><dt>{t('studio.published')}</dt><dd>{date(version.published_at)}</dd></>}{version.numbering_rule && <><dt>{t('studio.numbering')}</dt><dd>{version.numbering_rule}</dd></>}<dt>SHA-256</dt><dd><code>{version.source_sha256 || t('common.noValue')}</code></dd></dl>
      {version.active && <p className="studio-status PUBLISHED">{t(version.studio ? 'editor.active' : 'editor.legacyActive')}</p>}
      {editable && version.active && version.studio && <button className="secondary" disabled={busy || activationNote.trim().length < 3} onClick={async () => {
        if (!window.confirm(t('editor.legacyConfirm'))) return
        setBusy(true); setError(null)
        try { await api(`/studio/selections/${template.document_type}/${version.language}/restore-legacy`, { method: 'POST', body: JSON.stringify({ expected_version_id: version.id, expected_revision: version.selection_revision, reason: activationNote, confirmed: true }) }); setActivationNote(''); await reload() }
        catch (e) { setError(studioError(e)) } finally { setBusy(false) }
      }}>{t('editor.legacyRestore')}</button>}
      {editable && version.studio && !version.active && <div><p className="muted">{t('editor.activationHint')}</p><button className="secondary" disabled={busy || activationNote.trim().length < 3} onClick={async () => {
        setBusy(true); setError(null)
        try { await api(`/studio/versions/${version.id}/activate`, { method: 'POST', body: JSON.stringify({ expected_version_id: version.active_version_id, expected_revision: version.selection_revision, reason: activationNote }) }); setActivationNote(''); await reload() }
        catch (e) { setError(studioError(e)) } finally { setBusy(false) }
      }}>{t('editor.activate')}</button></div>}
      <DownloadButton path={version.download_endpoint} filename={version.source_filename || `${template.code}.docx`} label={t('studio.source')} />
    </article>)}
    <details><summary>{t('editor.selectionHistory')} · {t(`language.${language}`)}</summary>{selections.map(s => <article key={s.revision}><strong>{t('studio.revision', { number: s.revision })} · {t(s.selection_kind === 'STUDIO' ? 'editor.active' : 'editor.legacyActive')}</strong><p>{date(s.created_at)} · {s.reason}</p></article>)}</details>
    <p className="muted">{t('studio.numberingHint')}</p>
    <h4>{t('studio.drafts')}</h4>
    {!drafts.length && <p className="muted">{t('studio.noDrafts')}</p>}
    {drafts.map(draft => <div className="studio-draft-row" key={draft.id}><b>{draft.title}</b><span>{t(`language.${draft.language}` as TranslationKey)} · {t('studio.revision', { number: draft.revision })}</span><button disabled={busy} className="secondary compact" onClick={() => { if (!draftDirty || window.confirm(t('studio.leave'))) setOpened(draft) }}>{t('studio.open')}</button></div>)}
    {editable && <>
      <form className="studio-inline-form" onSubmit={create}><h4>{t('studio.newDraft')}</h4>
        {template.authoring_supported ? <><fieldset className="studio-fields" disabled={busy}><label>{t('studio.draftTitle')}<input required maxLength={255} value={title} onChange={e => setTitle(e.target.value)} /></label><label>{t('admin.templateLanguage')}<select value={language} onChange={e => { setLanguage(e.target.value as Locale); setBase('') }}>{(['bg', 'en', 'ru'] as const).map(lang => <option key={lang} value={lang}>{t(`language.${lang}`)}</option>)}</select></label><label>{t('editor.starter')}<select aria-label={t('editor.starter')} value={design} onChange={e => setDesign(e.target.value)}><option value="professional">{t('editor.professional')}</option><option value="blank">{t('editor.blank')}</option></select></label><label>{t('studio.base')}<select value={base} onChange={e => setBase(e.target.value)}><option value="">{t('studio.blank')}</option>{template.versions.filter(v => v.language === language).map(v => <option key={v.id} value={v.id}>{t('studio.version', { number: v.version })}</option>)}</select></label></fieldset><p className="muted">{t('studio.baseHint')}</p><button className="secondary" disabled={busy || !title.trim()}>{t('studio.create')}</button></> : <p className="muted">{t('studio.unsupported')}</p>}
      </form>
      <details><summary>{t('studio.import')}</summary><p className="muted">{t('studio.importHint')}</p><form className="studio-inline-form" onSubmit={importFile}><fieldset className="studio-fields" disabled={busy}><label>{t('studio.file')}<input type="file" required accept=".docx" onChange={e => setFile(e.target.files?.[0] || null)} /></label><label>{t('admin.templateLanguage')}<select value={language} onChange={e => { setLanguage(e.target.value as Locale); setBase('') }}>{(['bg', 'en', 'ru'] as const).map(lang => <option key={lang} value={lang}>{t(`language.${lang}`)}</option>)}</select></label><label>{t('studio.note')}<textarea required maxLength={2000} value={note} onChange={e => setNote(e.target.value)} /></label></fieldset><button className="secondary" disabled={busy || !file || !note.trim()}>{t('studio.import')}</button></form></details>
    </>}
  </section>
}

export function TemplateLibrary({ onDirty }: { onDirty: (d: boolean) => void }) {
  const { t, locale } = useI18n()
  const [templates, setTemplates] = useState<StudioTemplate[]>([])
  const [chosen, setChosen] = useState<number | null>(null)
  const [search, setSearch] = useState('')
  const [language, setLanguage] = useState('')
  const [error, setError] = useState<TranslationKey | null>(null)
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [dirty, setDirty] = useState(false)
  const [creating, setCreating] = useState(false)
  const [form, setForm] = useState({ code: '', document_type: 'TRANSFER_ISSUE', name_bg: '', name_en: '', name_ru: '' })
  const formDirty = creating && !!(form.code || form.name_bg || form.name_en || form.name_ru)
  useEffect(() => { onDirty(dirty || formDirty || busy); return () => onDirty(false) }, [dirty, formDirty, busy, onDirty])
  async function load() {
    try {
      const rows = await api<StudioTemplate[]>('/studio/templates')
      setTemplates(rows); setChosen(current => current ?? rows[0]?.id ?? null); setError(null)
    } catch (e) { setError(studioError(e)) } finally { setLoading(false) }
  }
  useEffect(() => { void load() }, [])

  async function create(event: FormEvent) {
    event.preventDefault(); setBusy(true)
    try {
      const result = await api<{ id: number }>('/studio/templates', { method: 'POST', body: JSON.stringify(form) })
      await load(); setChosen(result.id); setCreating(false); setForm({ code: '', document_type: 'TRANSFER_ISSUE', name_bg: '', name_en: '', name_ru: '' })
    } catch (e) { setError(studioError(e)) } finally { setBusy(false) }
  }
  const filtered = templates.filter(row => `${row.name_bg} ${row.name_en || ''} ${row.name_ru || ''} ${row.code}`.toLocaleLowerCase(locale).includes(search.toLocaleLowerCase(locale)) && (!language || row.versions.some(v => v.language === language)))
  const selected = templates.find(row => row.id === chosen)
  return <>
    {error && <p className="error" role="alert">{t(error)} <button className="secondary" onClick={() => void load()}>{t('studio.reload')}</button></p>}
    <div className="panel"><div className="panel-title"><h3>{t('studio.library')}</h3>{hasPermission('templates.manage') && <button className="secondary" onClick={() => { if ((!dirty && !formDirty) || window.confirm(t('studio.leave'))) { setCreating(value => !value); setForm({ code: '', document_type: 'TRANSFER_ISSUE', name_bg: '', name_en: '', name_ru: '' }) } }}>{t(creating ? 'studio.close' : 'studio.newTemplate')}</button>}</div>
      <div className="studio-fields"><label>{t('studio.search')}<input type="search" value={search} onChange={e => setSearch(e.target.value)} /></label><label>{t('admin.templateLanguage')}<select value={language} onChange={e => setLanguage(e.target.value)}><option value="">{t('studio.all')}</option>{(['bg', 'en', 'ru'] as const).map(lang => <option key={lang} value={lang}>{t(`language.${lang}`)}</option>)}</select></label></div>
      {creating && <form onSubmit={create}><fieldset disabled={busy} className="studio-fields"><label>{t('studio.code')}<input required maxLength={80} pattern="[A-Z0-9_-]+" value={form.code} onChange={e => setForm({ ...form, code: e.target.value.toUpperCase() })} /></label><label>{t('studio.type')}<select value={form.document_type} onChange={e => setForm({ ...form, document_type: e.target.value })}>{workflows.map(type => <option key={type} value={type}>{t(typeKey(type))}</option>)}</select></label>{(['bg', 'en', 'ru'] as const).map(lang => <label key={lang}>{t('studio.name')} · {t(`language.${lang}`)}<input required maxLength={255} value={form[`name_${lang}`]} onChange={e => setForm({ ...form, [`name_${lang}`]: e.target.value })} /></label>)}</fieldset><button className="primary" disabled={busy}>{t('studio.create')}</button></form>}
    </div>
    {loading ? <p role="status">{t('studio.loading')}</p> : <div className="studio-library-grid"><nav className="studio-template-list" aria-label={t('studio.library')}>{filtered.map(row => <button key={row.id} aria-current={chosen === row.id ? 'page' : undefined} onClick={() => { if (!dirty || window.confirm(t('studio.leave'))) setChosen(row.id) }}><b>{row[`name_${locale}`] || row.name_bg}</b><small>{t(typeKey(row.document_type))} · {row.code}</small></button>)}{!filtered.length && <p>{t('studio.empty')}</p>}</nav>{selected && <TemplateDetails key={selected.id} template={selected} reload={load} onDirty={setDirty} />}</div>}
  </>
}
