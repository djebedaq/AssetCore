import { useState } from 'react'
import { CheckCircle2, ShoppingCart, Trash2, Undo2 } from 'lucide-react'

import { api } from '../../api'
import { friendlyError } from '../../industrialUi'
import { useI18n } from '../../i18n'
import { hasPermission } from '../../permissions'
import type { MultiPartRequest } from '../../types'
import { notifyPartRequestsChanged } from '../partRequests/partRequestEvents'
import { updateCartQuantity } from './catalogState'
import type { CatalogCartLine } from './catalogTypes'
import {
  formatTransactionalPartQuantity,
  isRequestedPartQuantity,
} from '../partRequests/partRequestQuantities'

export function CatalogRequestCart({
  machineId,
  cartMachineId,
  lines,
  onChange,
  undoAvailable,
  onUndo,
}: {
  machineId: number
  cartMachineId: number | null
  lines: CatalogCartLine[]
  onChange: (lines: CatalogCartLine[]) => void
  undoAvailable: boolean
  onUndo: () => void
}) {
  const { locale, t } = useI18n()
  const [confirming, setConfirming] = useState(false)
  const [reason, setReason] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState('')
  const [created, setCreated] = useState('')

  async function submit() {
    if (!lines.length || cartMachineId !== machineId) {
      setError(t('catalog.cartMachineMismatch'))
      return
    }
    if (lines.some((line) => !isRequestedPartQuantity(line.quantity))) {
      setError(t('errors.validation'))
      return
    }
    setSubmitting(true)
    setError('')
    try {
      const request = await api<MultiPartRequest>('/part-requests/multi', {
        method: 'POST',
        body: JSON.stringify({
          machine_id: machineId,
          priority: 'NORMAL',
          language: locale,
          reason: reason || null,
          submit_for_approval: true,
          lines: lines.map((line) => ({
            catalog_part_id: line.catalog_part_id,
            position: line.position,
            part_number: line.part_number,
            description: line.description,
            quantity: line.quantity,
            source_document: line.source_document,
            source_page: line.source_page,
            assembly: line.assembly,
          })),
        }),
      })
      setCreated(request.request_reference)
      notifyPartRequestsChanged()
      setConfirming(false)
      onChange([])
    } catch (caught) {
      setError(friendlyError(caught, t('parts.saveError')))
    } finally {
      setSubmitting(false)
    }
  }

  return <aside className="catalog-v2-cart panel">
    <header><ShoppingCart size={21} /><span><h3>{t('catalog.requestCart')}</h3><small>{t('catalog.selectedCount', { count: lines.length })}</small></span></header>
    {created && <div className="success" role="status"><CheckCircle2 size={18} />{t('catalog.requestCreated')} <b>{created}</b></div>}
    {error && <div className="error">{error}</div>}
    <div className="catalog-v2-cart-lines">{lines.map((line) => <div key={line.source_record_key}>
      <span><b>{t('catalog.position')} {line.position} · {line.part_number || t('common.noValue')}</b><small>{line.description}</small>{line.replacement_applied && <small className="verified">{t('catalog.oldNumber')}: {line.source_part_number}</small>}</span>
      <label>{t('catalog.requestedQuantity')}<input aria-label={`${t('catalog.requestedQuantity')} ${line.part_number}`} type="number" inputMode="numeric" min="1" step="1" value={line.quantity} onChange={(event) => onChange(updateCartQuantity(lines, line.source_record_key, Number(event.target.value)))} /></label>
      <button className="link" aria-label={t('common.remove')} onClick={() => onChange(lines.filter((item) => item.source_record_key !== line.source_record_key))}><Trash2 size={16} /></button>
    </div>)}</div>
    {!lines.length && <div className="empty-state">{t('catalog.emptyCart')}</div>}
    {undoAvailable && <button className="secondary" onClick={onUndo}><Undo2 size={16} />{t('catalog.undoKitAddition')}</button>}
    {lines.length > 0 && <div className="catalog-v2-cart-actions"><button className="link" onClick={() => onChange([])}>{t('catalog.clearCart')}</button>{hasPermission('requests.create') && <button className="primary" onClick={() => setConfirming(true)}>{t('catalog.createRequest')}</button>}</div>}
    {confirming && <div className="catalog-v2-confirmation" role="dialog" aria-modal="true">
      <h4>{t('requests.confirm')}</h4>
      <p>{t('catalog.confirmRequestSummary', { count: lines.length })}</p>
      <div>{lines.map((line) => <span key={line.source_record_key}><b>{line.part_number || t('common.noValue')}</b> × {formatTransactionalPartQuantity(line.quantity)}</span>)}</div>
      <label>{t('parts.reason')}<textarea value={reason} onChange={(event) => setReason(event.target.value)} /></label>
      <div className="actions"><button className="secondary" disabled={submitting} onClick={() => setConfirming(false)}>{t('common.cancel')}</button><button className="primary" disabled={submitting} onClick={() => void submit()}>{submitting ? t('common.loading') : t('requests.submit')}</button></div>
    </div>}
  </aside>
}
