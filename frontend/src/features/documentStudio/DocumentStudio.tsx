import { useEffect, useState } from 'react'
import { Building2, Files, ShieldCheck } from 'lucide-react'
import { useI18n } from '../../i18n'
import { hasPermission } from '../../permissions'
import { CompanyProfile } from './CompanyProfile'
import { TemplateLibrary } from './TemplateLibrary'
import './studio.css'

export default function DocumentStudio({ onDirty }: { onDirty: (dirty: boolean) => void }) {
  const { t } = useI18n()
  const [section, setSection] = useState<'company' | 'library'>('company')
  const [dirty, setDirty] = useState(false)
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
    <nav className="studio-navigation" aria-label={t('studio.title')}>{(['company', 'library'] as const).map(value => <button key={value} aria-current={section === value ? 'page' : undefined} onClick={() => { if (section !== value && (!dirty || window.confirm(t('studio.leave')))) setSection(value) }}>{value === 'company' ? <Building2 size={18} /> : <Files size={18} />}{t(`studio.${value}`)}</button>)}</nav>
    {section === 'company' ? <CompanyProfile onDirty={setDirty} /> : <TemplateLibrary onDirty={setDirty} />}
  </section>
}
