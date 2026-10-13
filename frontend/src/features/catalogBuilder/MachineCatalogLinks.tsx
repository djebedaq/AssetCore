import { useEffect, useState } from 'react'
import { api, ApiError } from '../../api'
import { useI18n } from '../../i18n'
import { builderBase, type Catalog } from './wizardTypes'
type Option = Catalog & { bound: boolean; compatibility: 'EXACT' | 'AMBIGUOUS' | 'INCOMPATIBLE'; assets: Array<{ id: number; inventory_number: string }> }

export default function MachineCatalogLinks({ machineId, onChanged }: { machineId: number; onChanged?: () => void }) {
  const { t, locale } = useI18n()
  const [options, setOptions] = useState<Option[]>([])
  const [confirmed, setConfirmed] = useState<number[]>([])
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  async function load() { setOptions(await api<Option[]>(`${builderBase}/machines/${machineId}/catalogs`)) }
  useEffect(() => { let active = true; setOptions([]); setConfirmed([])
    void api<Option[]>(`${builderBase}/machines/${machineId}/catalogs`).then(rows => { if (active) setOptions(rows) }).catch(() => { if (active) setError(t('guided.error')) })
    return () => { active = false }
  }, [machineId, t])
  async function change(row: Option) {
    setBusy(true); setError('')
    try {
      await api(`${builderBase}/catalogs/${row.id}/assets/${machineId}`, row.bound ? { method: 'DELETE' } : {
        method: 'POST', body: JSON.stringify({ compatibility_confirmed: confirmed.includes(row.id) }),
      })
      await load(); onChanged?.()
    } catch (caught) { setError(t(caught instanceof ApiError && caught.code === 'catalog_asset_model_mismatch' ? 'ux04.incompatible' : 'guided.error')) }
    finally { setBusy(false) }
  }
  return <section className="panel"><h4>{t('ux04.catalogs')}</h4><p>{t('ux04.bindingHelp')}</p>
    {error && <p className="error" role="alert">{error}</p>}
    {!options.length && <p>{t('builder.empty')}</p>}
    {options.map(row => <article className="builder-list-item" key={row.id}>
      <div><strong>{row[`name_${locale}`] || row.name_bg}</strong><p>{row.manufacturer} · {row.model_reference} · {row.asset_category[`name_${locale}`]}</p>
        <p>{t(row.published_revision ? 'wizard.current' : 'ux04.prepared')} {row.published_revision?.revision_code}</p>
        {!!row.assets.length && <p>{t('wizard.machines')}: {row.assets.map(asset => asset.inventory_number).join(', ')}</p>}
        {!row.bound && row.compatibility === 'AMBIGUOUS' && <label><input type="checkbox" checked={confirmed.includes(row.id)} onChange={event => setConfirmed(current => event.target.checked ? [...current, row.id] : current.filter(id => id !== row.id))} />{t('ux04.compatibility')}</label>}
        {!row.bound && row.compatibility === 'INCOMPATIBLE' && <p>{t('ux04.incompatible')}</p>}
      </div>
      <button className="secondary" disabled={busy || !row.bound && (row.compatibility === 'INCOMPATIBLE' || row.compatibility === 'AMBIGUOUS' && !confirmed.includes(row.id))}
        onClick={() => void change(row)}>{t(row.bound ? 'ux04.unlink' : 'ux04.link')}</button>
    </article>)}
  </section>
}
