import { useEffect, useState, type ReactNode } from 'react'
import { Download, ExternalLink, Search, X } from 'lucide-react'

import { ApiError, createApiObjectUrl, downloadApiFile } from './api'
import { useI18n, type TranslationKey } from './i18n'
import type { StoredAttachment } from './types'

const EVENT_KEYS: Record<string, TranslationKey> = {
  MACHINE_CREATED: 'event.machineCreated', MACHINE_UPDATED: 'event.machineUpdated',
  CUSTOM_FIELDS_UPDATED: 'event.customFieldsUpdated', ATTACHMENT_ADDED: 'event.attachmentAdded',
  TRANSFER_ISSUED: 'event.transferIssued', TRANSFER_RETURNED: 'event.transferReturned',
  REPAIR_ACCEPTED: 'event.repairAccepted', REPAIR_STATUS_CHANGED: 'event.repairStatusChanged',
  IMPORTED: 'event.imported', ACCEPTED: 'event.accepted', INSPECTION: 'event.inspection',
  CLEANING: 'event.cleaning', DIAGNOSIS: 'event.diagnosis', APPROVAL: 'event.approval',
  PARTS: 'event.parts', REPAIR_ACTION: 'event.repairAction', TEST: 'event.test',
  STATUS_CHANGE: 'event.statusChange', COMPLETED: 'event.completed', NOTE: 'event.note',
  WAITING_APPROVAL: 'status.waitingApproval', WAITING_PARTS: 'status.waitingParts',
  REPAIRING: 'status.repairing', TESTING: 'status.testing',
  RETURN_DIRECTED_TO_REPAIR: 'event.returnDirectedToRepair',
  PARTICIPANT_ADDED: 'event.participantAdded', PARTICIPANT_REMOVED: 'event.participantRemoved',
  PART_ADDED: 'event.partAdded',
  DOCUMENT_GENERATED: 'event.documentGenerated', MACHINE_READY: 'event.machineReady',
}

export const DOCUMENT_KEYS: Record<string, TranslationKey> = {
  TRANSFER_ISSUE: 'documentType.transferIssue', TRANSFER_RETURN: 'documentType.transferReturn',
  REPAIR_PROTOCOL: 'documentType.repairProtocol', PART_REQUEST: 'documentType.partRequest',
  DAILY_REPORT: 'documentType.dailyReport', QR_LABEL: 'documentType.qrLabel',
  TECHNICAL: 'documentType.technical', OTHER: 'documentType.other',
}

export function friendlyError(error: unknown, fallback: string): string {
  if (error instanceof ApiError && error.data.message) return error.data.message
  return fallback
}

export function translatedCode(
  t: (key: TranslationKey, values?: Record<string, string | number>) => string,
  value: string,
  keys: Record<string, TranslationKey>,
): string {
  return keys[value] ? t(keys[value]) : value
}

export function translatedEventCode(
  t: (key: TranslationKey, values?: Record<string, string | number>) => string,
  value: string,
): string {
  return EVENT_KEYS[value] ? t(EVENT_KEYS[value]) : t('event.other')
}

export function Modal({ title, onClose, children, wide = false }: {
  title: string; onClose: () => void; children: ReactNode; wide?: boolean
}) {
  const { t } = useI18n()
  return (
    <div className="modal-bg">
      <div className={`modal industrial-modal ${wide ? 'industrial-modal-wide' : ''}`} role="dialog" aria-modal="true" aria-label={title}>
        <div className="modal-head"><h3>{title}</h3><button onClick={onClose} aria-label={t('common.close')}><X /></button></div>
        {children}
      </div>
    </div>
  )
}

export async function filePayload(file: File): Promise<{ filename: string; media_type: string; content_base64: string }> {
  const dataUrl = await new Promise<string>((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => resolve(String(reader.result))
    reader.onerror = () => reject(reader.error)
    reader.readAsDataURL(file)
  })
  return {
    filename: file.name,
    media_type: file.type || 'application/octet-stream',
    content_base64: dataUrl.split(',', 2)[1] || '',
  }
}

export function DownloadButton({ path, filename, label }: { path: string; filename: string; label?: string }) {
  const { t } = useI18n()
  const [failed, setFailed] = useState(false)
  return (
    <span>
      <button className="secondary compact" onClick={() => downloadApiFile(path, filename).catch(() => setFailed(true))}>
        <Download size={15} />{label || t('common.download')}
      </button>
      {failed && <small className="inline-error">{t('errors.generic')}</small>}
    </span>
  )
}

export function DocumentButtons({ path, filename, format, label }: { path: string; filename: string; format: string; label?: string }) {
  const { t } = useI18n()
  const [previewUrl, setPreviewUrl] = useState('')
  const [failed, setFailed] = useState(false)
  const [loading, setLoading] = useState(false)
  useEffect(() => () => { if (previewUrl) URL.revokeObjectURL(previewUrl) }, [previewUrl])
  async function preview() {
    setLoading(true)
    setFailed(false)
    try {
      const result = await createApiObjectUrl(path)
      setPreviewUrl(result.url)
    } catch {
      setFailed(true)
    } finally {
      setLoading(false)
    }
  }
  function closePreview() {
    URL.revokeObjectURL(previewUrl)
    setPreviewUrl('')
  }
  return <span className="document-actions-inline"><DownloadButton path={path} filename={filename} label={label || format.toUpperCase()} />{format.toLowerCase() === 'pdf' && <button className="secondary compact" disabled={loading} onClick={() => void preview()}><Search size={15} />{t('common.preview')}</button>}{failed && <small className="inline-error">{t('catalog.documentPreviewError')}</small>}{previewUrl && <Modal title={filename} onClose={closePreview} wide><object className="generated-document-preview" data={previewUrl} type="application/pdf"><p>{t('document.previewFallback')}</p></object><div className="generated-document-preview-recovery" role="note"><p>{t('document.previewFallback')}</p><div><a className="secondary compact button-link" href={previewUrl} target="_blank" rel="noopener noreferrer"><ExternalLink size={15} />{t('document.openPdf')}</a><DownloadButton path={path} filename={filename} /></div></div></Modal>}</span>
}

export function AttachmentList({ items }: { items: StoredAttachment[] }) {
  const { date, t } = useI18n()
  return (
    <div className="document-list">
      {items.map((item) => <div key={item.id}><span><b>{item.filename}</b><small>{date(item.created_at)} · SHA-256 {item.sha256.slice(0, 12)}…</small></span><DownloadButton path={item.download_endpoint} filename={item.filename} /></div>)}
      {!items.length && <div className="empty-state">{t('passport.noAttachments')}</div>}
    </div>
  )
}
