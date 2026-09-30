import { useEffect, useState } from 'react'
import { api, ApiError } from '../../api'
import { useI18n } from '../../i18n'
import { builderBase, problemKeys } from './wizardTypes'

type Machine = { id: number; inventory_number: string; name: string; brand: string; model: string | null }
export default function WizardMachines({ catalogId, onChanged }: { catalogId: number; onChanged: () => Promise<void> }) {
  const { t } = useI18n()
  const [bound, setBound] = useState<Machine[]>([])
  const [eligible, setEligible] = useState<Machine[]>([])
  const [search, setSearch] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const report = (caught: unknown) => setError(t(caught instanceof ApiError && caught.code ? problemKeys[caught.code] || 'builder.error.generic' : 'builder.error.generic'))
  useEffect(() => {
    let active = true
    void api<Machine[]>(`${builderBase}/catalogs/${catalogId}/assets`).then(rows => { if (active) setBound(rows) }).catch(report)
    return () => { active = false }
  }, [catalogId])
  useEffect(() => {
    let active = true
    const timer = window.setTimeout(() => void api<Machine[]>(`${builderBase}/catalogs/${catalogId}/eligible-assets?search=${encodeURIComponent(search)}`)
      .then(rows => { if (active) setEligible(rows) }).catch(report), 200)
    return () => { active = false; window.clearTimeout(timer) }
  }, [catalogId, search])
  async function bind(machine: Machine) {
    if (busy) return
    setBusy(true); setError('')
    try {
      await api(`${builderBase}/catalogs/${catalogId}/assets/${machine.id}`, { method: 'POST' })
      setBound(rows => [...rows, machine]); setEligible(rows => rows.filter(row => row.id !== machine.id))
      await onChanged()
    } catch (caught) { report(caught) } finally { setBusy(false) }
  }
  return <section className="panel"><h4>{t('wizard.machines')}</h4><p>{t('wizard.machineHelp')}</p>
    {error && <p className="error" role="alert">{error}</p>}
    {!bound.length && <p>{t('builder.noAssets')}</p>}
    {bound.map(machine => <p key={machine.id}><b>{machine.inventory_number}</b> · {machine.name} · {machine.brand} {machine.model}</p>)}
    <label>{t('wizard.machineSearch')}<input value={search} onChange={event => setSearch(event.target.value)} /></label>
    {!eligible.length && <p>{t('builder.noEligible')}</p>}
    {eligible.map(machine => <div className="builder-row" key={machine.id}><span><b>{machine.inventory_number}</b> · {machine.name} · {machine.brand} {machine.model}</span>
      <button className="secondary" disabled={busy} onClick={() => void bind(machine)}>{t('builder.addAsset')}</button></div>)}
  </section>
}
