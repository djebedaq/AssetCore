import { Settings } from 'lucide-react'
import { useI18n } from '../../i18n'
import { storedUser } from '../../permissions'
import { LanguageSwitcher } from '../../shell/LanguageSwitcher'
import GovernancePanel from './GovernancePanel'
import { AdministrationPanel } from './AdministrationPanel'

export default function SettingsPage() {
  const { t } = useI18n()
  const session = storedUser()
  return (
    <>
      <div className="panel">
        <div className="panel-title"><h3>{t('settings.title')}</h3><Settings /></div>
        <div className="settings-list">
          <div><b>{t('language.label')}</b><LanguageSwitcher compact /></div>
          <div><b>{t('settings.organization')}</b><span>{t('settings.organizationValue')}</span></div>
          <div><b>{t('settings.version')}</b><span>{t('settings.versionValue')}</span></div>
          <div><b>{t('settings.database')}</b><span>{t('settings.databaseValue')}</span></div>
        </div>
      </div>
      {session && <GovernancePanel session={session} />}
      <AdministrationPanel />
    </>
  )
}
