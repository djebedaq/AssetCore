import { useEffect, useState } from 'react'
import { api } from '../../api'
import AuthenticatedImage from '../../AuthenticatedImage'
import { useI18n } from '../../i18n'
import { Select } from '../../ui/Select'
import { MachineSelect } from '../../ui/workspace'
import type { CatalogPart } from '../catalog/catalogTypes'

type SourcePage = { id: number; page_number: number; role: string; preview_endpoint: string; sha256: string }
type Source = { source_id: string; revision: string; title: string; pages: SourcePage[] }
const BASE = '/admin/catalog-builder'

export default function ReferenceLinker({ onClose }: { onClose: () => void }) {
  const { t, locale } = useI18n()
  const [sources, setSources] = useState<Source[]>([])
  const [sourceKey, setSourceKey] = useState('')
  const [machineIds, setMachineIds] = useState<string[]>([])
  const [machineId, setMachineId] = useState('')
  const [schemeId, setSchemeId] = useState('')
  const [listId, setListId] = useState('')
  const [parts, setParts] = useState<CatalogPart[]>([])
  const [partIds, setPartIds] = useState<number[]>([])
  const [confirmed, setConfirmed] = useState(false)
  const [reason, setReason] = useState('')
  const [error, setError] = useState('')
  const [saved, setSaved] = useState(false)
  const [loading, setLoading] = useState(false)
  const source = sources.find(item => `${item.source_id}:${item.revision}` === sourceKey)
  const scheme = source?.pages.find(page => String(page.id) === schemeId)
  const list = source?.pages.find(page => String(page.id) === listId)
  useEffect(() => {
    let active = true
    void api<Source[]>(`${BASE}/reference-sources`).then(value => { if (active) setSources(value) }).catch(() => { if (active) setError(t('errors.generic')) })
    return () => { active = false }
  }, [t])
  useEffect(() => {
    let active = true
    setParts([]); setPartIds([]); setConfirmed(false); setSaved(false)
    if (!listId) return
    setLoading(true)
    void api<CatalogPart[]>(`${BASE}/reference-sources/${listId}/parts`).then(value => { if (active) { setParts(value); setError('') } }).catch(() => { if (active) setError(t('errors.generic')) }).finally(() => { if (active) setLoading(false) })
    return () => { active = false }
  }, [listId, t])
  async function save() {
    if (!source || loading || !confirmed) return
    setLoading(true); setError('')
    try {
      await api(`${BASE}/reference-associations`, { method: 'POST', body: JSON.stringify({ machine_ids: machineIds.map(Number), scheme_id: Number(schemeId), parts_list_id: Number(listId), source_revision: source.revision, part_ids: partIds, reason, compatibility_confirmed: confirmed }) })
      setSaved(true); setConfirmed(false)
    } catch { setError(t('ref.error')) }
    finally { setLoading(false) }
  }
  const pageOptions = (role: string) => (source?.pages || []).filter(page => page.role === role).map(page => ({ value: String(page.id), label: t('ref.page', { number: page.page_number }) }))
  return <section className="panel reference-linker" aria-label={t('ref.link')}>
    <div className="toolbar"><h3>{t('ref.link')}</h3><button className="secondary" disabled={loading} onClick={onClose}>{t('common.close')}</button></div>
    <p className="muted">{t('ref.warning')}</p>
    <div className="ac-filter-toolbar">
      <MachineSelect module="catalog" value={machineId} onChange={value => { setMachineId(value); setConfirmed(false) }} label={t('ref.target')} />
      <button className="secondary" disabled={!machineId || loading || machineIds.includes(machineId)} onClick={() => { setMachineIds(ids => [...ids, machineId]); setMachineId(''); setSaved(false); setConfirmed(false) }}>{t('ref.addMachine')}</button>
      <label className="ac-filter"><span>{t('ref.source')}</span><Select label={t('ref.source')} value={sourceKey} disabled={loading} onChange={value => { setSourceKey(value); setSchemeId(''); setListId(''); setConfirmed(false); setSaved(false) }} options={sources.map(item => ({ value: `${item.source_id}:${item.revision}`, label: `${item.title} · ${item.source_id} · ${item.revision}` }))} /></label>
      <label className="ac-filter"><span>{t('ref.scheme')}</span><Select label={t('ref.scheme')} value={schemeId} disabled={loading || !source} onChange={value => { setSchemeId(value); setConfirmed(false); setSaved(false) }} options={pageOptions('EXPLODED_SCHEME')} /></label>
      <label className="ac-filter"><span>{t('ref.list')}</span><Select label={t('ref.list')} value={listId} disabled={loading || !source} onChange={setListId} options={pageOptions('SPARE_PARTS_LIST')} /></label>
    </div>
    <div className="actions reference-targets">{machineIds.map(id => <ReferenceTarget key={id} id={id} onRemove={() => { setMachineIds(ids => ids.filter(value => value !== id)); setConfirmed(false); setSaved(false) }} disabled={loading} />)}</div>
    <div className="reference-previews">{scheme && <figure><figcaption>{t('ref.scheme')} · {t('ref.page', { number: scheme.page_number })}</figcaption><AuthenticatedImage src={scheme.preview_endpoint} alt={t('ref.scheme')} /></figure>}{list && <figure><figcaption>{t('ref.list')} · {t('ref.page', { number: list.page_number })}</figcaption><AuthenticatedImage src={list.preview_endpoint} alt={t('ref.list')} /></figure>}</div>
    {parts.length > 0 && <div className="table-card reference-parts"><table><thead><tr><th>{t('ref.applicable')}</th><th>{t('ref.position')}</th><th>{t('ref.partNumber')}</th><th>{t('ref.variant')}</th></tr></thead><tbody>{parts.map(part => <tr key={part.id}><td><input aria-label={`${part.position} · ${part.part_number}`} type="checkbox" disabled={loading} checked={partIds.includes(part.id)} onChange={event => { setPartIds(ids => event.target.checked ? [...ids, part.id] : ids.filter(id => id !== part.id)); setConfirmed(false); setSaved(false) }} /></td><td>{part.position}</td><td>{part.part_number}<small>{part[`description_${locale}`] || part.description}</small></td><td>{part.valid_for_raw || '—'}<small>{part.replaced_by_part_number || part.alternative_part_number || ''}</small></td></tr>)}</tbody></table></div>}
    <label className="reference-reason">{t('ref.reason')}<textarea value={reason} disabled={loading} onChange={event => { setReason(event.target.value); setConfirmed(false); setSaved(false) }} maxLength={4000} /></label>
    <label className="reference-confirm"><input type="checkbox" disabled={loading || !scheme || !list || !partIds.length || !machineIds.length} checked={confirmed} onChange={event => setConfirmed(event.target.checked)} />{t('ref.confirm')}</label>
    <p>{t('ref.selection', { machines: machineIds.length, parts: partIds.length })}</p>
    {error && <div className="error" role="alert">{error}</div>}{saved && <p role="status">{t('ref.saved')}</p>}
    <button className="primary" disabled={loading || saved || !confirmed || reason.trim().length < 3} onClick={() => { void save() }}>{t('common.save')}</button>
  </section>
}

function ReferenceTarget({ id, onRemove, disabled }: { id: string; onRemove: () => void; disabled: boolean }) {
  const { t } = useI18n()
  const [label, setLabel] = useState('')
  useEffect(() => { let active = true; void api<{ name: string; inventory_number: string }>(`/machines/${id}`).then(machine => { if (active) setLabel(`${machine.name} · №${machine.inventory_number}`) }).catch(() => undefined); return () => { active = false } }, [id])
  return <button className="secondary compact" disabled={disabled} onClick={onRemove}>{label || t('common.loading')} ×</button>
}
