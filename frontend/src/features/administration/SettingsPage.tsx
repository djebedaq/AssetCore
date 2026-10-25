import { lazy, Suspense, useState } from 'react'
import { Settings } from 'lucide-react'
import { useI18n } from '../../i18n'
import { hasPermission, storedUser } from '../../permissions'
import { LanguageSwitcher } from '../../shell/LanguageSwitcher'
import GovernancePanel from './GovernancePanel'
import { AdministrationPanel } from './AdministrationPanel'
import '../documentStudio/studio.css'
const DocumentStudio = lazy(() => import('../documentStudio/DocumentStudio'))

export default function SettingsPage() {
  const { t } = useI18n()
  const session = storedUser()
  const manageSettings = hasPermission('settings.manage')
  const [studio, setStudio] = useState(!manageSettings)
  const [dirty, setDirty] = useState(false)
  return (
    <>
      <nav className="studio-settings-tabs" aria-label={t('settings.title')}>
        {manageSettings && <button aria-current={!studio ? 'page' : undefined} onClick={() => { if (!dirty || window.confirm(t('studio.leave'))) setStudio(false) }}>{t('settings.title')}</button>}
        {hasPermission('studio.view') && <button aria-current={studio ? 'page' : undefined} onClick={() => setStudio(true)}>{t('studio.title')}</button>}
      </nav>
      {studio ? <Suspense fallback={<p>{t('studio.loading')}</p>}><DocumentStudio onDirty={setDirty} /></Suspense> : <>
      <div className="panel">
        <div className="panel-title"><h3>{t('settings.title')}</h3><Settings /></div>
        <div className="settings-list">
          <div><b>{t('language.label')}</b><LanguageSwitcher compact /></div>
          <div><b>{t('settings.version')}</b><span>{t('settings.versionValue')}</span></div>
          <div><b>{t('settings.database')}</b><span>{t('settings.databaseValue')}</span></div>
        </div>
      </div>
      {manageSettings && session && <GovernancePanel session={session} />}
      {manageSettings && <AdministrationPanel openStudio={() => setStudio(true)} />}
      </>}
    </>
  )
}
