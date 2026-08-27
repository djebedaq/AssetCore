import { useEffect, useMemo, useState } from 'react'
import { Plus, Search } from 'lucide-react'
import { api } from '../../api'
import { statusText, useI18n } from '../../i18n'
import { hasPermission } from '../../permissions'
import type { AssetCategory, Department, Location, Machine } from '../../types'
import MachineModal from './MachineModal'
import { LazyMachinePassportModal as MachinePassportModal } from '../passport/LazyMachinePassportModal'

export default function Machines({ onOpenCatalog }: { onOpenCatalog: (machineId: number) => void }) {
  const { t } = useI18n()
  const [items, setItems] = useState<Machine[]>([])
  const [locations, setLocations] = useState<Location[]>([])
  const [departments, setDepartments] = useState<Department[]>([])
  const [categories, setCategories] = useState<AssetCategory[]>([])
  const [query, setQuery] = useState('')
  const [selected, setSelected] = useState<Machine | null>(null)
  const [showNew, setShowNew] = useState(false)
  const [passportId, setPassportId] = useState<number | null>(null)
  const [error, setError] = useState(false)
  const showTechnicalDetails = hasPermission('documents.view')

  const load = () => (showTechnicalDetails
    ? Promise.all([api<Machine[]>('/machines'), api<Location[]>('/locations'), api<AssetCategory[]>('/categories'), api<Department[]>('/departments')])
    : api<Machine[]>('/machines').then((machines) => [machines, [], [], []] as [Machine[], Location[], AssetCategory[], Department[]]))
    .then(([machines, locationItems, categoryItems, departmentItems]) => {
      setItems(machines)
      setLocations(locationItems)
      setCategories(categoryItems)
      setDepartments(departmentItems)
      setError(false)
    })
    .catch(() => setError(true))

  useEffect(() => { void load() }, [])

  const filtered = useMemo(() => items.filter((machine) => (
    `${machine.inventory_number} ${machine.name} ${machine.brand} ${machine.model || ''} ${statusText(t, machine.status)} ${machine.location?.name || ''}`
      .toLowerCase()
      .includes(query.toLowerCase())
  )), [items, query, t])

  return (
    <>
      <div className="toolbar">
        <div className="search">
          <Search size={18} />
          <input
            aria-label={t('common.search')}
            placeholder={t('machines.searchPlaceholder')}
            value={query}
            onChange={(event) => setQuery(event.target.value)}
          />
        </div>
        {hasPermission('assets.create') && (
          <button className="primary" onClick={() => setShowNew(true)}><Plus size={18} />{t('machines.new')}</button>
        )}
      </div>
      {error && <div className="error" role="alert">{t('errors.generic')}</div>}
      <div className="table-card">
        <table>
          <thead><tr>
            <th>{t('machines.columnMachine')}</th><th>{t('machines.columnBrand')}</th>
            {showTechnicalDetails && <th>{t('machines.columnPressure')}</th>}<th>{t('machines.columnStatus')}</th>
            <th>{t('machines.columnLocation')}</th><th />
          </tr></thead>
          <tbody>
            {filtered.map((machine) => (
              <tr key={machine.id}>
                <td><strong>{machine.name}</strong><small>{t('machines.inventoryPrefix', { number: machine.inventory_number })}</small></td>
                <td>{machine.brand}<small>{machine.model}</small></td>
                {showTechnicalDetails && <td>{machine.pressure_bar} bar</td>}
                <td><span className="badge">{statusText(t, machine.status)}</span></td>
                <td>{machine.location?.name || t('common.notSpecified')}</td>
                <td><button className="link" onClick={() => setPassportId(machine.id)}>{t('passport.tab.passport')}</button>{hasPermission('assets.edit') && <button className="link" onClick={() => setSelected(machine)}>{t('common.details')}</button>}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {!filtered.length && <div className="empty-state">{t('machines.empty')}</div>}
      </div>
      {selected && (
        <MachineModal
          machine={selected}
          locations={locations}
          departments={departments}
          categories={categories}
          onClose={() => setSelected(null)}
          onSaved={() => {
            setSelected(null)
            void load()
          }}
        />
      )}
      {showNew && (
        <MachineModal
          locations={locations}
          departments={departments}
          categories={categories}
          onClose={() => setShowNew(false)}
          onSaved={() => {
            setShowNew(false)
            void load()
          }}
        />
      )}
      {passportId && <MachinePassportModal machineId={passportId} onClose={() => setPassportId(null)} onOpenCatalog={() => { setPassportId(null); onOpenCatalog(passportId) }} />}
    </>
  )
}
