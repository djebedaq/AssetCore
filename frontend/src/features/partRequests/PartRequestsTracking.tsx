import { type FormEvent, useEffect, useState } from 'react'
import {
  CheckCircle2,
  FilePlus2,
  PackageCheck,
  ShieldCheck,
  Upload,
} from 'lucide-react'

import { api } from '../../api'
import {
  AttachmentList,
  DocumentButtons,
  Modal,
  filePayload,
  friendlyError,
} from '../../industrialUi'
import { statusText, useI18n, type TranslationKey } from '../../i18n'
import { hasPermission } from '../../permissions'
import type { CatalogPartEnhanced, MultiPartRequest } from '../../types'
import { notifyPartRequestsChanged } from './partRequestEvents'

const DOCUMENT_STATUSES = new Set([
  'APPROVED',
  'ORDERED',
  'PARTIALLY_DELIVERED',
  'DELIVERED',
])

function UnknownPartLinkModal({
  request,
  line,
  catalog,
  onClose,
  onSaved,
}: {
  request: MultiPartRequest
  line: MultiPartRequest['lines'][number]
  catalog: CatalogPartEnhanced[]
  onClose: () => void
  onSaved: () => void
}) {
  const { t } = useI18n()
  const compatible = catalog.filter((part) => part.is_verified && part.is_active !== false && (!request.machine_number || (part.compatible_machine_numbers || []).map(String).includes(String(request.machine_number))))
  const [catalogPartId, setCatalogPartId] = useState<number | ''>('')
  const [note, setNote] = useState('')
  const [error, setError] = useState('')
  async function submit() {
    if (!catalogPartId) return
    try {
      await api(`/part-requests/${request.id}/lines/${line.id}/link-catalog-part`, { method: 'POST', body: JSON.stringify({ catalog_part_id: catalogPartId, note: note || null }) })
      onSaved()
    } catch (caught) {
      setError(friendlyError(caught, t('unknownPart.linkError')))
    }
  }
  return <Modal title={t('unknownPart.linkTitle')} onClose={onClose} wide>
    {error && <div className="error">{error}</div>}
    <div className="unknown-part-banner"><b>{t('unknownPart.label')}</b><span>{line.assembly} · {line.description}</span></div>
    <div className="form-grid">
      <label className="wide">{t('unknownPart.verifiedCatalogPart')}<select value={catalogPartId} onChange={(event) => setCatalogPartId(event.target.value ? Number(event.target.value) : '')}><option value="">{t('unknownPart.chooseVerifiedPart')}</option>{compatible.map((part) => <option value={part.id} key={part.id}>{part.part_number} · {part.description}</option>)}</select></label>
      <label className="wide">{t('unknownPart.linkNote')}<textarea value={note} onChange={(event) => setNote(event.target.value)} /></label>
    </div>
    {!compatible.length && <div className="error">{t('unknownPart.noCompatibleVerifiedParts')}</div>}
    <div className="actions"><button className="secondary" onClick={onClose}>{t('common.cancel')}</button><button className="primary" disabled={!catalogPartId} onClick={() => void submit()}>{t('unknownPart.linkAction')}</button></div>
  </Modal>
}

function PartRequestFulfillmentModal({ request, onClose, onSaved }: { request: MultiPartRequest; onClose: () => void; onSaved: () => void }) {
  const { t } = useI18n()
  const statuses = request.status === 'APPROVED' ? ['ORDERED', 'CANCELLED'] : ['PARTIALLY_DELIVERED', 'DELIVERED', 'CANCELLED']
  const [nextStatus, setNextStatus] = useState(statuses[0])
  const [supplier, setSupplier] = useState(request.supplier || '')
  const [note, setNote] = useState(request.delivery_note || '')
  const [quantities, setQuantities] = useState<Record<number, number>>(Object.fromEntries(request.lines.map((line) => [line.id, line.delivered_quantity])))
  const [error, setError] = useState('')
  async function submit(event: FormEvent) {
    event.preventDefault()
    if (!window.confirm(t('requests.fulfillmentConfirm'))) return
    try {
      await api(`/part-requests/${request.id}/fulfillment`, { method: 'PATCH', body: JSON.stringify({ status: nextStatus, supplier: supplier || null, note: note || null, lines: request.lines.map((line) => ({ line_id: line.id, delivered_quantity: quantities[line.id] || 0 })) }) })
      notifyPartRequestsChanged()
      onSaved()
    } catch (caught) {
      setError(friendlyError(caught, t('requests.fulfillmentError')))
    }
  }
  return <Modal title={t('requests.fulfillmentTitle')} onClose={onClose} wide><form className="form-grid" onSubmit={submit}>
    <label>{t('common.status')}<select value={nextStatus} onChange={(event) => setNextStatus(event.target.value)}>{statuses.map((status) => <option value={status} key={status}>{statusText(t, status, 'part')}</option>)}</select></label>
    <label>{t('catalog.supplier')}<input value={supplier} onChange={(event) => setSupplier(event.target.value)} /></label>
    <label className="wide">{t('common.notes')}<textarea value={note} onChange={(event) => setNote(event.target.value)} /></label>
    <div className="wide request-line-list">{request.lines.map((line) => <div key={line.id}><span><b>{line.part_number || t('common.noValue')}</b><small>{line.description}</small></span><label>{t('requests.deliveredQuantity')}<input disabled={nextStatus === 'ORDERED' || nextStatus === 'CANCELLED'} type="number" min={line.delivered_quantity} max={line.quantity} step="0.01" value={quantities[line.id] || 0} onChange={(event) => setQuantities((current) => ({ ...current, [line.id]: Number(event.target.value) }))} /></label><em>/ {line.quantity} {line.unit}</em></div>)}</div>
    {error && <div className="error wide">{error}</div>}
    <div className="actions wide"><button type="button" className="secondary" onClick={onClose}>{t('common.cancel')}</button><button className="primary">{t('requests.saveFulfillment')}</button></div>
  </form></Modal>
}

function nextActionKey(request: MultiPartRequest): TranslationKey {
  if (request.status === 'DRAFT') return 'requests.nextAction.submit'
  if (request.status === 'WAITING_APPROVAL') return hasPermission('requests.approve') ? 'requests.nextAction.decide' : 'requests.nextAction.waitingApproval'
  if (request.status === 'APPROVED') return 'requests.nextAction.order'
  if (request.status === 'ORDERED' || request.status === 'PARTIALLY_DELIVERED') return 'requests.nextAction.delivery'
  return 'requests.nextAction.none'
}

export function PartRequestsTracking() {
  const { date, t } = useI18n()
  const [items, setItems] = useState<MultiPartRequest[]>([])
  const [catalog, setCatalog] = useState<CatalogPartEnhanced[]>([])
  const [fulfillment, setFulfillment] = useState<MultiPartRequest | null>(null)
  const [unknownLink, setUnknownLink] = useState<{ request: MultiPartRequest; line: MultiPartRequest['lines'][number] } | null>(null)
  const [error, setError] = useState('')
  const load = async () => {
    try {
      const requestItems = await api<MultiPartRequest[]>('/part-requests/multi')
      setItems([...requestItems].sort((left, right) => new Date(right.created_at).getTime() - new Date(left.created_at).getTime()))
      if (hasPermission('parts.manage')) setCatalog(await api<CatalogPartEnhanced[]>('/catalog/parts'))
      setError('')
    } catch (caught) {
      setError(friendlyError(caught, t('requests.loadError')))
    }
  }
  useEffect(() => { void load() }, [])

  async function submitDraft(id: number) {
    if (!window.confirm(t('requests.submitDraftConfirm'))) return
    try {
      await api(`/part-requests/${id}/submit`, { method: 'POST' })
      notifyPartRequestsChanged()
      await load()
    } catch (caught) {
      setError(friendlyError(caught, t('requests.submitError')))
    }
  }
  async function decide(id: number, decision: 'APPROVED' | 'REJECTED') {
    if (!window.confirm(t(decision === 'APPROVED' ? 'requests.approveConfirm' : 'requests.rejectConfirm'))) return
    try {
      await api(`/part-requests/${id}/decision`, { method: 'POST', body: JSON.stringify({ decision }) })
      notifyPartRequestsChanged()
      await load()
    } catch (caught) {
      setError(friendlyError(caught, t('requests.decisionError')))
    }
  }
  async function generate(request: MultiPartRequest) {
    if (!window.confirm(t('documents.confirmLanguage', { language: t(`language.${request.language}` as TranslationKey) }))) return
    try {
      await api(`/part-requests/${request.id}/documents?language=${request.language}`, { method: 'POST' })
      await load()
    } catch (caught) {
      setError(friendlyError(caught, t('requests.documentError')))
    }
  }
  async function attach(request: MultiPartRequest, file?: File) {
    if (!file) return
    try {
      await api(`/part-requests/${request.id}/attachments`, { method: 'POST', body: JSON.stringify({ ...(await filePayload(file)), description: file.name }) })
      await load()
    } catch (caught) {
      setError(friendlyError(caught, t('requests.attachmentError')))
    }
  }

  return <>
    <div className="toolbar"><div><h3>{t('parts.title')}</h3><p className="muted">{t('requests.subtitle')}</p></div></div>
    {error && <div className="error" role="alert">{error}</div>}
    <div className="cards-list">{items.map((request) => <article className="panel request-card" key={request.id}>
      <div className="request-card-head"><div><span className="badge">{statusText(t, request.status, 'part')}</span><h3>{request.request_reference}</h3><small>{date(request.created_at)} · {request.machine_number ? t('passport.title', { number: request.machine_number }) : t('parts.general')}</small>{request.requested_by_name && <small>{t('requests.requester')}: {request.requested_by_name}</small>}{request.repair_reference && <small>{t('requests.linkedRepair')}: {request.repair_reference}</small>}{request.department && <small>{t('requests.department')}: {request.department}</small>}{request.supplier && <small>{t('catalog.supplier')}: {request.supplier}</small>}</div><b>{statusText(t, request.priority, 'part')}</b></div>
      <div className="request-next-action"><b>{t('requests.nextAction')}</b><span>{t(nextActionKey(request))}</span></div>
      <div className="request-line-list">{request.lines.map((line) => <div className={line.is_unknown_part ? 'unknown-part-request-line' : ''} key={line.id}><span><b>{line.is_unknown_part ? t('unknownPart.label') : line.part_number || t('common.noValue')}</b><small>{line.is_unknown_part && line.assembly ? `${t('unknownPart.assembly')}: ${line.assembly} · ` : ''}{line.description}</small>{line.linked_part_number && <small className="verified">{t('unknownPart.linkedTo')}: {line.linked_part_number} · {line.linked_part_description}</small>}</span><span className="request-line-side"><em>{line.delivered_quantity > 0 ? `${t('requests.deliveredQuantity')}: ${line.delivered_quantity} / ` : ''}{line.quantity} {line.unit}</em>{line.is_unknown_part && !line.linked_catalog_part_id && hasPermission('parts.manage') && <button className="secondary compact" onClick={() => setUnknownLink({ request, line })}><ShieldCheck size={14} />{t('unknownPart.linkAction')}</button>}</span></div>)}</div>
      {request.approvals.length > 0 && <details><summary>{t('requests.approvalHistory')} ({request.approvals.length})</summary><div className="request-approval-history">{request.approvals.map((approval) => <div key={approval.id}><b>{statusText(t, approval.decision, 'part')}</b><span>{approval.decided_by_name || t('common.noValue')} · {date(approval.decided_at)}</span>{approval.note && <small>{approval.note}</small>}</div>)}</div></details>}
      {request.attachments.length > 0 && <details><summary>{t('requests.attachments')} ({request.attachments.length})</summary><AttachmentList items={request.attachments} /></details>}
      <div className="request-actions">
        {request.status === 'DRAFT' && hasPermission('requests.create') && <button className="primary" onClick={() => void submitDraft(request.id)}>{t('requests.submitDraft')}</button>}
        {request.status === 'WAITING_APPROVAL' && hasPermission('requests.approve') && <><button className="primary" onClick={() => void decide(request.id, 'APPROVED')}><CheckCircle2 size={16} />{t('requests.approve')}</button><button className="secondary" onClick={() => void decide(request.id, 'REJECTED')}>{t('requests.reject')}</button></>}
        {['APPROVED', 'ORDERED', 'PARTIALLY_DELIVERED'].includes(request.status) && hasPermission('requests.create') && <button className="secondary" onClick={() => setFulfillment(request)}><PackageCheck size={16} />{t('requests.updateFulfillment')}</button>}
        {hasPermission('requests.create') && <label className="secondary compact file-button"><Upload size={15} />{t('requests.addAttachment')}<input hidden type="file" accept="application/pdf,.docx,.xlsx,image/png,image/jpeg,image/webp" onChange={(event) => { void attach(request, event.target.files?.[0]); event.currentTarget.value = '' }} /></label>}
        {DOCUMENT_STATUSES.has(request.status) && request.documents.length === 0 && hasPermission('documents.generate') && <button className="secondary" onClick={() => void generate(request)}><FilePlus2 size={16} />{t('requests.generate')} ({t(`language.${request.language}` as TranslationKey)})</button>}
        {request.documents.map((document) => <DocumentButtons key={document.id} path={document.download_endpoint} filename={document.filename} format={document.format} />)}
      </div>
    </article>)}{!items.length && <div className="empty-state">{t('parts.empty')}</div>}</div>
    {unknownLink && <UnknownPartLinkModal request={unknownLink.request} line={unknownLink.line} catalog={catalog} onClose={() => setUnknownLink(null)} onSaved={() => { setUnknownLink(null); void load() }} />}
    {fulfillment && <PartRequestFulfillmentModal request={fulfillment} onClose={() => setFulfillment(null)} onSaved={() => { setFulfillment(null); void load() }} />}
  </>
}
