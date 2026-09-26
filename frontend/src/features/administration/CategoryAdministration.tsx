import { useEffect, useState, type FormEvent } from 'react'
import { Plus } from 'lucide-react'
import { ApiError, api } from '../../api'
import { Modal } from '../../industrialUi'
import { useI18n, type TranslationKey } from '../../i18n'
import type { AssetCategory, AssetCategoryField } from '../../types'
import { CategoryDialog, type CapabilityDefinition } from './CategoryDialog'

type FieldForm = {
  code: string; label_bg: string; label_en: string; label_ru: string; field_type: string
  is_required: boolean; options: string[]; unit: string; sort_order: number
  min: string; max: string; min_length: string; max_length: string; pattern: string
}
const blankField: FieldForm = { code: '', label_bg: '', label_en: '', label_ru: '', field_type: 'TEXT', is_required: false, options: [], unit: '', sort_order: 0, min: '', max: '', min_length: '', max_length: '', pattern: '' }
const types = ['TEXT', 'INTEGER', 'DECIMAL', 'DATE', 'BOOLEAN', 'SELECT'] as const

function fieldValues(field?: AssetCategoryField): FieldForm {
  if (!field) return { ...blankField, options: [] }
  const rules = field.validation_rules || {}
  return {
    code: field.code, label_bg: field.label_bg, label_en: field.label_en || '', label_ru: field.label_ru || '',
    field_type: field.field_type, is_required: field.is_required, options: field.options || [], unit: field.unit || '',
    sort_order: field.sort_order, min: String(rules.min ?? ''), max: String(rules.max ?? ''),
    min_length: String(rules.min_length ?? ''), max_length: String(rules.max_length ?? ''), pattern: String(rules.pattern ?? ''),
  }
}

function fieldPayload(form: FieldForm): Record<string, unknown> {
  const rules: Record<string, unknown> = {}
  if (form.field_type === 'INTEGER' || form.field_type === 'DECIMAL') {
    if (form.min !== '') rules.min = Number(form.min)
    if (form.max !== '') rules.max = Number(form.max)
  }
  if (form.min_length !== '') rules.min_length = Number(form.min_length)
  if (form.max_length !== '') rules.max_length = Number(form.max_length)
  if (form.pattern.trim()) rules.pattern = form.pattern.trim()
  return {
    code: form.code, label_bg: form.label_bg, label_en: form.label_en || null, label_ru: form.label_ru || null,
    field_type: form.field_type, is_required: form.is_required,
    options: form.field_type === 'SELECT' ? form.options.map(value => value.trim()).filter(Boolean) : null,
    unit: form.unit || null, validation_rules: Object.keys(rules).length ? rules : null, sort_order: form.sort_order,
  }
}

export function CategoryAdministration() {
  const { locale, t } = useI18n()
  const [categories, setCategories] = useState<AssetCategory[]>([])
  const [capabilities, setCapabilities] = useState<CapabilityDefinition[]>([])
  const [error, setError] = useState('')
  const [editingCategory, setEditingCategory] = useState<AssetCategory | 'new' | null>(null)
  const [fieldTarget, setFieldTarget] = useState<{ category: AssetCategory; field?: AssetCategoryField } | null>(null)
  const [fieldForm, setFieldForm] = useState<FieldForm>(fieldValues())
  const [fieldError, setFieldError] = useState('')
  const [saving, setSaving] = useState(false)

  async function load() {
    try {
      const [items, registry] = await Promise.all([api<AssetCategory[]>('/categories'), api<CapabilityDefinition[]>('/admin/asset-capabilities')])
      setCategories(items)
      setCapabilities(registry)
      setError('')
    } catch { setError(t('admin.loadError')) }
  }
  useEffect(() => { void load() }, [])

  async function toggleCategory(category: AssetCategory) {
    if (!window.confirm(t(category.is_active ? 'admin.deactivateCategoryConfirm' : 'admin.activateCategoryConfirm', { count: category.asset_count || 0 }))) return
    try { await api(`/categories/${category.id}`, { method: 'PATCH', body: JSON.stringify({ is_active: !category.is_active }) }); await load() }
    catch { setError(t('admin.saveError')) }
  }
  function openField(category: AssetCategory, field?: AssetCategoryField) {
    setFieldTarget({ category, field }); setFieldForm(fieldValues(field)); setFieldError('')
  }
  async function toggleField(category: AssetCategory, field: AssetCategoryField) {
    try { await api(`/categories/${category.id}/fields/${field.id}`, { method: 'PATCH', body: JSON.stringify({ is_active: !field.is_active }) }); await load() }
    catch (caught) { setError(caught instanceof ApiError && caught.code === 'category_field_values_incompatible' ? t('admin.fieldValuesIncompatible') : t('admin.saveError')) }
  }
  async function saveField(event: FormEvent) {
    event.preventDefault()
    if (!fieldTarget) return
    setFieldError('')
    const { category, field } = fieldTarget
    const values = fieldPayload(fieldForm)
    if (field) {
      delete values.code
      const original = fieldValues(field)
      if ((['min', 'max', 'min_length', 'max_length', 'pattern'] as const).every(key => original[key] === fieldForm[key])) {
        // Preserve older advanced rules when editing unrelated field properties.
        delete values.validation_rules
      } else {
        const mergedRules: Record<string, unknown> = { ...(field.validation_rules || {}) }
        const selectedRules = (values.validation_rules || {}) as Record<string, unknown>
        for (const key of ['min', 'max', 'min_length', 'max_length', 'pattern']) {
          if (key in selectedRules) mergedRules[key] = selectedRules[key]
          else delete mergedRules[key]
        }
        values.validation_rules = Object.keys(mergedRules).length ? mergedRules : null
      }
      for (const key of Object.keys(values)) {
        if (JSON.stringify(values[key]) === JSON.stringify(field[key as keyof AssetCategoryField] ?? null)) delete values[key]
      }
      if (!Object.keys(values).length) { setFieldTarget(null); return }
    }
    try {
      setSaving(true)
      await api(`/categories/${category.id}/fields${field ? `/${field.id}` : ''}`, {
        method: field ? 'PATCH' : 'POST', body: JSON.stringify(values),
      })
      setFieldTarget(null)
      await load()
    } catch (caught) {
      if (caught instanceof ApiError && caught.code === 'category_field_code_duplicate') setFieldError(t('admin.fieldDuplicate'))
      else if (caught instanceof ApiError && caught.code === 'category_field_values_incompatible') setFieldError(t('admin.fieldValuesIncompatible'))
      else if (caught instanceof ApiError && caught.status === 422) setFieldError(t('admin.invalidFieldConfig'))
      else setFieldError(t('admin.saveError'))
    } finally { setSaving(false) }
  }

  return <section className="panel wide category-admin"><div className="panel-title"><h3>{t('admin.categories')}</h3><button type="button" className="secondary compact" onClick={() => setEditingCategory('new')}><Plus size={15} />{t('admin.addCategory')}</button></div>
    {error && <div className="error" role="alert">{error}</div>}
    <div className="category-admin-list">{categories.map(category => <article key={category.id} className="category-admin-card">
      <div className="category-admin-heading"><div><h4>{category[`name_${locale}`] || category.name_bg}</h4><small>{category.code}</small></div><span className="badge">{category.is_active ? t('admin.active') : t('admin.inactive')}</span></div>
      <p className="muted">{t('admin.assetCount', { count: category.asset_count || 0 })} · {t('admin.fieldsCount', { count: category.fields.length })}</p>
      <div className="category-chips">{(category.capabilities || []).map(code => <span className="badge" key={code} title={code}>{capabilities.find(item => item.code === code)?.[`name_${locale}`] || code}</span>)}{!category.capabilities?.length && <span className="muted">{t('admin.noCapabilities')}</span>}</div>
      <div className="category-actions"><button className="secondary compact" onClick={() => setEditingCategory(category)}>{t('common.edit')}</button><button className="secondary compact" onClick={() => void toggleCategory(category)}>{t(category.is_active ? 'admin.deactivate' : 'admin.activate')}</button></div>
      <div className="category-field-list"><div className="category-field-title"><h5>{t('admin.categoryFields')}</h5><button className="link" onClick={() => openField(category)}><Plus size={14} />{t('admin.addField')}</button></div>
        {[...category.fields].sort((a, b) => a.sort_order - b.sort_order || a.id - b.id).map(field => <div className="category-field-row" key={field.id}>
          <span><b>{field[`label_${locale}`] || field.label_bg}</b><small>{field.code} · {t(`fieldType.${field.field_type.toLowerCase()}` as TranslationKey)} · {field.is_required ? t('admin.requiredField') : t('admin.optionalField')}{field.unit ? ` · ${field.unit}` : ''} · {t('admin.sortOrder')}: {field.sort_order}</small></span>
          <span className="badge">{field.is_active ? t('admin.active') : t('admin.inactive')}</span>
          <button className="link" onClick={() => openField(category, field)}>{t('common.edit')}</button>
          <button className="link" onClick={() => void toggleField(category, field)}>{t(field.is_active ? 'admin.deactivate' : 'admin.activate')}</button>
        </div>)}
      </div>
    </article>)}</div>
    {editingCategory && <CategoryDialog category={editingCategory === 'new' ? undefined : editingCategory} advanced onClose={() => setEditingCategory(null)} onSaved={() => { setEditingCategory(null); void load() }} />}
    {fieldTarget && <Modal title={t(fieldTarget.field ? 'admin.editField' : 'admin.addField')} onClose={() => setFieldTarget(null)} wide><form className="form-grid" onSubmit={saveField}>
      <label>{t('admin.code')}<input required minLength={2} pattern="[A-Z0-9_-]+" readOnly={Boolean(fieldTarget.field)} value={fieldForm.code} onChange={event => setFieldForm({ ...fieldForm, code: event.target.value.toUpperCase() })} /></label>
      <label>{t('admin.fieldType')}<select value={fieldForm.field_type} onChange={event => setFieldForm({ ...fieldForm, field_type: event.target.value })}>{types.map(type => <option key={type} value={type}>{t(`fieldType.${type.toLowerCase()}` as TranslationKey)}</option>)}</select></label>
      <label>{t('language.bg')}<input required minLength={2} value={fieldForm.label_bg} onChange={event => setFieldForm({ ...fieldForm, label_bg: event.target.value })} /></label>
      <label>{t('language.en')}<input value={fieldForm.label_en} onChange={event => setFieldForm({ ...fieldForm, label_en: event.target.value })} /></label>
      <label>{t('language.ru')}<input value={fieldForm.label_ru} onChange={event => setFieldForm({ ...fieldForm, label_ru: event.target.value })} /></label>
      <label>{t('admin.fieldUnit')}<input value={fieldForm.unit} onChange={event => setFieldForm({ ...fieldForm, unit: event.target.value })} /></label>
      <label>{t('admin.sortOrder')}<input type="number" min="0" value={fieldForm.sort_order} onChange={event => setFieldForm({ ...fieldForm, sort_order: Number(event.target.value) })} /></label>
      <label className="check-label"><input type="checkbox" checked={fieldForm.is_required} onChange={event => setFieldForm({ ...fieldForm, is_required: event.target.checked })} />{t('admin.requiredField')}</label>
      {fieldForm.is_required && <p className="muted wide">{t('admin.requiredCompatibilityHint')}</p>}
      {fieldForm.field_type === 'SELECT' && <fieldset className="wide category-options"><legend>{t('admin.fieldOptions')}</legend>{fieldForm.options.map((option, index) => <div key={index}><input aria-label={`${t('admin.fieldOptions')} ${index + 1}`} value={option} onChange={event => setFieldForm(current => ({ ...current, options: current.options.map((item, i) => i === index ? event.target.value : item) }))} /><button type="button" className="secondary compact" aria-label={`${t('admin.removeOption')} ${index + 1}`} onClick={() => setFieldForm(current => ({ ...current, options: current.options.filter((_, i) => i !== index) }))}>{t('admin.removeOption')}</button></div>)}<button type="button" className="secondary compact" onClick={() => setFieldForm({ ...fieldForm, options: [...fieldForm.options, ''] })}>{t('admin.addOption')}</button></fieldset>}
      {(fieldForm.field_type === 'INTEGER' || fieldForm.field_type === 'DECIMAL') && <><label>{t('admin.minimum')}<input type="number" step="any" value={fieldForm.min} onChange={event => setFieldForm({ ...fieldForm, min: event.target.value })} /></label><label>{t('admin.maximum')}<input type="number" step="any" value={fieldForm.max} onChange={event => setFieldForm({ ...fieldForm, max: event.target.value })} /></label></>}
      <label>{t('admin.minimumLength')}<input type="number" min="0" value={fieldForm.min_length} onChange={event => setFieldForm({ ...fieldForm, min_length: event.target.value })} /></label>
      <label>{t('admin.maximumLength')}<input type="number" min="0" value={fieldForm.max_length} onChange={event => setFieldForm({ ...fieldForm, max_length: event.target.value })} /></label>
      <label className="wide">{t('admin.pattern')}<input value={fieldForm.pattern} onChange={event => setFieldForm({ ...fieldForm, pattern: event.target.value })} /></label>
      {fieldError && <div className="error wide" role="alert">{fieldError}</div>}
      <div className="actions wide"><button type="button" className="secondary" onClick={() => setFieldTarget(null)}>{t('common.cancel')}</button><button className="primary" disabled={saving}>{t('common.save')}</button></div>
    </form></Modal>}
  </section>
}
