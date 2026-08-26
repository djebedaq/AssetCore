import { type FormEvent, type ReactNode, useEffect, useMemo, useState } from 'react'
import {
  BarChart3,
  BookOpen,
  Boxes,
  ClipboardSignature,
  Download,
  FileText,
  FileCheck2,
  Gauge,
  History,
  Languages,
  LogOut,
  Menu,
  PackageSearch,
  Plus,
  QrCode,
  Search,
  Settings,
  ShieldCheck,
  UserRoundCog,
  Wrench,
  X,
} from 'lucide-react'
import { api, clearLegacyAuthStorage, downloadApiFile, logout } from './api'
import AuthenticatedImage from './AuthenticatedImage'
import BulkTransfers from './BulkTransfers'
import ChangePassword from './ChangePassword'
import {
  AdministrationPanel,
  GlobalSearchBox,
  IndustrialCatalog,
  IndustrialPartRequests,
  IndustrialRepairs,
  MachinePassportModal,
  TechnicalLibrary,
} from './IndustrialPlatform'
import { statusText, useI18n, type TranslationKey } from './i18n'
import { SUPPORTED_LOCALES, type Locale } from './locale'
import { clearSessionUser, hasPermission, setSessionUser, storedUser } from './permissions'
import type { AssetCategory, Department, EmergencyAccessStatus, Location, Machine, PermissionCode, UserSession } from './types'
import UserAdministration from './UserAdministration'
import GovernancePanel from './GovernancePanel'
import OfficialDocuments from './OfficialDocuments'
import ProfileCompletion from './ProfileCompletion'
import SignaturePage from './SignaturePage'
import { useMobileNavigationLock } from './useMobileNavigationLock'
import { PendingPartsBadge } from './features/partRequests/PendingPartsBadge'

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

type DashboardData = {
  total_machines: number
  ready: number
  in_use: number
  open_repairs: number
  pending_parts: number
  status_breakdown: Record<string, number>
  recent_repairs: Array<{
    id: number
    machine: string
    problem: string
    status: string
  }>
}

type TransferRecord = {
  id: number
  protocol_number: string
  batch_reference?: string | null
  is_active: boolean
  company_unit?: string | null
  vessel?: string | null
  location_text?: string | null
  issued_at?: string | null
  returned_at?: string | null
  created_at: string
  machine: Machine
}

type CatalogPart = {
  id: number
  brand: string
  model?: string | null
  assembly?: string | null
  position?: string | null
  part_number: string
  description: string
  quantity?: number | null
  source_document?: string | null
  source_page?: number | null
}

type TechnicalDocument = {
  id: number
  brand: string
  category: string
  title: string
}

type AuditEntry = {
  id: number
  created_at: string
  user_name?: string | null
  entity_type: string
  entity_id?: number | null
  action: string
  details?: string | null
  operation_reference?: string | null
}

const MACHINE_STATUS_CODES = [
  'READY',
  'ISSUED',
  'REPAIR',
]

export function LanguageSwitcher({ compact = false }: { compact?: boolean }) {
  const { locale, setLocale, t } = useI18n()
  return (
    <label className={compact ? 'language-switch compact-language' : 'language-switch'}>
      <Languages size={17} aria-hidden="true" />
      <span className="sr-only">{t('language.label')}</span>
      <select
        aria-label={t('language.label')}
        value={locale}
        onChange={(event) => setLocale(event.target.value as Locale)}
      >
        {SUPPORTED_LOCALES.map((language) => (
          <option key={language} value={language}>{t(`language.${language}`)}</option>
        ))}
      </select>
    </label>
  )
}

function Login({ onLogin }: { onLogin: (user: UserSession) => void }) {
  const { setLocale, t } = useI18n()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  async function submit(event: FormEvent) {
    event.preventDefault()
    setBusy(true)
    setError('')
    try {
      const data = await api<{ user: UserSession }>('/auth/login', {
        method: 'POST',
        body: JSON.stringify({ email, password }),
      })
      setSessionUser(data.user)
      setLocale(data.user.preferred_language, false)
      onLogin(data.user)
    } catch {
      setError(t('login.error'))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="login-shell">
      <div className="login-panel">
        <div className="login-language"><LanguageSwitcher compact /></div>
        <div className="brand-mark"><ShieldCheck size={30} /></div>
        <h1>AssetCore</h1>
        <p>{t('login.subtitle')}</p>
        <form onSubmit={submit}>
          <label>
            {t('login.email')}
            <input
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              type="email"
              autoComplete="username"
              placeholder={t('login.emailPlaceholder')}
              required
            />
          </label>
          <label>
            {t('login.password')}
            <input
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              type="password"
              autoComplete="current-password"
              placeholder={t('login.passwordPlaceholder')}
              required
            />
          </label>
          {error && <div className="error" role="alert">{error}</div>}
          <button disabled={busy}>{busy ? t('login.signingIn') : t('login.signIn')}</button>
        </form>
      </div>
    </div>
  )
}

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

  if (signingMatch) return <SignaturePage token={decodeURIComponent(signingMatch[1])} />

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
        </section>
        <footer className="application-footer">{t('app.copyright')}</footer>
      </main>
      {passportMachineId && <MachinePassportModal machineId={passportMachineId} onClose={() => setPassportMachineId(null)} onOpenCatalog={() => { setCatalogMachineId(passportMachineId); setPassportMachineId(null); setPage('catalog') }} />}
    </div>
  )
}

function Dashboard() {
  const { t, number } = useI18n()
  const [data, setData] = useState<DashboardData | null>(null)
  const [error, setError] = useState(false)

  useEffect(() => {
    void api<DashboardData>('/dashboard').then(setData).catch(() => setError(true))
  }, [])

  if (error) return <div className="error" role="alert">{t('errors.generic')}</div>
  if (!data) return <div className="loading">{t('common.loading')}</div>

  const cards = [
    ['dashboard.totalMachines', data.total_machines, Boxes],
    ['dashboard.ready', data.ready, ShieldCheck],
    ['dashboard.inUse', data.in_use, Gauge],
    ['dashboard.openRepairs', data.open_repairs, Wrench],
    ['dashboard.pendingRequests', data.pending_parts, PackageSearch],
  ] as const

  return (
    <>
      <div className="stats-grid">
        {cards.map(([label, value, Icon]) => (
          <div className="stat-card" key={label}>
            <div className="stat-icon"><Icon size={23} /></div>
            <div><span>{t(label)}</span><strong>{number(value)}</strong></div>
          </div>
        ))}
      </div>
      <div className="panel-grid">
        <div className="panel">
          <div className="panel-title"><h3>{t('dashboard.machineStatus')}</h3><BarChart3 /></div>
          <div className="status-list">
            {Object.entries(data.status_breakdown).map(([status, count]) => (
              <div key={status}>
                <span>{statusText(t, status)}</span>
                <div className="bar">
                  <i style={{ width: `${Math.max(8, (count / Math.max(data.total_machines, 1)) * 100)}%` }} />
                </div>
                <b>{number(count)}</b>
              </div>
            ))}
          </div>
        </div>
        <div className="panel">
          <div className="panel-title"><h3>{t('dashboard.recentRepairs')}</h3><Wrench /></div>
          <div className="activity-list">
            {data.recent_repairs.length ? data.recent_repairs.map((repair) => (
              <div key={repair.id}>
                <strong>{repair.machine}</strong>
                <span>{repair.problem}</span>
                <em>{statusText(t, repair.status, 'repair')}</em>
              </div>
            )) : <p className="muted">{t('dashboard.noRepairs')}</p>}
          </div>
        </div>
      </div>
    </>
  )
}

function Machines({ onOpenCatalog }: { onOpenCatalog: (machineId: number) => void }) {
  const { t } = useI18n()
  const [items, setItems] = useState<Machine[]>([])
  const [locations, setLocations] = useState<Location[]>([])
  const [departments, setDepartments] = useState<Department[]>([])
  const [categories, setCategories] = useState<AssetCategory[]>([])
  const [query, setQuery] = useState('')
  const [selected, setSelected] = useState<Machine | null>(null)
  const [showNew, setShowNew] = useState(false)
  const [passportId, setPassportId] = useState<number | null>(null)
  const [error, setError] = useState(false)
  const showTechnicalDetails = hasPermission('documents.view')

  const load = () => (showTechnicalDetails
    ? Promise.all([api<Machine[]>('/machines'), api<Location[]>('/locations'), api<AssetCategory[]>('/categories'), api<Department[]>('/departments')])
    : api<Machine[]>('/machines').then((machines) => [machines, [], [], []] as [Machine[], Location[], AssetCategory[], Department[]]))
    .then(([machines, locationItems, categoryItems, departmentItems]) => {
      setItems(machines)
      setLocations(locationItems)
      setCategories(categoryItems)
      setDepartments(departmentItems)
      setError(false)
    })
    .catch(() => setError(true))

  useEffect(() => { void load() }, [])

  const filtered = useMemo(() => items.filter((machine) => (
    `${machine.inventory_number} ${machine.name} ${machine.brand} ${machine.model || ''} ${statusText(t, machine.status)} ${machine.location?.name || ''}`
      .toLowerCase()
      .includes(query.toLowerCase())
  )), [items, query, t])

  return (
    <>
      <div className="toolbar">
        <div className="search">
          <Search size={18} />
          <input
            aria-label={t('common.search')}
            placeholder={t('machines.searchPlaceholder')}
            value={query}
            onChange={(event) => setQuery(event.target.value)}
          />
        </div>
        {hasPermission('assets.create') && (
          <button className="primary" onClick={() => setShowNew(true)}><Plus size={18} />{t('machines.new')}</button>
        )}
      </div>
      {error && <div className="error" role="alert">{t('errors.generic')}</div>}
      <div className="table-card">
        <table>
          <thead><tr>
            <th>{t('machines.columnMachine')}</th><th>{t('machines.columnBrand')}</th>
            {showTechnicalDetails && <th>{t('machines.columnPressure')}</th>}<th>{t('machines.columnStatus')}</th>
            <th>{t('machines.columnLocation')}</th><th />
          </tr></thead>
          <tbody>
            {filtered.map((machine) => (
              <tr key={machine.id}>
                <td><strong>{machine.name}</strong><small>{t('machines.inventoryPrefix', { number: machine.inventory_number })}</small></td>
                <td>{machine.brand}<small>{machine.model}</small></td>
                {showTechnicalDetails && <td>{machine.pressure_bar} bar</td>}
                <td><span className="badge">{statusText(t, machine.status)}</span></td>
                <td>{machine.location?.name || t('common.notSpecified')}</td>
                <td><button className="link" onClick={() => setPassportId(machine.id)}>{t('passport.tab.passport')}</button>{hasPermission('assets.edit') && <button className="link" onClick={() => setSelected(machine)}>{t('common.details')}</button>}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {!filtered.length && <div className="empty-state">{t('machines.empty')}</div>}
      </div>
      {selected && (
        <MachineModal
          machine={selected}
          locations={locations}
          departments={departments}
          categories={categories}
          onClose={() => setSelected(null)}
          onSaved={() => {
            setSelected(null)
            void load()
          }}
        />
      )}
      {showNew && (
        <MachineModal
          locations={locations}
          departments={departments}
          categories={categories}
          onClose={() => setShowNew(false)}
          onSaved={() => {
            setShowNew(false)
            void load()
          }}
        />
      )}
      {passportId && <MachinePassportModal machineId={passportId} onClose={() => setPassportId(null)} onOpenCatalog={() => { setPassportId(null); onOpenCatalog(passportId) }} />}
    </>
  )
}

type MachineForm = {
  inventory_number: string
  name: string
  category: string
  brand: string
  model: string
  serial_number: string
  pressure_bar: number
  status: string
  location_id: number | ''
  notes: string
  category_id: number | ''
  asset_type: string
  subtype: string
  manufacturer: string
  manufacture_year: number | ''
  commissioning_date: string
  ownership: string
  department: string
  responsible_person: string
  capacity: string
  dimensions: string
  is_active: boolean
}

function MachineModal({ machine, locations, departments, categories, onClose, onSaved }: {
  machine?: Machine
  locations: Location[]
  departments: Department[]
  categories: AssetCategory[]
  onClose: () => void
  onSaved: () => void
}) {
  const { locale, t } = useI18n()
  const [form, setForm] = useState<MachineForm>({
    inventory_number: machine?.inventory_number || '',
    name: machine?.name || '',
    category: machine?.category || 'HPWJ',
    brand: machine?.brand || '',
    model: machine?.model || '',
    serial_number: machine?.serial_number || '',
    pressure_bar: machine?.pressure_bar || 500,
    status: machine?.status || 'READY',
    location_id: machine?.location_id || locations.find((item) => item.is_active)?.id || '',
    notes: machine?.notes || '',
    category_id: machine?.category_id || categories.find((item) => item.code === machine?.category)?.id || '',
    asset_type: machine?.asset_type || '',
    subtype: machine?.subtype || '',
    manufacturer: machine?.manufacturer || '',
    manufacture_year: machine?.manufacture_year || '',
    commissioning_date: machine?.commissioning_date?.slice(0, 10) || '',
    ownership: machine?.ownership || '',
    department: machine?.department || '',
    responsible_person: machine?.responsible_person || '',
    capacity: machine?.capacity || '',
    dimensions: machine?.dimensions || '',
    is_active: machine?.is_active ?? true,
  })
  const [error, setError] = useState('')
  const canEdit = !machine ? hasPermission('assets.create') : hasPermission('assets.edit')

  async function save(event: FormEvent) {
    event.preventDefault()
    setError('')
    try {
      await api(machine ? `/machines/${machine.id}` : '/machines', {
        method: machine ? 'PATCH' : 'POST',
        body: JSON.stringify({ ...form, category_id: form.category_id || null, location_id: form.location_id || null, manufacture_year: form.manufacture_year || null, commissioning_date: form.commissioning_date || null }),
      })
      onSaved()
    } catch {
      setError(t('machines.saveError'))
    }
  }

  const field = <K extends keyof MachineForm>(name: K, value: MachineForm[K]) => {
    setForm((current) => ({ ...current, [name]: value }))
  }

  return (
    <div className="modal-bg">
      <div className="modal" role="dialog" aria-modal="true" aria-label={machine ? t('machines.editTitle') : t('machines.newTitle')}>
        <div className="modal-head">
          <h3>{machine ? t('machines.editTitle') : t('machines.newTitle')}</h3>
          <button onClick={onClose} aria-label={t('common.close')}><X /></button>
        </div>
        <form onSubmit={save} className="form-grid">
          <label>{t('machines.inventoryNumber')}<input required disabled={Boolean(machine)} value={form.inventory_number} onChange={(event) => field('inventory_number', event.target.value)} /></label>
          <label>{t('machines.name')}<input required disabled={!canEdit} value={form.name} onChange={(event) => field('name', event.target.value)} /></label>
          <label>{t('machines.category')}<select required disabled={!canEdit} value={form.category_id} onChange={(event) => { const selectedCategory = categories.find((item) => item.id === Number(event.target.value)); field('category_id', event.target.value ? Number(event.target.value) : ''); if (selectedCategory) field('category', selectedCategory.code) }}><option value="">{t('common.notSpecified')}</option>{categories.map((category) => <option value={category.id} key={category.id}>{category[`name_${locale}` as 'name_bg'] || category.name_bg}</option>)}</select></label>
          <label>{t('machines.brand')}<input required disabled={!canEdit} value={form.brand} onChange={(event) => field('brand', event.target.value)} /></label>
          <label>{t('machines.model')}<input disabled={!canEdit} value={form.model} onChange={(event) => field('model', event.target.value)} /></label>
          <label>{t('machines.serialNumber')}<input disabled={!canEdit} value={form.serial_number} onChange={(event) => field('serial_number', event.target.value)} /></label>
          <label>{t('machines.pressure')}<input disabled={!canEdit} type="number" min="0" value={form.pressure_bar} onChange={(event) => field('pressure_bar', Number(event.target.value))} /></label>
          <label>{t('common.status')}<select disabled={!canEdit} value={form.status} onChange={(event) => field('status', event.target.value)}>{MACHINE_STATUS_CODES.map((status) => <option key={status} value={status}>{statusText(t, status)}</option>)}</select></label>
          <label>{t('common.location')}<select disabled={!canEdit} value={form.location_id} onChange={(event) => field('location_id', event.target.value ? Number(event.target.value) : '')}><option value="">{t('common.notSpecified')}</option>{locations.map((location) => <option disabled={!location.is_active && location.id !== form.location_id} key={location.id} value={location.id}>{location.name}{!location.is_active ? ` · ${t('admin.inactive')}` : ''}</option>)}</select></label>
          <label>{t('passport.manufacturer')}<input disabled={!canEdit} value={form.manufacturer} onChange={(event) => field('manufacturer', event.target.value)} /></label>
          <label>{t('passport.manufactureYear')}<input disabled={!canEdit} type="number" min="1800" max="2200" value={form.manufacture_year} onChange={(event) => field('manufacture_year', event.target.value ? Number(event.target.value) : '')} /></label>
          <label>{t('machines.assetType')}<input disabled={!canEdit} value={form.asset_type} onChange={(event) => field('asset_type', event.target.value)} /></label>
          <label>{t('machines.subtype')}<input disabled={!canEdit} value={form.subtype} onChange={(event) => field('subtype', event.target.value)} /></label>
          <label>{t('machines.commissioningDate')}<input disabled={!canEdit} type="date" value={form.commissioning_date} onChange={(event) => field('commissioning_date', event.target.value)} /></label>
          <label>{t('machines.ownership')}<input disabled={!canEdit} value={form.ownership} onChange={(event) => field('ownership', event.target.value)} /></label>
          <label>{t('passport.department')}<select disabled={!canEdit} value={form.department} onChange={(event) => field('department', event.target.value)}><option value="">{t('common.notSpecified')}</option>{form.department && !departments.some((item) => item.code === form.department) && <option value={form.department}>{form.department}</option>}{departments.map((department) => <option disabled={!department.is_active && department.code !== form.department} value={department.code} key={department.id}>{department[`name_${locale}` as 'name_bg'] || department.name_bg} · {department.code}{!department.is_active ? ` · ${t('admin.inactive')}` : ''}</option>)}</select></label>
          <label>{t('passport.responsible')}<input disabled={!canEdit} value={form.responsible_person} onChange={(event) => field('responsible_person', event.target.value)} /></label>
          <label>{t('machines.capacity')}<input disabled={!canEdit} value={form.capacity} onChange={(event) => field('capacity', event.target.value)} /></label>
          <label>{t('machines.dimensions')}<input disabled={!canEdit} value={form.dimensions} onChange={(event) => field('dimensions', event.target.value)} /></label>
          <label className="check-label"><input disabled={!canEdit} type="checkbox" checked={form.is_active} onChange={(event) => field('is_active', event.target.checked)} />{t('machines.active')}</label>
          <label className="wide">{t('machines.notes')}<textarea disabled={!canEdit} value={form.notes} onChange={(event) => field('notes', event.target.value)} /></label>
          {machine && <div className="qr-box"><AuthenticatedImage src={`/machines/${machine.id}/qr`} alt={t('machines.qrAlt', { number: machine.inventory_number })} /><span>{t('machines.qrLabel')}</span></div>}
          {error && <div className="error wide" role="alert">{error}</div>}
          <div className="actions wide">
            <button type="button" className="secondary" onClick={onClose}>{t('common.cancel')}</button>
            {canEdit && <button className="primary">{t('common.save')}</button>}
          </div>
        </form>
      </div>
    </div>
  )
}

export function Repairs() {
  return <IndustrialRepairs />
}

function Reports() {
  const { t } = useI18n()
  const [error, setError] = useState('')
  const download = () => downloadApiFile('/reports/daily.pdf', 'assetcore-daily-report.pdf')
    .catch(() => setError(t('reports.downloadError')))
  return (
    <div className="panel">
      <div className="panel-title"><div><h3>{t('reports.title')}</h3><p className="muted">{t('reports.subtitle')}</p></div><FileText /></div>
      {error && <div className="error" role="alert">{error}</div>}
      <div className="report-options"><button className="primary" onClick={download}>{t('reports.downloadDaily')}</button><div className="report-description">{t('reports.description')}</div></div>
    </div>
  )
}

function QrCodes() {
  const { t } = useI18n()
  const [machines, setMachines] = useState<Machine[]>([])
  useEffect(() => { void api<Machine[]>('/machines').then(setMachines).catch(() => undefined) }, [])
  return (<>
    <div className="toolbar qr-toolbar"><div><h3>{t('nav.qr')}</h3></div><button className="primary" onClick={() => window.print()}>{t('qr.printLabels')}</button></div>
    <div className="qr-grid printable-qr-labels">
      {machines.map((machine) => (
        <div className="qr-card" key={machine.id}>
          <AuthenticatedImage src={`/machines/${machine.id}/qr`} alt={t('qr.alt', { number: machine.inventory_number })} />
          <strong>{machine.name}</strong><span>{machine.brand} · {machine.pressure_bar} bar</span>
        </div>
      ))}
      {!machines.length && <div className="empty-state">{t('qr.empty')}</div>}
    </div>
  </>)
}

function SettingsPage() {
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

function Transfers() {
  const { date, t } = useI18n()
  const [items, setItems] = useState<TransferRecord[]>([])
  const [error, setError] = useState('')
  const load = () => api<TransferRecord[]>('/transfers')
    .then((records) => {
      setItems(records)
      setError('')
    })
    .catch(() => setError(t('transfers.loadError')))

  useEffect(() => { void load() }, [t])

  const download = (path: string, name: string) => downloadApiFile(path, name)
    .catch(() => setError(t('transfers.downloadError')))

  return (
    <>
      <div className="toolbar"><div><h3>{t('transfers.title')}</h3><p className="muted">{t('transfers.subtitle')}</p></div></div>
      {error && <div className="error" role="alert">{error}</div>}
      <BulkTransfers onChanged={() => { void load() }} />
      <div className="toolbar protocol-history-title"><div><h3>{t('transfers.historyTitle')}</h3><p className="muted">{t('transfers.historySubtitle')}</p></div></div>
      <div className="table-card">
        <table>
          <thead><tr><th>{t('transfers.number')}</th><th>{t('transfers.batch')}</th><th>{t('common.machine')}</th><th>{t('common.status')}</th><th>{t('transfers.companyLocation')}</th><th>{t('transfers.issueReturn')}</th><th>{t('transfers.documents')}</th></tr></thead>
          <tbody>{items.map((transfer) => (
            <tr key={transfer.id}>
              <td><strong>{transfer.protocol_number}</strong></td>
              <td>{transfer.batch_reference || t('common.noValue')}</td>
              <td>{transfer.machine.name}</td>
              <td><span className="badge">{transfer.is_active ? t('transfers.stillIssued') : t('transfers.returned')}</span></td>
              <td>{[transfer.company_unit, transfer.vessel, transfer.location_text].filter(Boolean).join(' · ') || t('common.noValue')}</td>
              <td>{date(transfer.issued_at || transfer.created_at)}{transfer.returned_at && <small>{t('transfers.returnedAt', { date: date(transfer.returned_at) })}</small>}</td>
              <td><button className="link" onClick={() => download(`/transfers/${transfer.id}/docx`, `${transfer.protocol_number}.docx`)}>{t('common.word')}</button> · <button className="link" onClick={() => download(`/transfers/${transfer.id}/pdf`, `${transfer.protocol_number}.pdf`)}>{t('common.pdf')}</button></td>
            </tr>
          ))}</tbody>
        </table>
        {!items.length && <div className="empty-state">{t('transfers.emptyHistory')}</div>}
      </div>
    </>
  )
}

export function PartCatalog() {
  const { t } = useI18n()
  const [items, setItems] = useState<CatalogPart[]>([])
  const [query, setQuery] = useState('')
  const [brand, setBrand] = useState('')
  const [error, setError] = useState(false)

  useEffect(() => {
    void api<CatalogPart[]>(`/catalog/parts?q=${encodeURIComponent(query)}&brand=${encodeURIComponent(brand)}`)
      .then((records) => {
        setItems(records)
        setError(false)
      })
      .catch(() => setError(true))
  }, [brand, query])

  const brands = useMemo(() => [...new Set(items.map((item) => item.brand))].sort(), [items])

  return (
    <>
      <div className="toolbar"><div><h3>{t('catalog.title')}</h3><p className="muted">{t('catalog.subtitle')}</p></div></div>
      <div className="filters">
        <div className="searchbox"><Search size={18} /><input aria-label={t('common.search')} value={query} onChange={(event) => setQuery(event.target.value)} placeholder={t('catalog.searchPlaceholder')} /></div>
        <select aria-label={t('machines.columnBrand')} value={brand} onChange={(event) => setBrand(event.target.value)}><option value="">{t('common.allBrands')}</option>{brands.map((item) => <option key={item}>{item}</option>)}</select>
      </div>
      {error && <div className="error" role="alert">{t('errors.generic')}</div>}
      <div className="table-card">
        <table><thead><tr><th>{t('catalog.brandModel')}</th><th>{t('catalog.assembly')}</th><th>{t('catalog.position')}</th><th>{t('common.partNumber')}</th><th>{t('catalog.description')}</th><th>{t('common.quantity')}</th><th>{t('catalog.source')}</th></tr></thead>
          <tbody>{items.map((item) => <tr key={item.id}><td><strong>{item.brand}</strong><small>{item.model}</small></td><td>{item.assembly || t('common.noValue')}</td><td>{item.position || t('common.noValue')}</td><td><strong>{item.part_number}</strong></td><td>{item.description}</td><td>{item.quantity || t('common.noValue')}</td><td>{item.source_document ? `${item.source_document.split('/').pop()} · ${t('common.page')} ${item.source_page || t('common.noValue')}` : t('common.noValue')}</td></tr>)}</tbody>
        </table>
        {!items.length && <div className="empty-state">{t('catalog.empty')}</div>}
      </div>
    </>
  )
}

export function Documents() {
  const { t } = useI18n()
  const [items, setItems] = useState<TechnicalDocument[]>([])
  const [error, setError] = useState('')

  useEffect(() => {
    void api<TechnicalDocument[]>('/documents').then(setItems).catch(() => setError(t('documents.loadError')))
  }, [t])

  const groups = useMemo(() => Object.entries(items.reduce<Record<string, TechnicalDocument[]>>((grouped, item) => {
    ;(grouped[item.brand] ??= []).push(item)
    return grouped
  }, {})), [items])

  const download = (id: number, name: string) => downloadApiFile(`/documents/${id}/download`, name)
    .catch(() => setError(t('documents.downloadError')))

  return (
    <>
      <div className="toolbar"><div><h3>{t('documents.title')}</h3><p className="muted">{t('documents.subtitle')}</p></div></div>
      {error && <div className="error" role="alert">{error}</div>}
      <div className="cards-list">
        {groups.map(([brand, documents]) => <div className="panel" key={brand}><div className="panel-title"><h3>{brand}</h3><BookOpen /></div><div className="activity-list">{documents.map((document) => <div key={document.id}><strong>{document.title}</strong><span>{document.category}</span><button className="link" onClick={() => download(document.id, document.title)}>{t('documents.openDownload')}</button></div>)}</div></div>)}
        {!groups.length && <div className="empty-state">{t('documents.empty')}</div>}
      </div>
    </>
  )
}

function AuditDetails({ details }: { details?: string | null }) {
  const { t } = useI18n()

  const renderValue = (value: unknown): ReactNode => {
    if (value === null || value === undefined || value === '') return t('common.noValue')
    if (Array.isArray(value)) {
      return <ul>{value.map((item, index) => <li key={index}>{renderValue(item)}</li>)}</ul>
    }
    if (typeof value === 'object') {
      return (
        <dl className="audit-detail-list">
          {Object.entries(value).map(([key, nested]) => (
            <div key={key}><dt>{key.replaceAll('_', ' ')}</dt><dd>{renderValue(nested)}</dd></div>
          ))}
        </dl>
      )
    }
    if (typeof value === 'boolean') return value ? t('common.yes') : t('common.no')
    return String(value)
  }

  if (!details) return <small>{t('common.noValue')}</small>
  try {
    const parsed = JSON.parse(details) as Record<string, unknown>
    return <dl className="audit-detail-list">{Object.entries(parsed).map(([key, value]) => <div key={key}><dt>{key.replaceAll('_', ' ')}</dt><dd>{renderValue(value)}</dd></div>)}</dl>
  } catch {
    return <small>{details}</small>
  }
}

function Audit() {
  const { date, t } = useI18n()
  const [items, setItems] = useState<AuditEntry[]>([])
  const [error, setError] = useState('')
  const [query, setQuery] = useState('')
  useEffect(() => {
    void api<AuditEntry[]>('/audit').then(setItems).catch(() => setError(t('audit.restricted')))
  }, [t])
  const filtered = useMemo(() => items.filter((entry) => (
    `${entry.user_name || ''} ${entry.entity_type} ${entry.entity_id || ''} ${entry.action} ${entry.operation_reference || ''} ${entry.details || ''}`
      .toLowerCase()
      .includes(query.toLowerCase())
  )), [items, query])
  const exportLog = () => downloadApiFile('/audit/export.json', 'assetcore-audit.json')
    .catch(() => setError(t('audit.exportError')))
  return (
    <>
      <div className="toolbar"><div><h3>{t('audit.title')}</h3><p className="muted">{t('audit.subtitle')}</p></div><button className="secondary" onClick={exportLog}><Download size={16} />{t('audit.export')}</button></div>
      <div className="filters"><div className="searchbox"><Search size={18} /><input aria-label={t('audit.search')} value={query} onChange={(event) => setQuery(event.target.value)} placeholder={t('audit.searchPlaceholder')} /></div></div>
      {error && <div className="error" role="alert">{error}</div>}
      <div className="table-card"><table><thead><tr><th>{t('audit.date')}</th><th>{t('audit.user')}</th><th>{t('audit.entity')}</th><th>{t('audit.action')}</th><th>{t('audit.details')}</th></tr></thead><tbody>{filtered.map((entry) => <tr key={entry.id}><td>{date(entry.created_at)}</td><td>{entry.user_name || t('common.system')}</td><td>{entry.entity_type} #{entry.entity_id || t('common.noValue')}</td><td>{entry.action}</td><td><AuditDetails details={entry.details} /></td></tr>)}</tbody></table>{!filtered.length && !error && <div className="empty-state">{t('audit.empty')}</div>}</div>
    </>
  )
}

export default App
