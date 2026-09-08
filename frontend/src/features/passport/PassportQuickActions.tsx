import { BookOpen, FileText, FolderOpen, RotateCcw, Send, Wrench } from 'lucide-react'
import { useI18n } from '../../i18n'
import { hasPermission } from '../../permissions'
import type { MachinePassport } from '../../types'
import type { MachineEntryIntent } from './machineEntryIntent'

export function PassportQuickActions({ passport, onWorkflow, onCatalog, onTab }: {
  passport: MachinePassport
  onWorkflow?: (intent: MachineEntryIntent) => void
  onCatalog?: () => void
  onTab: (tab: 'protocols' | 'files') => void
}) {
  const { t } = useI18n()
  if (passport.limited_view) return null
  const { machine, current_state: state } = passport
  const active = machine.is_active === true
  return <section className="passport-quick-actions" aria-label={t('entry.quickActions')}>
    <h3>{t('entry.quickActions')}</h3><div>
      {onWorkflow && active && hasPermission('transfers.view') && state.allowed_actions.issue && <button type="button" className="primary" onClick={() => onWorkflow({ action: 'issue', machineId: machine.id })}><Send size={17} aria-hidden="true" />{t('entry.issue')}</button>}
      {onWorkflow && active && hasPermission('transfers.view') && state.allowed_actions.return && <button type="button" className="secondary" onClick={() => onWorkflow({ action: 'return', machineId: machine.id })}><RotateCcw size={17} aria-hidden="true" />{t('entry.return')}</button>}
      {onWorkflow && hasPermission('repairs.view') && (state.active_repair
        ? <button type="button" className="secondary" onClick={() => onWorkflow({ action: 'repair-open', machineId: machine.id, repairId: state.active_repair!.id })}><Wrench size={17} aria-hidden="true" />{t('entry.openRepair')}</button>
        : active && state.allowed_actions.repair && <button type="button" className="secondary" onClick={() => onWorkflow({ action: 'repair-create', machineId: machine.id })}><Wrench size={17} aria-hidden="true" />{t('entry.startRepair')}</button>)}
      {onCatalog && hasPermission('parts.view') && <button type="button" className="secondary" onClick={onCatalog}><BookOpen size={17} aria-hidden="true" />{t('nav.catalog')}</button>}
      {hasPermission('documents.view') && <button type="button" className="secondary" onClick={() => onTab('protocols')}><FileText size={17} aria-hidden="true" />{t('passport.tab.protocols')}</button>}
      {active && hasPermission('repairs.edit') && <button type="button" className="secondary" onClick={() => onTab('files')}><FolderOpen size={17} aria-hidden="true" />{t('passport.tab.files')}</button>}
    </div>
  </section>
}
