import { formatExactPartQuantity } from './partRequestQuantities'
import { useState } from 'react'
import { api } from '../../api'
import { Modal } from '../../industrialUi'
import { useI18n, type TranslationKey } from '../../i18n'
import type { MultiPartRequest } from '../../types'
import { hasPermission } from '../../permissions'
import { notifyPartRequestsChanged } from './partRequestEvents'
import { validRequestQuantity } from './FreeFormRequestModal'
import { usePage } from '../../ui/workspace'

type Props = { request: MultiPartRequest; onClose: () => void; onSaved: () => void }

export function RequestDeliveryModal({ request, onClose, onSaved }: Props) {
  const { t, locale } = useI18n()
  const [quantities, setQuantities] = useState<Record<number, string>>({})
  const [supplier, setSupplier] = useState(request.supplier || '')
  const [note, setNote] = useState('')
  const [key] = useState(() => crypto.randomUUID())
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  async function save() {
    const lines = request.lines.filter(line => quantities[line.id]?.trim()).map(line => ({ line_id: line.id, quantity: quantities[line.id].replace(',', '.') }))
    if (!lines.length || request.lines.some(line => quantities[line.id]?.trim() && !validRequestQuantity(quantities[line.id], request.request_kind === 'FREE_FORM' ? line.unit || 'pcs' : 'pcs'))) {
      setError(t('requests01.validation')); return
    }
    setBusy(true)
    try {
      await api(`/part-requests/${request.id}/deliveries`, { method: 'POST', body: JSON.stringify({ idempotency_key: key, lines, supplier: supplier || null, note: note || null }) })
      notifyPartRequestsChanged(); onSaved()
    } catch { setError(t('requests.fulfillmentError')) }
    finally { setBusy(false) }
  }
  return <Modal title={t('requests01.delivery')} onClose={onClose} wide><form className="form-grid" onSubmit={event => { event.preventDefault(); void save() }}>
    <label>{t('catalog.supplier')}<input maxLength={255} value={supplier} onChange={event => setSupplier(event.target.value)} /></label>
    <label>{t('common.notes')}<textarea maxLength={8000} value={note} onChange={event => setNote(event.target.value)} /></label>
    <div className="wide request-line-list">{request.lines.map(line => <div key={line.id}><span>{line.description}<small>{t('requests01.remaining')}: {formatExactPartQuantity(line.remaining_quantity || '0', locale)} {request.request_kind === 'FREE_FORM' ? t(`requests01.${line.unit}` as TranslationKey) : line.unit}</small></span><label>{t('requests01.received')}<input inputMode="decimal" value={quantities[line.id] || ''} onChange={event => setQuantities(current => ({ ...current, [line.id]: event.target.value }))} /></label></div>)}</div>
    {error && <div className="wide error" role="alert">{error}</div>}<div className="wide actions"><button className="primary" disabled={busy}>{t('common.save')}</button></div>
  </form></Modal>
}

export function RequestCancelModal({ request, onClose, onSaved }: Props) {
  const { t } = useI18n()
  const [reason, setReason] = useState('')
  const [confirmed, setConfirmed] = useState(false)
  const [replacement, setReplacement] = useState('')
  const [query, setQuery] = useState('')
  const { data } = usePage<MultiPartRequest>(`/workspace/requests?q=${encodeURIComponent(query)}&page_size=100`)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  async function save() {
    setBusy(true)
    try {
      await api(`/part-requests/${request.id}/cancel`, { method: 'POST', body: JSON.stringify({ reason, confirmed, replacement_request_id: replacement ? Number(replacement) : null }) })
      notifyPartRequestsChanged(); onSaved()
    } catch { setError(t('requests.fulfillmentError')) }
    finally { setBusy(false) }
  }
  return <Modal title={t('requests01.cancel')} onClose={onClose}><form className="form-grid" onSubmit={event => { event.preventDefault(); void save() }}>
    <label className="wide">{t('requests01.cancelReason')}<textarea required maxLength={8000} value={reason} onChange={event => setReason(event.target.value)} /></label>
    <label className="wide">{t('requests01.replacement')}<input aria-label={t('common.search')} value={query} onChange={event => setQuery(event.target.value)} /><select value={replacement} onChange={event => setReplacement(event.target.value)}><option value="">{t('common.noValue')}</option>{data?.items.filter(item => item.id !== request.id).map(item => <option key={item.id} value={item.id}>{item.official_number || item.request_reference} · {item.lines[0]?.description}</option>)}</select></label>
    <label className="wide"><input type="checkbox" required checked={confirmed} onChange={event => setConfirmed(event.target.checked)} />{t('requests01.cancelConfirm')}</label>
    {error && <div className="error wide" role="alert">{error}</div>}<button className="primary" disabled={busy || !confirmed || !reason.trim()}>{t('requests01.cancel')}</button>
  </form></Modal>
}

export function RequestDeliveryHistory({ request, onSaved }: { request: MultiPartRequest; onSaved: () => void }) {
  const { t, date, locale } = useI18n()
  const [error, setError] = useState(false)
  const [busy, setBusy] = useState(false)
  async function reverse(id: number) {
    const reason = window.prompt(t('requests01.correctionReason'))
    if (!reason?.trim()) return
    setBusy(true)
    try {
      await api(`/part-requests/${request.id}/deliveries/${id}/reverse`, { method: 'POST', body: JSON.stringify({ reason, idempotency_key: crypto.randomUUID() }) })
      notifyPartRequestsChanged(); onSaved()
    } catch { setError(true) }
    finally { setBusy(false) }
  }
  return <>{error && <div className="error" role="alert">{t('requests.fulfillmentError')}</div>}{!!request.delivery_events?.length && <details><summary>{t('requests01.deliveryHistory')} ({request.delivery_events.length})</summary>{request.delivery_events.map(event => <div className="request-delivery-event" key={event.id}>
    <b>{t(event.kind === 'RECEIPT' ? 'requests01.RECEIPT' : 'requests01.CORRECTION')}</b><span>{event.actor_name} · {date(event.occurred_at)} · {event.supplier}</span>
    {Object.entries(event.quantities).map(([id, quantity]) => <small key={id}>{request.lines.find(line => line.id === Number(id))?.description}: {formatExactPartQuantity(quantity, locale)}</small>)}{event.note && <p>{event.note}</p>}
    {request.status !== 'CANCELLED' && event.kind === 'RECEIPT' && !request.delivery_events?.some(other => other.correction_of_id === event.id) && hasPermission('requests.create') && <button className="secondary compact" disabled={busy} onClick={() => void reverse(event.id)}>{t('requests01.reverse')}</button>}
  </div>)}</details>}</>
}
