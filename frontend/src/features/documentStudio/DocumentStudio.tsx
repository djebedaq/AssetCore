import { useEffect, useState } from 'react'
import { Building2, Files, MessageSquare, ShieldCheck } from 'lucide-react'
import { api } from '../../api'
import { useI18n } from '../../i18n'
import { hasPermission } from '../../permissions'
import { CompanyProfile } from './CompanyProfile'
import { TemplateLibrary } from './TemplateLibrary'
import { ProposalCenter } from './ProposalCenter'
import type { Draft } from './shared'
import './studio.css'

export default function DocumentStudio({ onDirty }: { onDirty: (dirty: boolean) => void }) {
  const { t } = useI18n()
  const [section, setSection] = useState<'company' | 'library' | 'proposals'>('company')
  const [pending, setPending] = useState(0), [proposalId, setProposalId] = useState<number | null>(null)
  const [requested, setRequested] = useState<{ templateId: number; draft: Draft | null } | null>(null)
  const [sent, setSent] = useState<number | null>(null)
  const [dirty, setDirty] = useState(false)
  useEffect(() => {
    let live = true
    if (hasPermission('studio.propose')) void api<{ pending_count: number }>('/studio/proposals?limit=1').then(p => { if (live) setPending(p.pending_count) }).catch(() => {})
    return () => { live = false }
  }, [])
  useEffect(() => { onDirty(dirty); return () => onDirty(false) }, [dirty, onDirty])
  useEffect(() => {
    const before = (event: BeforeUnloadEvent) => { if (dirty) event.preventDefault() }
    const navigate = (event: MouseEvent) => {
      if (dirty && event.target instanceof Element && event.target.closest('.sidebar-navigation button') && !window.confirm(t('studio.leave'))) {
        event.preventDefault(); event.stopPropagation()
      }
    }
    window.addEventListener('beforeunload', before)
    document.addEventListener('click', navigate, true)
    return () => { window.removeEventListener('beforeunload', before); document.removeEventListener('click', navigate, true) }
  }, [dirty, t])
  if (!hasPermission('studio.view')) return null
  return <section className="document-studio" aria-label={t('studio.title')}>
    <div className="studio-heading"><div><span className="studio-eyebrow"><ShieldCheck size={15} />{t('studio.foundation')}</span><h2>{t('studio.title')}</h2><p>{t('studio.subtitle')}</p></div>{!hasPermission('templates.manage') && <span className="badge">{t('studio.readOnly')}</span>}</div>
    <div className="studio-notice">{t('studio.foundationHint')}</div>
    <nav className="studio-navigation" aria-label={t('studio.title')}>{(['company', 'library', 'proposals'] as const).filter(value => value !== 'proposals' || hasPermission('studio.propose')).map(value => <button key={value} aria-current={section === value ? 'page' : undefined} onClick={() => { if (section !== value && (!dirty || window.confirm(t('studio.leave')))) { setSection(value); setSent(null) } }}>{value === 'company' ? <Building2 size={18} /> : value === 'library' ? <Files size={18} /> : <MessageSquare size={18} />}{t(value === 'proposals' ? 'proposal.center' : `studio.${value}`)}{value === 'proposals' && <span className="badge">{pending}</span>}</button>)}</nav>
    {sent !== null && <p className="studio-notice" role="status">{t('proposal.sent', { id: sent })}</p>}
    {section === 'company' ? <CompanyProfile onDirty={setDirty} /> : section === 'library' ? <TemplateLibrary key={`${requested?.templateId || ''}-${requested?.draft?.id || ''}`} requested={requested} onDirty={setDirty} proposed={id => { setProposalId(id); setSent(id); setPending(n => n + 1); setSection('proposals') }} /> : <ProposalCenter initialId={proposalId} onDirty={setDirty} pendingChanged={setPending} openTemplate={id => { setRequested({ templateId: id, draft: null }); setSection('library') }} openDraft={draft => { setRequested({ templateId: draft.template_id, draft }); setSection('library') }} />}
  </section>
}
