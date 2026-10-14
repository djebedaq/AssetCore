import { useI18n } from '../../i18n'
import { problemKeys, type Group, type Issue, type Workflow } from './wizardTypes'

export default function WizardReview({ workflow, editable, busy, onFix, onPublish, groups = [], catalogName, revisionCode }: {
  groups?: Group[]; catalogName?: string; revisionCode?: string; workflow: Workflow | null; editable: boolean; busy: boolean; onFix: (issue: Issue) => void; onPublish: () => void
}) {
  const { t, locale } = useI18n()
  if (!workflow) return <p>{t('wizard.loading')}</p>
  return <div className="builder-workspace">
    <h4>{catalogName} · {revisionCode}</h4><p>{t('wizard.reviewHelp')}</p>
    <p>{t('wizard.summary', workflow.summary)}</p>
    <p>{t('wizard.progress', workflow.progress)}</p>
    {workflow.summary.reviewed_source_count !== undefined && <p>{t('catalogUx.reviewedSources', { done: workflow.summary.reviewed_source_count, total: workflow.summary.spare_list_page_count })}</p>}
    {editable && <>
      <p role="status"><b>{t(workflow.ready ? 'builder.publication.ready' : 'builder.publication.notReady')}</b></p>
      {(['errors', 'warnings'] as const).map(severity => workflow[severity].length > 0 && <section key={severity}>
        <h4>{t(`wizard.${severity}`)} ({workflow[severity].length})</h4>
        <ul className="wizard-readiness">{workflow[severity].map((issue, index) => <li key={index}>
          <span><b>{groups.find(group => group.id === issue.assembly_id)?.[`name_${locale}`] || ''}</b>
            {issue.position && <> · {t('guided.position')} {issue.position}</>}
            {issue.page_number && <> · {t('guided.physicalPage', { number: issue.page_number })}</>}
            {issue.filename && <small>{issue.filename}</small>}
            <br />{t(problemKeys[issue.code] || 'builder.error.generic', { count: issue.missing_positions || 0 })}</span>
          <button className="secondary" disabled={busy} onClick={() => onFix(issue)}>{t(severity === 'errors' ? 'wizard.fix' : 'ux05.inspect')}</button>
        </li>)}</ul>
      </section>)}
      <button className="primary" disabled={busy || !workflow.ready || workflow.summary.part_count === 0} onClick={onPublish}>
        {t(workflow.current_published_revision_id ? 'wizard.publishUpdate' : 'wizard.publish')}
      </button>
    </>}
  </div>
}
