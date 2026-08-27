import { useI18n } from '../../i18n'
import SignaturePage from '../../SignaturePage'
import type { SigningTask } from '../../types'

// Presentation only: task order and required signatures come from the API response.
export function SignatureStep({ tasks, index, onFinished }: {
  tasks: SigningTask[]
  index: number
  onFinished: (outcome: 'DONE' | 'REJECTED') => void
}) {
  const { t } = useI18n()
  return <section className="integrated-signing"><div className="signing-progress"><strong>{t('bulk.signatureProgress', { current: index + 1, total: tasks.length })}</strong><span>{tasks[index].signer_name} · {tasks[index].operation_role}</span></div><SignaturePage embedded token={tasks[index].signing_token} onFinished={onFinished} /></section>
}
