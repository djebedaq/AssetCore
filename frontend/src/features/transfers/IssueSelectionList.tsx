import { useI18n } from '../../i18n'
import type { TransferAvailability } from '../../types'

export function IssueSelectionList({ items, selected, onToggle }: {
  items: TransferAvailability[]
  selected: Set<number>
  onToggle: (item: TransferAvailability) => void
}) {
  const { t } = useI18n()
  if (!items.length) return <div className="empty-state">{t('bulk.noSearchMachines')}</div>
  return (
    <div className="selection-list">
      {items.map((item) => (
        <label
          key={item.machine_id}
          className={`selection-row ${item.available ? '' : 'unavailable'} ${selected.has(item.machine_id) ? 'selected' : ''}`}
        >
          <input
            type="checkbox"
            aria-label={t('bulk.machineAria', { number: item.machine_number })}
            checked={selected.has(item.machine_id)}
            disabled={!item.available}
            onChange={() => onToggle(item)}
          />
          <span className="selection-main">
            <strong>{t('bulk.machineName', { number: item.machine_number })}</strong>
            <small>{item.brand} · {item.pressure_bar} bar · {item.location || t('common.notSpecified')}</small>
          </span>
          <span className={`availability-pill ${item.available ? 'available' : 'blocked'}`}>
            {item.available ? t('bulk.available') : t('bulk.unavailable')}
          </span>
          {!item.available && <small className="unavailable-reason">{item.unavailable_reason || t('errors.issueConflict')}</small>}
        </label>
      ))}
    </div>
  )
}
