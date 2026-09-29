import { useEffect, useState, type FormEvent } from 'react'
import { api, ApiError } from '../../api'
import { Modal } from '../../industrialUi'
import { useI18n, type TranslationKey } from '../../i18n'
import RevisionHotspotEditor from './RevisionHotspotEditor'

type Part = { id: number; position: string; part_number: string; name_bg: string | null; name_en: string | null;
  name_ru: string | null; description: string | null; validation_status: 'READY' | 'INCOMPLETE' }
type Page = { visual_page_id: number; artifact_title: string; filename: string; page_number: number }
type Component = { id: number; part_id: number; quantity: number; quantity_raw: string | null; is_optional: boolean;
  note: string | null; sort_order: number; version: number; part: Part }
type Kit = { id: number; code: string; name_bg: string | null; name_en: string | null; name_ru: string | null;
  description: string | null; source_visual_page_id: number | null; sort_order: number; version: number;
  validation_status: 'READY' | 'INCOMPLETE'; incomplete_part_ids: number[]; components: Component[]; component_count: number;
  code_locked: boolean }
type KitForm = { code: string; name_bg: string; name_en: string; name_ru: string; description: string;
  source_visual_page_id: string; sort_order: number }
const blank: KitForm = { code: '', name_bg: '', name_en: '', name_ru: '', description: '', source_visual_page_id: '', sort_order: 0 }
const errorKeys: Record<string, TranslationKey> = {
  catalog_repair_kit_duplicate: 'builder.kit.error.duplicate',
  catalog_repair_kit_code_immutable: 'builder.kit.error.immutable',
  catalog_repair_kit_component_duplicate: 'builder.kit.error.componentDuplicate',
  catalog_repair_kit_component_invalid: 'builder.kit.error.component',
  catalog_repair_kit_cross_assembly: 'builder.kit.error.component',
  catalog_repair_kit_source_page_invalid: 'builder.kit.error.source',
  catalog_repair_kit_stale: 'builder.kit.error.stale',
  catalog_repair_kit_invalid: 'builder.kit.error.invalid',
  catalog_revision_not_draft: 'builder.error.revisionImmutable',
  catalog_inactive: 'builder.error.inactive',
}

export default function RevisionRepairKits({ assemblyId, editable }: { assemblyId: number; editable: boolean }) {
  const { locale, t } = useI18n()
  const [kits, setKits] = useState<Kit[]>([])
  const [parts, setParts] = useState<Part[]>([])
  const [pages, setPages] = useState<Page[]>([])
  const [selectedId, setSelectedId] = useState<number | null>(null)
  const [editing, setEditing] = useState<Kit | 'new' | null>(null)
  const [form, setForm] = useState<KitForm>(blank)
  const [partSearch, setPartSearch] = useState('')
  const [addPartId, setAddPartId] = useState('')
  const [quantity, setQuantity] = useState('1')
  const [optional, setOptional] = useState(false)
  const [note, setNote] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const selected = kits.find(item => item.id === selectedId)
  const name = (item: { name_bg: string | null; name_en: string | null; name_ru: string | null; description?: string | null }) =>
    item[`name_${locale}`] || item.name_bg || item.name_en || item.name_ru || item.description || ''
  const message = (caught: unknown) => t(caught instanceof ApiError && caught.code && errorKeys[caught.code]
    ? errorKeys[caught.code] : 'builder.error.generic')
  async function load() {
    const [kitRows, partRows, pageRows] = await Promise.all([
      api<Kit[]>(`/admin/catalog-builder/assemblies/${assemblyId}/repair-kits`),
      api<Part[]>(`/admin/catalog-builder/assemblies/${assemblyId}/parts`),
      api<Page[]>(`/admin/catalog-builder/assemblies/${assemblyId}/spare-list-pages`),
    ])
    setKits(kitRows); setParts(partRows); setPages(pageRows)
  }
  useEffect(() => { setSelectedId(null); void load().catch(caught => setError(message(caught))) }, [assemblyId])
  function openForm(item: Kit | 'new') {
    setEditing(item)
    setForm(item === 'new' ? blank : { code: item.code, name_bg: item.name_bg || '', name_en: item.name_en || '',
      name_ru: item.name_ru || '', description: item.description || '',
      source_visual_page_id: String(item.source_visual_page_id || ''), sort_order: item.sort_order })
  }
  async function save(event: FormEvent) {
    event.preventDefault()
    if (!editing || busy) return
    setBusy(true)
    try {
      const payload = { ...form, source_visual_page_id: form.source_visual_page_id ? Number(form.source_visual_page_id) : null }
      const created = editing === 'new'
        ? await api<Kit>(`/admin/catalog-builder/assemblies/${assemblyId}/repair-kits`,
          { method: 'POST', body: JSON.stringify(payload) })
        : await api<Kit>(`/admin/catalog-builder/repair-kits/${editing.id}`,
          { method: 'PATCH', body: JSON.stringify({ ...payload, expected_version: editing.version }) })
      setEditing(null); setSelectedId(created.id); setError(''); await load()
    } catch (caught) { setError(message(caught)); setEditing(null); await load() } finally { setBusy(false) }
  }
  async function remove(kit: Kit) {
    if (!window.confirm(t('builder.kit.deleteConfirm', { code: kit.code }))) return
    try {
      await api(`/admin/catalog-builder/repair-kits/${kit.id}?expected_version=${kit.version}`, { method: 'DELETE' })
      if (selectedId === kit.id) setSelectedId(null)
      setError(''); await load()
    } catch (caught) { setError(message(caught)); await load() }
  }
  async function addComponent(event: FormEvent) {
    event.preventDefault()
    if (!selected || !addPartId || busy) return
    setBusy(true)
    try {
      await api(`/admin/catalog-builder/repair-kits/${selected.id}/components`, { method: 'POST',
        body: JSON.stringify({ part_id: Number(addPartId), quantity: Number(quantity), is_optional: optional, note: note || null }) })
      setAddPartId(''); setQuantity('1'); setOptional(false); setNote(''); setError(''); await load()
    } catch (caught) { setError(message(caught)); await load() } finally { setBusy(false) }
  }
  async function updateComponent(component: Component, patch: Record<string, unknown>) {
    try {
      await api(`/admin/catalog-builder/repair-kit-components/${component.id}`, { method: 'PATCH',
        body: JSON.stringify({ ...patch, expected_version: component.version }) })
      setError(''); await load()
    } catch (caught) { setError(message(caught)); await load() }
  }
  async function removeComponent(component: Component) {
    if (!window.confirm(t('builder.kit.removeComponentConfirm'))) return
    try {
      await api(`/admin/catalog-builder/repair-kit-components/${component.id}?expected_version=${component.version}`,
        { method: 'DELETE' })
      setError(''); await load()
    } catch (caught) { setError(message(caught)); await load() }
  }
  const available = selected ? parts.filter(part => !selected.components.some(item => item.part_id === part.id) &&
    [part.position, part.part_number, name(part)].some(value => value.toLocaleLowerCase().includes(partSearch.toLocaleLowerCase()))) : []
  const highlighted = selected?.components.map(item => item.part.position) || []
  return <div className="builder-workspace">
    {error && <p className="error" role="alert">{error}</p>}
    {editable && <div className="actions"><button className="primary compact" onClick={() => openForm('new')}>{t('builder.kit.add')}</button></div>}
    {!kits.length && <p>{t('builder.kit.empty')}</p>}
    {kits.map(kit => <div key={kit.id} className="builder-row"><span><b>{kit.code}</b> · {name(kit)}
      <small>{t('builder.kit.componentCount', { count: kit.component_count })} · {t(kit.validation_status === 'READY' ? 'builder.kit.ready' : 'builder.kit.incomplete')}</small></span>
      <div className="actions"><button className="secondary compact" onClick={() => setSelectedId(kit.id)}>{t('builder.open')}</button>
        {editable && <><button className="secondary compact" onClick={() => openForm(kit)}>{t('common.edit')}</button>
          <button className="secondary compact" onClick={() => void remove(kit)}>{t('common.remove')}</button></>}</div></div>)}
    {selected && <section className="panel"><div className="panel-title"><h4>{selected.code} · {name(selected)}</h4>
      <button className="secondary compact" onClick={() => setSelectedId(null)}>{t('common.close')}</button></div>
      <p>{t(selected.validation_status === 'READY' ? 'builder.kit.ready' : 'builder.kit.incomplete')}</p>
      {selected.incomplete_part_ids.length > 0 && <p>{t('builder.kit.incompleteParts', { count: selected.incomplete_part_ids.length })}</p>}
      <div className="builder-parts-table"><table><thead><tr><th>{t('builder.part.position')}</th><th>{t('builder.part.partNumber')}</th>
        <th>{t('builder.part.name')}</th><th>{t('builder.kit.quantity')}</th><th>{t('builder.kit.optional')}</th><th>{t('builder.kit.note')}</th>
        <th>{t('builder.part.actions')}</th></tr></thead><tbody>{selected.components.map(component => <tr key={component.id}>
        <td>{component.part.position}</td><td>{component.part.part_number}</td><td>{name(component.part)}</td>
        <td>{editable ? <input type="number" min="0.0001" step="0.0001" defaultValue={component.quantity}
          key={`quantity-${component.id}-${component.version}`} aria-label={t('builder.kit.quantity')}
          onBlur={event => { const value = Number(event.target.value); if (value > 0 && value !== Number(component.quantity))
            void updateComponent(component, { quantity: value }) }} /> : component.quantity}</td>
        <td>{editable ? <input type="checkbox" checked={component.is_optional}
          onChange={event => void updateComponent(component, { is_optional: event.target.checked })} /> :
          t(component.is_optional ? 'common.yes' : 'common.no')}</td>
        <td>{editable ? <input defaultValue={component.note || ''} key={`note-${component.id}-${component.version}`}
          aria-label={t('builder.kit.note')} onBlur={event => { if (event.target.value !== (component.note || ''))
            void updateComponent(component, { note: event.target.value || null }) }} /> : component.note}</td>
        <td>{editable && <button className="secondary compact" onClick={() => void removeComponent(component)}>{t('common.remove')}</button>}</td>
      </tr>)}</tbody></table></div>
      {editable && <form className="form-grid" onSubmit={event => void addComponent(event)}>
        <label>{t('builder.kit.searchPart')}<input value={partSearch} onChange={event => setPartSearch(event.target.value)} /></label>
        <label>{t('builder.kit.part')}<select required value={addPartId} onChange={event => setAddPartId(event.target.value)}>
          <option value="">{t('builder.kit.choosePart')}</option>
          {available.map(part => <option key={part.id} value={part.id}>{part.position} · {part.part_number} · {name(part)}</option>)}</select></label>
        <label>{t('builder.kit.quantity')}<input type="number" min="0.0001" step="0.0001" required value={quantity}
          onChange={event => setQuantity(event.target.value)} /></label>
        <label>{t('builder.kit.optional')}<input type="checkbox" checked={optional} onChange={event => setOptional(event.target.checked)} /></label>
        <label>{t('builder.kit.note')}<input value={note} onChange={event => setNote(event.target.value)} /></label>
        <div className="actions wide"><button className="primary compact" disabled={busy || !addPartId}>{t('builder.kit.addComponent')}</button></div>
      </form>}
      <h4>{t('builder.kit.preview')}</h4>
      <RevisionHotspotEditor assemblyId={assemblyId} editable={false} highlightPositions={highlighted} />
    </section>}
    {editing && <Modal title={t(editing === 'new' ? 'builder.kit.add' : 'builder.kit.edit')} onClose={() => setEditing(null)} wide>
      <form className="form-grid" onSubmit={event => void save(event)}>
        <label>{t('builder.code')}<input required pattern="[A-Z][A-Z0-9_]*" maxLength={120}
          readOnly={editing !== 'new' && editing.code_locked} value={form.code}
          onChange={event => setForm({ ...form, code: event.target.value.toUpperCase() })} /></label>
        {(['bg', 'en', 'ru'] as const).map(language => <label key={language}>{t(`builder.name.${language}`)}
          <input value={form[`name_${language}`]} onChange={event => setForm({ ...form, [`name_${language}`]: event.target.value })} /></label>)}
        <label className="wide">{t('builder.description')}<textarea value={form.description}
          onChange={event => setForm({ ...form, description: event.target.value })} /></label>
        <label>{t('builder.kit.sourcePage')}<select value={form.source_visual_page_id}
          onChange={event => setForm({ ...form, source_visual_page_id: event.target.value })}>
          <option value="">{t('builder.kit.noSource')}</option>
          {pages.map(page => <option key={page.visual_page_id} value={page.visual_page_id}>
            {page.artifact_title} · {t('builder.pageNumber', { count: page.page_number })} · {page.filename}</option>)}</select></label>
        <label>{t('builder.sortOrder')}<input type="number" value={form.sort_order}
          onChange={event => setForm({ ...form, sort_order: Number(event.target.value) })} /></label>
        <p className="wide muted">{t('builder.kit.nameRule')}</p>
        <div className="actions wide"><button type="button" className="secondary" onClick={() => setEditing(null)}>{t('common.cancel')}</button>
          <button className="primary" disabled={busy}>{t('common.save')}</button></div>
      </form></Modal>}
  </div>
}
