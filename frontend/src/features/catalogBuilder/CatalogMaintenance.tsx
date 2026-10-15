import { useEffect, useState, type FormEvent } from 'react'
import { api } from '../../api'
import { useI18n } from '../../i18n'
import { OwnerDeleteButton } from '../administration/OwnerDeleteButton'
import RevisionVisualSources from './RevisionVisualSources'
import useDraftGuard from './useDraftGuard'
import { guidedError } from './guidedErrors'
import { builderBase, type Catalog, type Category, type Revision } from './wizardTypes'

type Definition = Catalog & { description: string | null }
type Asset = { id: number; inventory_number: string; name: string }

// Catalog administration is scoped to the selected definition. Creation,
// extraction, review and publication have a single guided workspace.
export default function CatalogMaintenance({ catalogId, onChanged, onDirtyChange, onManageBindings }: {
  catalogId: number; onChanged: () => Promise<void>; onDirtyChange: (dirty: boolean) => void; onManageBindings?: () => void
}) {
  const { t, locale, date } = useI18n()
  const [item, setItem] = useState<Definition | null>(null)
  const [categories, setCategories] = useState<Category[]>([])
  const [revisions, setRevisions] = useState<Array<Revision & { change_note?: string | null }>>([])
  const [assets, setAssets] = useState<Asset[]>([])
  const [editing, setEditing] = useState(false)
  const [revisionEdit, setRevisionEdit] = useState<Revision | 'new' | null>(null)
  const [clone, setClone] = useState(false)
  const [code, setCode] = useState('')
  const [note, setNote] = useState('')
  const [legacyId, setLegacyId] = useState<number | null>(null)
  const [childDirty, setChildDirty] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  useDraftGuard(editing || !!revisionEdit || busy || childDirty, onDirtyChange)
  async function load() {
    const [rows, options, versions, machines] = await Promise.all([
      api<Definition[]>(`${builderBase}/catalogs`), api<Category[]>('/categories'),
      api<typeof revisions>(`${builderBase}/catalogs/${catalogId}/revisions`),
      api<Asset[]>(`${builderBase}/catalogs/${catalogId}/assets`),
    ])
    setItem(rows.find(row => row.id === catalogId) || null); setRevisions(versions); setAssets(machines)
    setCategories(options.filter(row => row.capabilities.includes('HAS_PARTS_CATALOG')))
  }
  useEffect(() => { void load().catch(caught => setError(t(guidedError(caught)))) }, [catalogId])
  async function action(work: () => Promise<unknown>) {
    if (busy) return
    setBusy(true); setError('')
    try { await work(); setEditing(false); setRevisionEdit(null); await load(); await onChanged() }
    catch (caught) { setError(t(guidedError(caught))) } finally { setBusy(false) }
  }
  function save(event: FormEvent) {
    event.preventDefault()
    if (!item) return
    const { name_bg, name_en, name_ru, description, manufacturer, model_reference, asset_category_id } = item
    void action(() => api(`${builderBase}/catalogs/${catalogId}`, { method: 'PATCH', body: JSON.stringify({ name_bg, name_en, name_ru, description, manufacturer, model_reference, asset_category_id }) }))
  }
  if (!item) return error ? <p role="alert">{error}</p> : <p role="status">{t('wizard.loading')}</p>
  return <div className="catalog-maintenance">
    {error && <p role="alert" className="error">{error}</p>}
    <p>{item.code} · {t(item.is_active ? 'builder.active' : 'builder.inactive')}</p>
    {!editing ? <button className="secondary" onClick={() => setEditing(true)}>{t('wizard.editMetadata')}</button> : <form className="form-grid" onSubmit={save}>
      {(['bg', 'en', 'ru'] as const).map(language => <label key={language}>{t(`builder.name.${language}`)}<input required disabled={busy} maxLength={255} value={item[`name_${language}`]} onChange={event => setItem({ ...item, [`name_${language}`]: event.target.value })} /></label>)}
      <label>{t('builder.category')}<select disabled={busy} value={item.asset_category_id} onChange={event => setItem({ ...item, asset_category_id: Number(event.target.value) })}>{categories.filter(row => row.is_active || row.id === item.asset_category_id).map(row => <option value={row.id} key={row.id}>{row[`name_${locale}`]}</option>)}</select></label>
      {(['manufacturer', 'model_reference', 'description'] as const).map(key => <label key={key}>{t(key === 'model_reference' ? 'builder.modelReference' : `builder.${key}`)}<input disabled={busy} value={item[key] || ''} onChange={event => setItem({ ...item, [key]: event.target.value || null })} /></label>)}
      <button className="primary" disabled={busy}>{t('common.save')}</button>
      <button type="button" className="secondary" disabled={busy} onClick={() => { setEditing(false); void load() }}>{t('common.cancel')}</button>
    </form>}
    <details><summary>{t('wizard.history')}</summary>
      <button className="secondary" disabled={busy || !item.is_active} onClick={() => { setRevisionEdit('new'); setClone(false); setCode(''); setNote('') }}>{t('builder.createRevision')}</button>
      {revisions.map(row => <article key={row.id}><p><b>{row.revision_code}</b> · {t(`builder.status.${row.status}`)} · {date(row.created_at)} · {row.change_note}</p>
        {row.status === 'DRAFT' && <button className="secondary" disabled={busy} onClick={() => { setRevisionEdit(row); setClone(false); setCode(row.revision_code); setNote(row.change_note || '') }}>{t('builder.editRevision')}</button>}
        {row.status === 'PUBLISHED' && <button className="secondary" disabled={busy} onClick={() => { setRevisionEdit(row); setClone(true); setCode(''); setNote('') }}>{t('builder.publication.clone')}</button>}
      </article>)}
      {revisionEdit && <form className="form-grid" onSubmit={event => {
        event.preventDefault()
        const path = clone && revisionEdit !== 'new' ? `/revisions/${revisionEdit.id}/clone` : revisionEdit === 'new' ? `/catalogs/${catalogId}/revisions` : `/revisions/${revisionEdit.id}`
        void action(() => api(builderBase + path, { method: clone || revisionEdit === 'new' ? 'POST' : 'PATCH', body: JSON.stringify({ ...(clone || revisionEdit === 'new' ? { revision_code: code } : {}), change_note: note || null }) }))
      }}>
        <label>{t('builder.revisionCode')}<input required disabled={busy} readOnly={!clone && revisionEdit !== 'new'} value={code} onChange={event => setCode(event.target.value)} /></label>
        <label>{t('builder.changeNote')}<textarea disabled={busy} value={note} onChange={event => setNote(event.target.value)} /></label>
        <button className="primary" disabled={busy}>{t('common.save')}</button><button type="button" className="secondary" onClick={() => setRevisionEdit(null)}>{t('common.cancel')}</button>
      </form>}
    </details>
    <section><p>{t('ux06.boundCount', { count: item.active_asset_count || 0 })}</p>
      {!!item.pending_asset_count && <p>{t('ux06.pendingCount', { count: item.pending_asset_count })}</p>}
      {assets.map(asset => <p key={asset.id}>{asset.inventory_number} · {asset.name}</p>)}
      {onManageBindings && <button className="secondary" disabled={busy || editing || !!revisionEdit || childDirty} onClick={onManageBindings}>{t('ux06.title')}</button>}
    </section>
    <details><summary>{t('catalogUx.sourceTools')}</summary><label>{t('catalogUx.revision')}<select disabled={busy || childDirty} value={legacyId || ''} onChange={event => setLegacyId(Number(event.target.value) || null)}><option value="">{t('guided.select')}</option>{revisions.map(row => <option value={row.id} key={row.id}>{row.revision_code} · {t(`builder.status.${row.status}`)}</option>)}</select></label>
      {legacyId && <RevisionVisualSources revisionId={legacyId} editable={revisions.find(row => row.id === legacyId)?.status === 'DRAFT'} onDirtyChange={setChildDirty} />}
    </details>
    <details><summary>{t('builder.active')}</summary><button className="secondary" disabled={busy} onClick={() => {
      if (window.confirm(t(item.is_active ? 'builder.deactivateConfirm' : 'builder.activateConfirm'))) void action(() => api(`${builderBase}/catalogs/${catalogId}`, { method: 'PATCH', body: JSON.stringify({ is_active: !item.is_active }) }))
    }}>{t(item.is_active ? 'admin.deactivate' : 'admin.activate')}</button>
      <OwnerDeleteButton resource="catalog_definition" resourceId={catalogId} identity={item.code} onDeleted={onChanged} />
    </details>
  </div>
}
