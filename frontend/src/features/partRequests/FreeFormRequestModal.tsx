import { useEffect, useState } from 'react'
import { Plus, Trash2 } from 'lucide-react'
import { api, createApiObjectUrl } from '../../api'
import { Modal } from '../../industrialUi'
import { useI18n, type TranslationKey } from '../../i18n'
import type { MultiPartRequest } from '../../types'
import { notifyPartRequestsChanged } from './partRequestEvents'

export const REQUEST_UNITS = ['pcs', 'm', 'l', 'kg', 'g', 'm2', 'm3', 'set', 'pair'] as const
type Row = { key: number; description: string; quantity: string; unit: string }

export function validRequestQuantity(quantity: string, unit: string): boolean {
  const normalized = quantity.trim().replace(',', '.')
  if (!/^\d{1,9}(\.\d{1,6})?$/.test(normalized) || !/[1-9]/.test(normalized)) return false
  return !['pcs', 'set', 'pair'].includes(unit) || !normalized.includes('.') || /^0+$/.test(normalized.split('.')[1])
}

export function RequestPreviewButton({ requestId }: { requestId: number }) {
  const { t } = useI18n()
  const [url, setUrl] = useState('')
  const [error, setError] = useState(false)
  const [busy, setBusy] = useState(false)
  useEffect(() => () => { if (url) URL.revokeObjectURL(url) }, [url])
  async function preview() {
    setBusy(true); setError(false)
    try { setUrl((await createApiObjectUrl(`/part-requests/${requestId}/preview`)).url) }
    catch { setError(true) }
    finally { setBusy(false) }
  }
  return <><button className="secondary" disabled={busy} onClick={() => void preview()}>{t('requests01.preview')}</button>
    {error && <span role="alert">{t('requests.documentError')}</span>}
    {url && <Modal title={t('requests01.preview')} onClose={() => setUrl('')} wide><iframe className="request-preview" src={url} title={t('requests01.preview')} /></Modal>}</>
}

export function FreeFormRequestModal({ request, onClose, onSaved }: { request?: MultiPartRequest; onClose: () => void; onSaved: () => void }) {
  const { t, locale } = useI18n()
  const [id, setId] = useState(request?.id)
  const [department, setDepartment] = useState(request?.department || '')
  const [reason, setReason] = useState(request?.reason || '')
  const [rows, setRows] = useState<Row[]>(request?.lines.map((line, key) => ({ key, description: line.description, quantity: line.exact_quantity || String(line.quantity), unit: line.unit || 'pcs' })) || [{ key: 0, description: '', quantity: '1', unit: 'pcs' }])
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [saved, setSaved] = useState(false)
  const [previewUrl, setPreviewUrl] = useState('')
  useEffect(() => () => { if (previewUrl) URL.revokeObjectURL(previewUrl) }, [previewUrl])

  function change(index: number, values: Partial<Row>) {
    setRows(current => current.map((row, i) => i === index ? { ...row, ...values } : row)); setSaved(false); setPreviewUrl('')
  }
  async function save(action: 'draft' | 'preview' | 'submit') {
    if (!department.trim() || !rows.length || rows.some(row => !row.description.trim() || !validRequestQuantity(row.quantity, row.unit))) {
      setError(t('requests01.validation')); return
    }
    if (action === 'submit' && !window.confirm(t('requests.submitDraftConfirm'))) return
    setBusy(true); setError('')
    try {
      const result = await api<MultiPartRequest>(id ? `/part-requests/${id}/free-form` : '/part-requests/free-form', {
        method: id ? 'PUT' : 'POST', body: JSON.stringify({ department, reason: reason || null, language: request?.language || locale,
          submit_for_approval: action === 'submit', lines: rows.map(row => ({ description: row.description, quantity: row.quantity.replace(',', '.'), unit: row.unit })) }),
      })
      setId(result.id); setSaved(true); notifyPartRequestsChanged(); onSaved()
      if (action === 'preview') setPreviewUrl((await createApiObjectUrl(`/part-requests/${result.id}/preview`)).url)
      if (action === 'submit') onClose()
    } catch { setError(t('parts.saveError')) }
    finally { setBusy(false) }
  }
  return <Modal title={t(request ? 'requests01.edit' : 'requests01.new')} onClose={onClose} wide>
    <form className="form-grid free-form-request" onSubmit={event => { event.preventDefault(); void save('submit') }}>
      <label className="wide">{t('requests.department')}<input required maxLength={255} value={department} disabled={busy} onChange={event => { setDepartment(event.target.value); setSaved(false); setPreviewUrl('') }} /></label>
      <div className="wide free-form-rows">{rows.map((row, index) => <div className="free-form-row" key={row.key}>
        <label>{t('requests01.description')}<textarea required maxLength={4000} value={row.description} disabled={busy} onChange={event => change(index, { description: event.target.value })} /></label>
        <label>{t('requests01.quantity')}<input required inputMode="decimal" value={row.quantity} disabled={busy} onChange={event => change(index, { quantity: event.target.value })} /></label>
        <label>{t('requests01.unit')}<select aria-label={t('requests01.unit')} value={row.unit} disabled={busy} onChange={event => change(index, { unit: event.target.value })}>{REQUEST_UNITS.map(unit => <option key={unit} value={unit}>{t(`requests01.${unit}` as TranslationKey)}</option>)}</select></label>
        <button type="button" className="secondary compact" disabled={busy || rows.length === 1} aria-label={`${t('common.remove')} ${index + 1}`} onClick={() => { setRows(current => current.filter((_, i) => i !== index)); setSaved(false); setPreviewUrl('') }}><Trash2 size={16} /></button>
      </div>)}</div>
      <button type="button" className="secondary" disabled={busy || rows.length >= 500} onClick={() => { setRows(current => [...current, { key: Math.max(...current.map(row => row.key)) + 1, description: '', quantity: '1', unit: 'pcs' }]); setPreviewUrl(''); setSaved(false) }}><Plus size={16} />{t('requests01.addRow')}</button>
      <label className="wide">{t('parts.reason')}<textarea maxLength={8000} disabled={busy} value={reason} onChange={event => { setReason(event.target.value); setSaved(false); setPreviewUrl('') }} /></label>
      {error && <div role="alert" className="error wide">{error}</div>}
      {saved && <div role="status" className="success wide">{t('requests01.saved')}</div>}
      <div className="actions wide"><button type="button" className="secondary" disabled={busy} onClick={() => void save('draft')}>{t('requests01.saveDraft')}</button><button type="button" className="secondary" disabled={busy} onClick={() => void save('preview')}>{t('requests01.preview')}</button><button className="primary" disabled={busy}>{t('requests.submit')}</button></div>
      {previewUrl && <iframe className="wide request-preview" src={previewUrl} title={t('requests01.preview')} />}
    </form>
  </Modal>
}
