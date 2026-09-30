import { useI18n } from '../../i18n'
import { problemKeys, type Issue, type Workflow } from './wizardTypes'

export default function WizardReview({ workflow, editable, busy, onFix, onPublish }: {
  workflow: Workflow | null; editable: boolean; busy: boolean; onFix: (issue: Issue) => void; onPublish: () => void
}) {
  const { t } = useI18n()
  if (!workflow) return <p>{t('wizard.loading')}</p>
  return <div className="builder-workspace">
    <p>{t('wizard.reviewHelp')}</p>
    <p>{t('wizard.summary', workflow.summary)}</p>
    <p>{t('wizard.progress', workflow.progress)}</p>
    {editable && <>
      <p role="status"><b>{t(workflow.ready ? 'builder.publication.ready' : 'builder.publication.notReady')}</b></p>
      <ul className="wizard-readiness">{[...workflow.errors, ...workflow.warnings].map((issue, index) => <li key={index}>
        <span>{t(problemKeys[issue.code] || 'builder.error.generic', { count: issue.missing_positions || 0 })}</span>
        <button className="secondary" disabled={busy} onClick={() => onFix(issue)}>{t('wizard.fix')}</button>
      </li>)}</ul>
      <button className="primary" disabled={busy || !workflow.ready || workflow.summary.part_count === 0} onClick={onPublish}>
        {t(workflow.current_published_revision_id ? 'wizard.publishUpdate' : 'wizard.publish')}
      </button>
    </>}
  </div>
}
