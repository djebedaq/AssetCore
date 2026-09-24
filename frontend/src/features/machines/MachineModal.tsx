import { type FormEvent, useEffect, useState } from 'react'
import { X } from 'lucide-react'
import { ApiError, api } from '../../api'
import AuthenticatedImage from '../../AuthenticatedImage'
import { statusText, useI18n } from '../../i18n'
import { hasPermission } from '../../permissions'
import type { AssetCategoryField, Department, Location, Machine, RegistryCategory } from '../../types'
import CategoryFieldControl from './CategoryFieldControl'

type FormDefinition = { id: number; capabilities: string[]; fields: AssetCategoryField[] }
type FormData = { category: FormDefinition; values: Array<{ field_id: number; value: string | null }> }

type FormCategory = Omit<RegistryCategory, 'asset_count' | 'has_pressure'> & {
  asset_count?: number; has_pressure?: boolean; capabilities?: string[]
}

const supportsPressure = (category?: FormCategory) => category?.has_pressure ?? category?.capabilities?.includes('HAS_PRESSURE') ?? false

const MACHINE_STATUS_CODES = [
  'READY',
  'ISSUED',
  'REPAIR',
]

type MachineForm = {
  inventory_number: string
  name: string
  brand: string
  model: string
  serial_number: string
  pressure_bar: number | ''
  status: string
  location_id: number | ''
  notes: string
  category_id: number | ''
  asset_type: string
  subtype: string
  manufacturer: string
  manufacture_year: number | ''
  commissioning_date: string
  ownership: string
  department: string
  responsible_person: string
  capacity: string
  dimensions: string
  is_active: boolean
}

export default function MachineModal({ machine, initialCategoryId, locations, departments, categories, onClose, onSaved }: {
  machine?: Machine
  initialCategoryId?: number
  locations: Location[]
  departments: Department[]
  categories: FormCategory[]
  onClose: () => void
  onSaved: () => void
}) {
  const { locale, t } = useI18n()
  const [form, setForm] = useState<MachineForm>({
    inventory_number: machine?.inventory_number || '',
    name: machine?.name || '',
    brand: machine?.brand || '',
    model: machine?.model || '',
    serial_number: machine?.serial_number || '',
    pressure_bar: machine?.pressure_bar ?? '',
    status: machine?.status || 'READY',
    location_id: machine?.location_id || locations.find((item) => item.is_active)?.id || '',
    notes: machine?.notes || '',
    category_id: machine?.category_id || categories.find((item) => item.code === machine?.category)?.id || initialCategoryId || '',
    asset_type: machine?.asset_type || '',
    subtype: machine?.subtype || '',
    manufacturer: machine?.manufacturer || '',
    manufacture_year: machine?.manufacture_year || '',
    commissioning_date: machine?.commissioning_date?.slice(0, 10) || '',
    ownership: machine?.ownership || '',
    department: machine?.department || '',
    responsible_person: machine?.responsible_person || '',
    capacity: machine?.capacity || '',
    dimensions: machine?.dimensions || '',
    is_active: machine?.is_active ?? true,
  })
  const [error, setError] = useState('')
  const [definition, setDefinition] = useState<FormDefinition | null>(null)
  const [customValues, setCustomValues] = useState<Record<number, string>>({})
  const [loadingFields, setLoadingFields] = useState(false)
  const canEdit = !machine ? hasPermission('assets.create') : hasPermission('assets.edit')
  const selectedCategory = categories.find((item) => item.id === form.category_id)
  const hasPressure = definition?.id === form.category_id
    ? definition.capabilities.includes('HAS_PRESSURE') : supportsPressure(selectedCategory)

  useEffect(() => {
    if (!form.category_id) { setDefinition(null); setCustomValues({}); return }
    let cancelled = false
    setLoadingFields(true)
    setDefinition(null)
    const request = machine
      ? api<FormData>(`/machines/${machine.id}/form-data?category_id=${form.category_id}`)
      : api<FormDefinition>(`/asset-categories/${form.category_id}/form-definition`)
    void request.then(result => {
      if (cancelled) return
      if ('category' in result) {
        setDefinition(result.category)
        setCustomValues(Object.fromEntries(result.values.map(item => [item.field_id, item.value || ''])))
      } else {
        setDefinition(result)
        setCustomValues({})
      }
      setError('')
    }).catch(() => { if (!cancelled) setError(t('machines.formLoadError')) })
      .finally(() => { if (!cancelled) setLoadingFields(false) })
    return () => { cancelled = true }
  }, [form.category_id, machine, t])

  async function save(event: FormEvent) {
    event.preventDefault()
    if (loadingFields || !definition || definition.id !== form.category_id) return
    setError('')
    try {
      const { pressure_bar, ...identity } = form
      const includePressure = !machine || hasPressure || form.category_id !== machine.category_id
      await api(machine ? `/machines/${machine.id}` : '/machines', {
        method: machine ? 'PATCH' : 'POST',
        body: JSON.stringify({ ...identity, category_id: form.category_id || null, custom_fields: definition.fields.map(field => ({ field_id: field.id, value: customValues[field.id] || null })), ...(includePressure ? { pressure_bar: hasPressure && pressure_bar !== '' ? pressure_bar : null } : {}), location_id: form.location_id || null, manufacture_year: form.manufacture_year || null, commissioning_date: form.commissioning_date || null }),
      })
      onSaved()
    } catch (caught) {
      if (caught instanceof ApiError && typeof caught.data.field_id === 'number') {
        const affected = definition.fields.find(field => field.id === caught.data.field_id)
        const label = affected?.[`label_${locale}` as 'label_bg'] || affected?.label_bg
        const reason = caught.code === 'required_custom_field' ? t('machines.requiredField') : t('machines.invalidField')
        setError(label ? `${label}: ${reason}` : reason)
      } else if (caught instanceof ApiError && caught.code === 'field_category_mismatch') {
        setError(t('machines.categoryFieldMismatch'))
      } else if (caught instanceof ApiError && caught.code === 'inactive_custom_field') {
        setError(t('machines.inactiveField'))
      } else if (caught instanceof ApiError && caught.code === 'pressure_not_applicable') {
        setError(t('machines.pressureNotApplicable'))
      } else setError(t('machines.saveError'))
    }
  }

  const field = <K extends keyof MachineForm>(name: K, value: MachineForm[K]) => {
    setForm((current) => ({ ...current, [name]: value }))
  }

  return (
    <div className="modal-bg">
      <div className="modal" role="dialog" aria-modal="true" aria-label={machine ? t('machines.editTitle') : t('machines.newTitle')}>
        <div className="modal-head">
          <h3>{machine ? t('machines.editTitle') : t('machines.newTitle')}</h3>
          <button onClick={onClose} aria-label={t('common.close')}><X /></button>
        </div>
        <form onSubmit={save} className="form-grid">
          <h4 className="wide asset-form-heading">{t('machines.basicData')}</h4>
          <label>{t('machines.inventoryNumber')}<input required disabled={Boolean(machine)} value={form.inventory_number} onChange={(event) => field('inventory_number', event.target.value)} /></label>
          <label>{t('machines.name')}<input required disabled={!canEdit} value={form.name} onChange={(event) => field('name', event.target.value)} /></label>
          <label>{t('machines.category')}<select required disabled={!canEdit} value={form.category_id} onChange={(event) => { const categoryId = event.target.value ? Number(event.target.value) : ''; setForm((current) => ({ ...current, category_id: categoryId, pressure_bar: supportsPressure(categories.find((item) => item.id === categoryId)) ? current.pressure_bar : '' })) }}><option value="">{t('machines.selectCategory')}</option>{categories.map((category) => <option value={category.id} key={category.id} disabled={!category.is_active && category.id !== form.category_id}>{category[`name_${locale}` as 'name_bg'] || category.name_bg}{!category.is_active ? ` · ${t('admin.inactive')}` : ''}</option>)}</select></label>
          <label>{t('machines.brand')}<input required disabled={!canEdit} value={form.brand} onChange={(event) => field('brand', event.target.value)} /></label>
          <label>{t('machines.model')}<input disabled={!canEdit} value={form.model} onChange={(event) => field('model', event.target.value)} /></label>
          <label>{t('machines.serialNumber')}<input disabled={!canEdit} value={form.serial_number} onChange={(event) => field('serial_number', event.target.value)} /></label>
          {hasPressure && <label>{t('machines.pressure')}<input disabled={!canEdit} type="number" min="0" value={form.pressure_bar} onChange={(event) => field('pressure_bar', event.target.value === '' ? '' : Number(event.target.value))} /></label>}
          {form.category_id && (loadingFields || Boolean(definition?.fields.length)) && <div className="wide category-field-section"><h4>{t('passport.customFields')}</h4>
            {loadingFields ? <p>{t('common.loading')}</p> : definition?.fields.map(item =>
              <CategoryFieldControl key={item.id} field={item} value={customValues[item.id] || ''}
                disabled={!canEdit} onChange={value => setCustomValues(current => ({ ...current, [item.id]: value }))} />)}
          </div>}
          <h4 className="wide asset-form-heading">{t('machines.organizationalData')}</h4>
          <label>{t('common.status')}<select disabled={!canEdit} value={form.status} onChange={(event) => field('status', event.target.value)}>{MACHINE_STATUS_CODES.map((status) => <option key={status} value={status}>{statusText(t, status)}</option>)}</select></label>
          <label>{t('common.location')}<select disabled={!canEdit} value={form.location_id} onChange={(event) => field('location_id', event.target.value ? Number(event.target.value) : '')}><option value="">{t('common.notSpecified')}</option>{locations.map((location) => <option disabled={!location.is_active && location.id !== form.location_id} key={location.id} value={location.id}>{location.name}{!location.is_active ? ` · ${t('admin.inactive')}` : ''}</option>)}</select></label>
          <label>{t('passport.manufacturer')}<input disabled={!canEdit} value={form.manufacturer} onChange={(event) => field('manufacturer', event.target.value)} /></label>
          <label>{t('passport.manufactureYear')}<input disabled={!canEdit} type="number" min="1800" max="2200" value={form.manufacture_year} onChange={(event) => field('manufacture_year', event.target.value ? Number(event.target.value) : '')} /></label>
          <label>{t('machines.assetType')}<input disabled={!canEdit} value={form.asset_type} onChange={(event) => field('asset_type', event.target.value)} /></label>
          <label>{t('machines.subtype')}<input disabled={!canEdit} value={form.subtype} onChange={(event) => field('subtype', event.target.value)} /></label>
          <label>{t('machines.commissioningDate')}<input disabled={!canEdit} type="date" value={form.commissioning_date} onChange={(event) => field('commissioning_date', event.target.value)} /></label>
          <label>{t('machines.ownership')}<input disabled={!canEdit} value={form.ownership} onChange={(event) => field('ownership', event.target.value)} /></label>
          <label>{t('passport.department')}<select disabled={!canEdit} value={form.department} onChange={(event) => field('department', event.target.value)}><option value="">{t('common.notSpecified')}</option>{form.department && !departments.some((item) => item.code === form.department) && <option value={form.department}>{form.department}</option>}{departments.map((department) => <option disabled={!department.is_active && department.code !== form.department} value={department.code} key={department.id}>{department[`name_${locale}` as 'name_bg'] || department.name_bg} · {department.code}{!department.is_active ? ` · ${t('admin.inactive')}` : ''}</option>)}</select></label>
          <label>{t('passport.responsible')}<input disabled={!canEdit} value={form.responsible_person} onChange={(event) => field('responsible_person', event.target.value)} /></label>
          <label>{t('machines.capacity')}<input disabled={!canEdit} value={form.capacity} onChange={(event) => field('capacity', event.target.value)} /></label>
          <label>{t('machines.dimensions')}<input disabled={!canEdit} value={form.dimensions} onChange={(event) => field('dimensions', event.target.value)} /></label>
          <label className="check-label"><input disabled={!canEdit} type="checkbox" checked={form.is_active} onChange={(event) => field('is_active', event.target.checked)} />{t('machines.active')}</label>
          <label className="wide">{t('machines.notes')}<textarea disabled={!canEdit} value={form.notes} onChange={(event) => field('notes', event.target.value)} /></label>
          {machine && <div className="qr-box"><AuthenticatedImage src={`/machines/${machine.id}/qr`} alt={t('machines.qrAlt', { number: machine.inventory_number })} /><span>{t('machines.qrLabel')}</span></div>}
          {error && <div className="error wide" role="alert">{error}</div>}
          <div className="actions wide">
            <button type="button" className="secondary" onClick={onClose}>{t('common.cancel')}</button>
            {canEdit && <button className="primary" disabled={loadingFields || !definition}>{t('common.save')}</button>}
          </div>
        </form>
      </div>
    </div>
  )
}
