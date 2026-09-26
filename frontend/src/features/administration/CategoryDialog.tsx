import { useEffect, useState, type FormEvent } from 'react'
import { ApiError, api } from '../../api'
import { Modal } from '../../industrialUi'
import { useI18n } from '../../i18n'
import type { AssetCategory } from '../../types'

export type CapabilityDefinition = {
  code: string
  name_bg: string; name_en: string; name_ru: string
  description_bg: string; description_en: string; description_ru: string
}

const empty = { code: '', name_bg: '', name_en: '', name_ru: '', description: '', icon: '', capabilities: [] as string[], validation_rules: null as Record<string, unknown> | null, document_types: null as string[] | null, checklists: null as Array<Record<string, unknown>> | null, status_codes: null as string[] | null }

function parseAdvanced(value: string, array: boolean): unknown {
  if (!value.trim()) return null
  const parsed: unknown = JSON.parse(value)
  if (array ? !Array.isArray(parsed) : !parsed || typeof parsed !== 'object' || Array.isArray(parsed)) throw Error('invalid_json')
  return parsed
}

export function CategoryDialog({ category, advanced = false, onClose, onSaved }: {
  category?: AssetCategory; advanced?: boolean; onClose: () => void; onSaved: (category: AssetCategory) => void
}) {
  const { locale, t } = useI18n()
  const [form, setForm] = useState({ ...empty, ...(category || {}), name_en: category?.name_en || '', name_ru: category?.name_ru || '', description: category?.description || '', icon: category?.icon || '', capabilities: category?.capabilities || [] })
  const [capabilities, setCapabilities] = useState<CapabilityDefinition[]>([])
  const [error, setError] = useState('')
  const [saving, setSaving] = useState(false)
  const [advancedText, setAdvancedText] = useState({
    validation_rules: category?.validation_rules ? JSON.stringify(category.validation_rules, null, 2) : '',
    document_types: category?.document_types ? JSON.stringify(category.document_types, null, 2) : '',
    checklists: category?.checklists ? JSON.stringify(category.checklists, null, 2) : '',
    status_codes: category?.status_codes ? JSON.stringify(category.status_codes, null, 2) : '',
  })
  useEffect(() => { void api<CapabilityDefinition[]>('/admin/asset-capabilities').then(setCapabilities).catch(() => setError(t('admin.loadError'))) }, [t])

  async function save(event: FormEvent) {
    event.preventDefault()
    setError('')
    try {
      const values: Record<string, unknown> = {
        code: form.code, name_bg: form.name_bg, name_en: form.name_en || null, name_ru: form.name_ru || null,
        description: form.description || null, icon: form.icon || null, capabilities: form.capabilities,
      }
      if (advanced) {
        values.validation_rules = parseAdvanced(advancedText.validation_rules, false)
        values.document_types = parseAdvanced(advancedText.document_types, true)
        values.checklists = parseAdvanced(advancedText.checklists, true)
        values.status_codes = parseAdvanced(advancedText.status_codes, true)
      }
      if (category) {
        delete values.code
        for (const key of Object.keys(values)) {
          if (JSON.stringify(values[key]) === JSON.stringify(category[key as keyof AssetCategory] ?? null)) delete values[key]
        }
        if (!Object.keys(values).length) { onClose(); return }
      }
      setSaving(true)
      const saved = await api<AssetCategory>(category ? `/categories/${category.id}` : '/categories', {
        method: category ? 'PATCH' : 'POST', body: JSON.stringify(values),
      })
      onSaved(saved)
    } catch (caught) {
      if (caught instanceof ApiError && caught.code === 'category_code_duplicate') setError(t('admin.categoryDuplicate'))
      else if (caught instanceof ApiError && caught.code === 'category_capability_in_use') setError(t('admin.pressureInUse', { count: Number(caught.data.affected_asset_count || 0) }))
      else if (caught instanceof SyntaxError || caught instanceof Error && caught.message === 'invalid_json') setError(t('admin.configurationJsonError'))
      else if (caught instanceof ApiError && caught.status === 422) setError(t('admin.invalidCategoryConfig'))
      else setError(t('admin.saveError'))
    } finally { setSaving(false) }
  }

  return <Modal title={t(category ? 'admin.editCategory' : 'admin.addCategory')} onClose={onClose} wide>
    <form className="form-grid" onSubmit={save}>
      <label>{t('admin.code')}<input required minLength={2} pattern="[A-Z0-9_-]+" readOnly={Boolean(category)} value={form.code} onChange={event => setForm({ ...form, code: event.target.value.toUpperCase() })} /></label>
      <label>{t('admin.categoryIcon')}<input value={form.icon} onChange={event => setForm({ ...form, icon: event.target.value })} /></label>
      <label>{t('language.bg')}<input required minLength={2} value={form.name_bg} onChange={event => setForm({ ...form, name_bg: event.target.value })} /></label>
      <label>{t('language.en')}<input value={form.name_en} onChange={event => setForm({ ...form, name_en: event.target.value })} /></label>
      <label>{t('language.ru')}<input value={form.name_ru} onChange={event => setForm({ ...form, name_ru: event.target.value })} /></label>
      <label className="wide">{t('catalog.description')}<textarea value={form.description} onChange={event => setForm({ ...form, description: event.target.value })} /></label>
      <fieldset className="wide category-capabilities"><legend>{t('admin.platformFunctions')}</legend>
        {capabilities.map(capability => <label className="category-capability" key={capability.code}>
          <input type="checkbox" checked={form.capabilities.includes(capability.code)} onChange={event => setForm(current => ({ ...current, capabilities: event.target.checked ? [...current.capabilities, capability.code] : current.capabilities.filter(code => code !== capability.code) }))} />
          <span><b>{capability[`name_${locale}`]}</b><small>{capability[`description_${locale}`]}</small><small className="muted">{capability.code}</small></span>
        </label>)}
      </fieldset>
      {advanced && <details className="wide category-advanced"><summary>{t('admin.advancedSettings')}</summary><div className="form-grid">
        {(['document_types', 'status_codes', 'checklists', 'validation_rules'] as const).map(key => <label key={key}>{t(({ document_types: 'admin.categoryDocumentTypes', status_codes: 'admin.categoryStatuses', checklists: 'admin.categoryChecklists', validation_rules: 'admin.validationRules' } as const)[key])}<textarea value={advancedText[key]} onChange={event => setAdvancedText({ ...advancedText, [key]: event.target.value })} /></label>)}
      </div></details>}
      {error && <div className="error wide" role="alert">{error}</div>}
      <div className="actions wide"><button type="button" className="secondary" onClick={onClose}>{t('common.cancel')}</button><button className="primary" disabled={saving || !capabilities.length}>{t('common.save')}</button></div>
    </form>
  </Modal>
}
