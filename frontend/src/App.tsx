import { useEffect, useState } from 'react'
import { BarChart3, BookOpen, Boxes, ClipboardSignature, FileText, FileCheck2, Gauge, History, LogOut, Menu, PackageSearch, QrCode, Settings, ShieldCheck, UserRoundCog, Wrench, X } from 'lucide-react'
import { api, clearLegacyAuthStorage, logout } from './api'
import ChangePassword from './ChangePassword'
import { useI18n, type TranslationKey } from './i18n'
import { clearSessionUser, setSessionUser } from './permissions'
import type { EmergencyAccessStatus, PermissionCode, UserSession } from './types'
import ProfileCompletion from './ProfileCompletion'
import { useMobileNavigationLock } from './useMobileNavigationLock'
import { PendingPartsBadge } from './features/partRequests/PendingPartsBadge'
import Login from './features/auth/Login'
import { GlobalSearchBox } from './features/search/GlobalSearchBox'
import { LazyMachinePassportModal as MachinePassportModal } from './features/passport/LazyMachinePassportModal'
import { LanguageSwitcher } from './shell/LanguageSwitcher'
import { PageBoundary } from './shell/PageBoundary'
import { Dashboard, Machines, Transfers, IndustrialRepairs, IndustrialCatalog, IndustrialPartRequests, TechnicalLibrary, OfficialDocuments, Reports, Audit, QrCodes, UserAdministration, SettingsPage, SignaturePage } from './shell/lazyPages'

// Retained public imports; page implementations live in feature modules.
export { LanguageSwitcher } from './shell/LanguageSwitcher'
export { Repairs, PartCatalog, Documents } from './shell/legacyScreens'

type Page =
  | 'dashboard'
  | 'machines'
  | 'transfers'
  | 'repairs'
  | 'catalog'
  | 'parts'
  | 'documents'
  | 'official'
  | 'reports'
  | 'audit'
  | 'qr'
  | 'users'
  | 'password'
  | 'settings'

function App() {
  const { date, setLocale, t } = useI18n()
  const [authenticated, setAuthenticated] = useState(false)
  const [bootstrapping, setBootstrapping] = useState(true)
  const [session, setSession] = useState<UserSession | null>(null)
  const [page, setPage] = useState<Page>('dashboard')
  const [catalogMachineId, setCatalogMachineId] = useState<number | null>(null)
  const [mobileMenu, setMobileMenu] = useState(false)
  const [emergencyAccess, setEmergencyAccess] = useState<EmergencyAccessStatus | null>(null)
  const [passportMachineId, setPassportMachineId] = useState<number | null>(() => {
    const match = window.location.pathname.match(/^\/machine\/(\d+)\/?$/)
    return match ? Number(match[1]) : null
  })
  const signingMatch = window.location.pathname.match(/^\/sign\/([^/]+)\/?$/)

  useEffect(() => {
    clearLegacyAuthStorage()
    if (signingMatch) {
      setBootstrapping(false)
      return
    }
    let active = true
    void api<UserSession>('/auth/me')
      .then((user) => {
        if (!active) return
        setSessionUser(user)
        setSession(user)
        setAuthenticated(true)
        setLocale(user.preferred_language, false)
        setPage(user.permissions.includes('repairs.view') ? 'dashboard' : 'machines')
      })
      .catch(() => {
        if (!active) return
        clearSessionUser()
        setSession(null)
        setAuthenticated(false)
      })
      .finally(() => {
        if (active) setBootstrapping(false)
      })
    return () => { active = false }
  }, [])

  useEffect(() => {
    const unauthenticated = () => {
      clearSessionUser()
      setSession(null)
      setAuthenticated(false)
      setMobileMenu(false)
    }
    window.addEventListener('assetcore:unauthorized', unauthenticated)
    return () => window.removeEventListener('assetcore:unauthorized', unauthenticated)
  }, [])

  useMobileNavigationLock(mobileMenu && authenticated && Boolean(session))

  useEffect(() => {
    if (!authenticated || !session) {
      setEmergencyAccess(null)
      return
    }
    const loadEmergencyAccess = () => {
      void api<EmergencyAccessStatus>('/emergency-access/status')
        .then(setEmergencyAccess)
        .catch(() => setEmergencyAccess(null))
    }
    loadEmergencyAccess()
    window.addEventListener('assetcore-emergency-change', loadEmergencyAccess)
    const timer = window.setInterval(loadEmergencyAccess, 30_000)
    return () => {
      window.removeEventListener('assetcore-emergency-change', loadEmergencyAccess)
      window.clearInterval(timer)
    }
  }, [authenticated, session])

  if (signingMatch) return <PageBoundary><SignaturePage token={decodeURIComponent(signingMatch[1])} /></PageBoundary>

  if (bootstrapping) return <div className="login-shell"><div className="login-panel"><p>{t('common.loading')}</p></div></div>
  if (!authenticated || !session) return <Login onLogin={(user) => { setSessionUser(user); setSession(user); setAuthenticated(true); setPage(user.permissions.includes('repairs.view') ? 'dashboard' : 'machines') }} />
  if (session.must_change_password) return <ChangePassword forced onChanged={(user) => { setSessionUser(user); setSession(user); setPage(user.permissions.includes('repairs.view') ? 'dashboard' : 'machines') }} />
  if (session.profile_status === 'PROFILE_INCOMPLETE') return <ProfileCompletion user={session} onCompleted={(user) => { setSessionUser(user); setSession(user); setPage(user.permissions.includes('repairs.view') ? 'dashboard' : 'machines') }} />

  const nav = ([
    ['dashboard', 'nav.dashboard', Gauge, 'repairs.view'],
    ['machines', 'nav.machines', Boxes, 'assets.view'],
    ['transfers', 'nav.transfers', ClipboardSignature, 'transfers.view'],
    ['repairs', 'nav.repairs', Wrench, 'repairs.view'],
    ['catalog', 'nav.catalog', BookOpen, 'parts.view'],
    ['parts', 'nav.parts', PackageSearch, 'requests.view'],
    ['documents', 'nav.documents', FileText, 'documents.view'],
    ['official', 'nav.officialDocuments', FileCheck2, 'documents.view'],
    ['reports', 'nav.reports', BarChart3, 'audit.view_operational'],
    ['audit', 'nav.audit', History, 'audit.view_operational'],
    ['qr', 'nav.qr', QrCode, 'documents.generate'],
    ['users', 'nav.users', UserRoundCog, 'users.view'],
    ['settings', 'nav.settings', Settings, 'settings.manage'],
  ] as Array<[Exclude<Page, 'password'>, TranslationKey, typeof Gauge, PermissionCode]>).filter(([, , , permission]) => session.permissions.includes(permission))

  return (
    <div className="app-shell">
      {mobileMenu && <button className="sidebar-backdrop" aria-label={t('common.close')} onClick={() => setMobileMenu(false)} />}
      <aside className={mobileMenu ? 'sidebar open' : 'sidebar'}>
        <div className="brand">
          <div className="brand-mark small"><ShieldCheck size={22} /></div>
          <div><strong>AssetCore</strong><span>{t('app.brandSubtitle')}</span></div>
        </div>
        <nav className="sidebar-navigation">
          {nav.map(([id, label, Icon]) => (
            <button
              key={id}
              className={page === id ? 'active' : ''}
              onClick={() => {
                setPage(id)
                setCatalogMachineId(null)
                setMobileMenu(false)
              }}
            >
              <Icon size={19} /><span className="nav-label">{t(label)}</span>{id === 'parts' && <PendingPartsBadge canApprove={session.permissions.includes('requests.approve')} revalidationKey={page} />}
            </button>
          ))}
        </nav>
        <div className="sidebar-actions">
          <button className="logout" onClick={() => { setPage('password'); setMobileMenu(false) }}><UserRoundCog size={18} />{t('password.title')}</button>
          <button
            className="logout"
            onClick={() => {
              void logout().finally(() => {
                clearSessionUser()
                setSession(null)
                setAuthenticated(false)
                setMobileMenu(false)
              })
            }}
          >
            <LogOut size={18} />{t('app.logout')}
          </button>
        </div>
      </aside>
      <main>
        <header>
          <button
            className="mobile-toggle"
            onClick={() => setMobileMenu((value) => !value)}
            aria-label={mobileMenu ? t('common.close') : t('common.open')}
          >
            {mobileMenu ? <X /> : <Menu />}
          </button>
          <div className="header-copy">
            <h2>{page === 'password' ? t('password.title') : t(nav.find((item) => item[0] === page)?.[1] || 'nav.machines')}</h2>
            <p>{t('app.headerSubtitle')}</p>
          </div>
          <GlobalSearchBox onMachine={setPassportMachineId} />
          <LanguageSwitcher compact />
          {session.is_system_owner && <span className="owner-badge"><ShieldCheck size={15} />{t('governance.ownerBadge')}</span>}
        </header>
        {emergencyAccess?.active && <div className="emergency-access-banner" role="status"><ShieldCheck size={18} /><span><strong>{t('emergency.activeTitle')}</strong>{t('emergency.activeMessage', { owner: emergencyAccess.owner_name || t('common.noValue'), expires: emergencyAccess.expires_at ? date(emergencyAccess.expires_at) : t('common.noValue') })}</span></div>}
        <section className="content">
          <PageBoundary key={page}>
          {page === 'dashboard' && <Dashboard />}
          {page === 'machines' && <Machines onOpenCatalog={(machineId) => { setCatalogMachineId(machineId); setPage('catalog') }} />}
          {page === 'transfers' && <Transfers />}
          {page === 'repairs' && <IndustrialRepairs />}
          {page === 'catalog' && <IndustrialCatalog defaultMachineId={catalogMachineId || undefined} />}
          {page === 'parts' && <IndustrialPartRequests />}
          {page === 'documents' && <TechnicalLibrary />}
          {page === 'official' && <OfficialDocuments />}
          {page === 'reports' && <Reports />}
          {page === 'audit' && <Audit />}
          {page === 'qr' && <QrCodes />}
          {page === 'users' && <UserAdministration />}
          {page === 'settings' && <SettingsPage />}
          {page === 'password' && <ChangePassword onChanged={(user) => { setSession(user); setPage(user.permissions.includes('repairs.view') ? 'dashboard' : 'machines') }} onCancel={() => setPage(session.permissions.includes('repairs.view') ? 'dashboard' : 'machines')} />}
          </PageBoundary>
        </section>
        <footer className="application-footer">{t('app.copyright')}</footer>
      </main>
      {passportMachineId && <MachinePassportModal machineId={passportMachineId} onClose={() => setPassportMachineId(null)} onOpenCatalog={() => { setCatalogMachineId(passportMachineId); setPassportMachineId(null); setPage('catalog') }} />}
    </div>
  )
}

export default App
