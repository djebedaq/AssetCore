import { ApiError } from '../../api'
import { statusText, useI18n, type TranslationKey } from '../../i18n'

export function localizedErrorKey(error: Error): TranslationKey {
  if (!(error instanceof ApiError)) return 'errors.generic'
  if (error.status === 403) return 'errors.permissionDenied'
  if (error.status === 404) return 'errors.notFound'
  if (error.code === 'issue_conflict' || error.code === 'concurrent_issue_conflict') return 'errors.issueConflict'
  if (error.code === 'return_conflict' || error.code === 'return_without_active_transfer') return 'errors.returnConflict'
  if (error.code === 'document_template_unavailable') return 'errors.templateUnavailable'
  if (error.code === 'validation_error') return 'errors.validation'
  if (error.code === 'batch_not_pending') return 'errors.batchNotPending'
  if (error.code === 'batch_not_found') return 'errors.notFound'
  return 'errors.generic'
}

export function ConflictNotice({ error }: { error: Error | null }) {
  const { date, t } = useI18n()
  if (!error) return null
  const conflicts = error instanceof ApiError && Array.isArray(error.data.conflicts)
    ? error.data.conflicts as Array<Record<string, unknown>>
    : []
  const diagnosticId = error instanceof ApiError && typeof error.data.diagnostic_id === 'string'
    ? error.data.diagnostic_id
    : null
  const diagnosticStage = error instanceof ApiError && typeof error.data.stage_label === 'string'
    ? error.data.stage_label
    : error instanceof ApiError && typeof error.data.stage === 'string'
      ? error.data.stage
      : null
  const serverMessage = error instanceof ApiError
    && error.code === 'bulk_return_internal_error'
    && typeof error.data.message === 'string'
      ? error.data.message
      : null
  return (
    <div className="conflict-notice" role="alert">
      <strong>{serverMessage || t(localizedErrorKey(error))}</strong>
      {diagnosticId && <p><b>{t('bulk.diagnosticCode')}:</b> <code>{diagnosticId}</code>{diagnosticStage ? <> · <b>{t('bulk.diagnosticStage')}:</b> {diagnosticStage}</> : null}</p>}
      {conflicts.length > 0 && (
        <ul>
          {conflicts.map((conflict, index) => (
            <li key={String(conflict.transfer_id || conflict.machine_id || index)}>
              <b>{t('bulk.machineName', { number: String(conflict.machine_number || t('common.noValue')) })}</b>
              {conflict.status ? ` · ${statusText(t, String(conflict.status))}` : ''}
              {conflict.protocol_number ? ` · ${t('errors.protocol', { protocol: String(conflict.protocol_number) })}` : ''}
              {conflict.issued_at ? ` · ${t('errors.issuedAt', { date: date(String(conflict.issued_at)) })}` : ''}
              {conflict.current_recipient_or_location ? ` · ${String(conflict.current_recipient_or_location)}` : ''}
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
