import { ArrowUpRight, Check, Clock, CircleHelp, OctagonAlert, Wrench } from 'lucide-react'
import { statusText, useI18n, type StatusDomain } from '../i18n'

type Tone = 'success' | 'info' | 'attention' | 'neutral' | 'error'
const semantics: Record<StatusDomain, Record<string, Tone>> = {
  machine: { READY: 'success', ISSUED: 'info', REPAIR: 'attention', RETURNED: 'success' },
  repair: { ACCEPTED: 'neutral', DIAGNOSIS: 'attention', WAITING_APPROVAL: 'neutral', WAITING_PARTS: 'neutral', REPAIRING: 'attention', TESTING: 'attention', COMPLETED: 'success' },
  part: { DRAFT: 'neutral', SUBMITTED: 'neutral', WAITING_APPROVAL: 'neutral', APPROVED: 'success', REJECTED: 'neutral', RETURNED_FOR_CHANGES: 'attention', ORDERED: 'info', PARTIALLY_DELIVERED: 'info', DELIVERED: 'success', CANCELLED: 'neutral' },
  batch: { ACTIVE: 'info', PARTIALLY_RETURNED: 'info', RETURNED: 'success', COMPLETED: 'success', AWAITING_SIGNATURE: 'neutral', CANCELLED: 'neutral' },
}
const icons = { success: Check, info: ArrowUpRight, attention: Wrench, neutral: Clock, error: OctagonAlert }
export function statusTone(status: string, domain: StatusDomain = 'machine'): Tone { return semantics[domain][status] || 'neutral' }

export function StatusBadge({ status, domain = 'machine', label }: { status: string; domain?: StatusDomain; label?: string }) {
  const { t } = useI18n()
  const known = Boolean(semantics[domain][status])
  const tone = statusTone(status, domain)
  const Icon = known ? icons[tone] : CircleHelp
  return <span className={`badge ac-status ac-status-${tone}`} data-status-domain={domain} data-status={status}>
    <Icon size={13} aria-hidden="true" /><span>{label || (status === 'RETURNED' && domain === 'machine' ? t('transfers.returned') : status === 'AWAITING_SIGNATURE' ? t('bulk.awaitingSignature') : statusText(t, status, domain))}</span>
  </span>
}
