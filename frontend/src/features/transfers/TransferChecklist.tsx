import { useI18n, type TranslationKey } from '../../i18n'
import { LENGTH_CODES, type ChecklistCondition, type ChecklistItem } from './transferState'

export function ConditionChecklist({ items, onChange }: { items: ChecklistItem[]; onChange: (items: ChecklistItem[]) => void }) {
  const { t } = useI18n()
  const conditions: ChecklistCondition[] = ['GOOD', 'SATISFACTORY', 'REPAIR', 'FAULTY', 'MISSING', 'NA']
  const update = (index: number, patch: Partial<ChecklistItem>) => onChange(items.map((item, itemIndex) => itemIndex === index ? { ...item, ...patch } : item))
  return <fieldset className="wide condition-checklist"><legend>{t('bulk.checklist.title')}</legend>{items.map((item, index) => <div className="checklist-row" key={item.code}><strong>{t(`bulk.checklist.item.${item.code}` as TranslationKey)}</strong><select value={item.condition} onChange={(event) => update(index, { condition: event.target.value as ChecklistCondition })}>{conditions.map((value) => <option key={value} value={value}>{t(`bulk.checklist.condition.${value}` as TranslationKey)}</option>)}</select>{LENGTH_CODES.has(item.code) && <input type="number" min="0" step="0.1" placeholder={t('bulk.checklist.lengthPlaceholder')} value={item.length_m} onChange={(event) => update(index, { length_m: event.target.value })} />}<input placeholder={t('bulk.checklist.notePlaceholder')} value={item.note} onChange={(event) => update(index, { note: event.target.value })} /></div>)}</fieldset>
}
