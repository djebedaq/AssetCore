import type { AssetCategoryField } from '../../types'
import { useI18n } from '../../i18n'

type Props = {
  field: AssetCategoryField
  value: string
  onChange: (value: string) => void
  disabled?: boolean
}

export default function CategoryFieldControl({ field, value, onChange, disabled = false }: Props) {
  const { locale, t } = useI18n()
  const label = field[`label_${locale}` as 'label_bg'] || field.label_bg
  const rules = field.validation_rules || {}
  const numeric = field.field_type === 'INTEGER' || field.field_type === 'DECIMAL'
  const min = numeric && (typeof rules.min === 'number' || typeof rules.min === 'string')
    && Number.isFinite(Number(rules.min)) ? Number(rules.min) : undefined
  const max = numeric && (typeof rules.max === 'number' || typeof rules.max === 'string')
    && Number.isFinite(Number(rules.max)) ? Number(rules.max) : undefined
  const minLength = typeof rules.min_length === 'number' ? rules.min_length : undefined
  const maxLength = typeof rules.max_length === 'number' ? rules.max_length : undefined
  const pattern = typeof rules.pattern === 'string' && !rules.pattern.includes('(?')
    && !rules.pattern.includes('\\A') && !rules.pattern.includes('\\Z')
    ? rules.pattern : undefined
  let control
  if (field.field_type === 'BOOLEAN' || field.field_type === 'SELECT') {
    const options = field.field_type === 'BOOLEAN' ? [
      { value: 'true', label: t('common.yes') }, { value: 'false', label: t('common.no') },
    ] : (field.options || []).map(option => ({ value: option, label: option }))
    control = <select disabled={disabled} required={field.is_required} value={value} onChange={event => onChange(event.target.value)}>
      <option value="">{t('common.notSpecified')}</option>
      {options.map(option => <option value={option.value} key={option.value}>{option.label}</option>)}
    </select>
  } else {
    control = <input disabled={disabled} required={field.is_required}
      type={field.field_type === 'DATE' ? 'date' : numeric ? 'number' : 'text'}
      step={field.field_type === 'DECIMAL' ? 'any' : field.field_type === 'INTEGER' ? 1 : undefined}
      min={min} max={max} minLength={minLength} maxLength={maxLength} pattern={pattern}
      value={value} onChange={event => onChange(event.target.value)} />
  }
  return <label>{label}{field.unit ? ` (${field.unit})` : ''}{field.is_required ? <span aria-hidden="true"> *</span> : null}{control}</label>
}
