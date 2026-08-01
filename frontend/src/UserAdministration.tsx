import { type FormEvent, type ReactNode, useEffect, useMemo, useState } from 'react'
import { KeyRound, Pencil, Plus, ShieldCheck, UserCheck, UserX, X } from 'lucide-react'
import { ApiError, api } from './api'
import { useI18n, type TranslationKey } from './i18n'
import { storedUser } from './permissions'
import type { ManagedUser, UserRole } from './types'

type Modal = 'create' | 'edit' | 'reset' | null

const emptyCreate = {
  email: '', full_name: '', role: 'observer' as UserRole, preferred_language: 'bg',
  temporary_password: '', confirm_password: '', is_active: true,
}

function userError(error: unknown): TranslationKey {
  if (!(error instanceof ApiError)) return 'users.error.generic'
  if (error.status === 403) return 'users.error.permission'
  if (error.code === 'duplicate_email') return 'users.error.duplicateEmail'
  if (error.code === 'password_policy') return 'users.error.passwordPolicy'
  if (error.code === 'system_owner_protected') return 'users.error.ownerProtected'
  if (error.code === 'role_escalation_denied' || error.code === 'user_scope_denied') return 'users.error.scope'
  if (error.status === 422) return 'users.error.validation'
  return 'users.error.generic'
}

function UserModal({ title, onClose, children }: {
  title: string; onClose: () => void; children: ReactNode
}) {
  const { t } = useI18n()
  return <div className="modal-bg" role="presentation"><section className="modal" role="dialog" aria-modal="true" aria-label={title}><div className="modal-head"><h3>{title}</h3><button type="button" onClick={onClose} aria-label={t('common.close')}><X /></button></div>{children}</section></div>
}

export default function UserAdministration() {
  const { date, t } = useI18n()
  const session = storedUser()
  const [items, setItems] = useState<ManagedUser[]>([])
  const [search, setSearch] = useState('')
  const [role, setRole] = useState('')
  const [active, setActive] = useState('')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<TranslationKey | ''>('')
  const [success, setSuccess] = useState<TranslationKey | ''>('')
  const [modal, setModal] = useState<Modal>(null)
  const [selected, setSelected] = useState<ManagedUser | null>(null)
  const [createForm, setCreateForm] = useState({ ...emptyCreate, preferred_language: session?.preferred_language || 'bg' })
  const [editForm, setEditForm] = useState({ full_name: '', role: 'observer' as UserRole, preferred_language: 'bg' })
  const [resetForm, setResetForm] = useState({ temporary_password: '', confirm_password: '' })
  const availableRoles = useMemo<UserRole[]>(
    () => session?.is_system_owner ? ['director', 'mechanic', 'observer'] : ['mechanic', 'observer'],
    [session?.is_system_owner],
  )
  const filterRoles = useMemo<UserRole[]>(
    () => session?.is_system_owner ? ['administrator', ...availableRoles] : availableRoles,
    [availableRoles, session?.is_system_owner],
  )

  async function load() {
    setLoading(true)
    setError('')
    const query = new URLSearchParams()
    if (search.trim()) query.set('search', search.trim())
    if (role) query.set('role', role)
    if (active) query.set('is_active', active)
    try { setItems(await api<ManagedUser[]>(`/users${query.size ? `?${query}` : ''}`)) }
    catch (caught) { setError(userError(caught)) }
    finally { setLoading(false) }
  }

  useEffect(() => { void load() }, [search, role, active])

  function closeModal() {
    setModal(null)
    setSelected(null)
    setCreateForm({ ...emptyCreate, preferred_language: session?.preferred_language || 'bg' })
    setResetForm({ temporary_password: '', confirm_password: '' })
  }

  function openCreate() {
    setError('')
    setModal('create')
  }

  async function createUser(event: FormEvent) {
    event.preventDefault()
    setError('')
    try {
      await api('/users', { method: 'POST', body: JSON.stringify(createForm) })
      setCreateForm({ ...emptyCreate, preferred_language: session?.preferred_language || 'bg' })
      setSuccess('users.success.created')
      closeModal()
      await load()
    } catch (caught) { setError(userError(caught)) }
  }

  function openEdit(user: ManagedUser) {
    setError('')
    setSelected(user)
    setEditForm({ full_name: user.full_name, role: user.role, preferred_language: user.preferred_language })
    setModal('edit')
  }

  async function editUser(event: FormEvent) {
    event.preventDefault()
    if (!selected) return
    setError('')
    try {
      await api(`/users/${selected.id}`, { method: 'PATCH', body: JSON.stringify(editForm) })
      setSuccess('users.success.updated')
      closeModal()
      await load()
    } catch (caught) { setError(userError(caught)) }
  }

  async function toggleUser(user: ManagedUser) {
    if (!window.confirm(t(user.is_active ? 'users.confirm.deactivate' : 'users.confirm.activate', { name: user.full_name }))) return
    setError('')
    try {
      await api(`/users/${user.id}/${user.is_active ? 'deactivate' : 'activate'}`, { method: 'POST' })
      setSuccess(user.is_active ? 'users.success.deactivated' : 'users.success.activated')
      await load()
    } catch (caught) { setError(userError(caught)) }
  }

  function openReset(user: ManagedUser) {
    setError('')
    setSelected(user)
    setResetForm({ temporary_password: '', confirm_password: '' })
    setModal('reset')
  }

  async function resetPassword(event: FormEvent) {
    event.preventDefault()
    if (!selected || !window.confirm(t('users.confirm.reset', { name: selected.full_name }))) return
    setError('')
    try {
      await api(`/users/${selected.id}/reset-password`, { method: 'POST', body: JSON.stringify(resetForm) })
      setResetForm({ temporary_password: '', confirm_password: '' })
      setSuccess('users.success.reset')
      closeModal()
      await load()
    } catch (caught) { setError(userError(caught)) }
  }

  return <>
    <div className="toolbar users-toolbar"><div><h3>{t('users.title')}</h3><p className="muted">{t(session?.is_system_owner ? 'users.subtitle.owner' : 'users.subtitle.director')}</p></div><button className="primary" onClick={openCreate}><Plus size={17} />{t('users.add')}</button></div>
    <div className="filter-row users-filters"><label>{t('common.search')}<input value={search} onChange={(event) => setSearch(event.target.value)} placeholder={t('users.searchPlaceholder')} /></label><label>{t('users.role')}<select value={role} onChange={(event) => setRole(event.target.value)}><option value="">{t('users.filter.allRoles')}</option>{filterRoles.map((value) => <option key={value} value={value}>{t(`role.${value}` as TranslationKey)}</option>)}</select></label><label>{t('users.status')}<select value={active} onChange={(event) => setActive(event.target.value)}><option value="">{t('users.filter.allStatuses')}</option><option value="true">{t('users.active')}</option><option value="false">{t('users.inactive')}</option></select></label></div>
    {!modal && error && <div className="error" role="alert">{t(error)}</div>}
    {success && <div className="success" role="status">{t(success)}</div>}
    {loading ? <div className="loading">{t('common.loading')}</div> : <div className="table-card users-table"><table><thead><tr><th>{t('users.name')}</th><th>{t('users.role')}</th><th>{t('users.language')}</th><th>{t('users.status')}</th><th>{t('users.createdAt')}</th><th>{t('users.lastLogin')}</th><th>{t('users.actions')}</th></tr></thead><tbody>{items.map((user) => <tr key={user.id}><td><strong>{user.full_name}</strong><small>{user.email}</small>{user.is_system_owner && <span className="owner-badge"><ShieldCheck size={14} />{t('users.systemOwner')}</span>}</td><td><span className="badge">{t(`role.${user.role}` as TranslationKey)}</span></td><td>{t(`language.${user.preferred_language}` as TranslationKey)}</td><td><span className={`badge ${user.is_active ? 'batch-complete' : 'batch-active'}`}>{t(user.is_active ? 'users.active' : 'users.inactive')}</span></td><td>{date(user.created_at)}</td><td>{user.last_login_at ? date(user.last_login_at) : t('users.neverLoggedIn')}</td><td>{!user.is_system_owner && <div className="user-actions"><button className="link" onClick={() => openEdit(user)}><Pencil size={14} />{t('common.edit')}</button><button className="link" onClick={() => void toggleUser(user)}>{user.is_active ? <UserX size={14} /> : <UserCheck size={14} />}{t(user.is_active ? 'users.deactivate' : 'users.activate')}</button><button className="link" onClick={() => openReset(user)}><KeyRound size={14} />{t('users.resetPassword')}</button></div>}</td></tr>)}</tbody></table>{!items.length && <div className="empty-state">{t('users.empty')}</div>}</div>}
    {modal === 'create' && <UserModal title={t('users.add')} onClose={closeModal}><form className="form-grid" onSubmit={createUser}>{error && <div className="error wide" role="alert">{t(error)}</div>}<label>{t('users.name')}<input required value={createForm.full_name} onChange={(event) => setCreateForm({ ...createForm, full_name: event.target.value })} /></label><label>{t('users.workEmail')}<input type="email" required autoComplete="off" value={createForm.email} onChange={(event) => setCreateForm({ ...createForm, email: event.target.value })} /></label><label>{t('users.role')}<select value={createForm.role} onChange={(event) => setCreateForm({ ...createForm, role: event.target.value as UserRole })}>{availableRoles.map((value) => <option value={value} key={value}>{t(`role.${value}` as TranslationKey)}</option>)}</select></label><label>{t('users.language')}<select value={createForm.preferred_language} onChange={(event) => setCreateForm({ ...createForm, preferred_language: event.target.value as ManagedUser['preferred_language'] })}><option value="bg">{t('language.bg')}</option><option value="en">{t('language.en')}</option><option value="ru">{t('language.ru')}</option></select></label><label>{t('users.temporaryPassword')}<input required minLength={10} type="password" autoComplete="new-password" value={createForm.temporary_password} onChange={(event) => setCreateForm({ ...createForm, temporary_password: event.target.value })} /></label><label>{t('users.confirmPassword')}<input required minLength={10} type="password" autoComplete="new-password" value={createForm.confirm_password} onChange={(event) => setCreateForm({ ...createForm, confirm_password: event.target.value })} /></label><label className="check-label wide"><input type="checkbox" checked={createForm.is_active} onChange={(event) => setCreateForm({ ...createForm, is_active: event.target.checked })} />{t('users.activeAccount')}</label><p className="muted wide">{t('users.passwordPolicy')}</p><div className="actions wide"><button type="button" className="secondary" onClick={closeModal}>{t('common.cancel')}</button><button className="primary">{t('common.save')}</button></div></form></UserModal>}
    {modal === 'edit' && selected && <UserModal title={t('users.edit')} onClose={closeModal}><form className="form-grid" onSubmit={editUser}>{error && <div className="error wide" role="alert">{t(error)}</div>}<label className="wide">{t('users.name')}<input required value={editForm.full_name} onChange={(event) => setEditForm({ ...editForm, full_name: event.target.value })} /></label><label>{t('users.role')}<select value={editForm.role} onChange={(event) => setEditForm({ ...editForm, role: event.target.value as UserRole })}>{availableRoles.map((value) => <option value={value} key={value}>{t(`role.${value}` as TranslationKey)}</option>)}</select></label><label>{t('users.language')}<select value={editForm.preferred_language} onChange={(event) => setEditForm({ ...editForm, preferred_language: event.target.value as ManagedUser['preferred_language'] })}><option value="bg">{t('language.bg')}</option><option value="en">{t('language.en')}</option><option value="ru">{t('language.ru')}</option></select></label><div className="actions wide"><button type="button" className="secondary" onClick={closeModal}>{t('common.cancel')}</button><button className="primary">{t('common.save')}</button></div></form></UserModal>}
    {modal === 'reset' && selected && <UserModal title={t('users.resetPassword')} onClose={closeModal}><form className="form-grid" onSubmit={resetPassword}>{error && <div className="error wide" role="alert">{t(error)}</div>}<p className="wide">{t('users.resetFor', { name: selected.full_name })}</p><label>{t('users.temporaryPassword')}<input required minLength={10} type="password" autoComplete="new-password" value={resetForm.temporary_password} onChange={(event) => setResetForm({ ...resetForm, temporary_password: event.target.value })} /></label><label>{t('users.confirmPassword')}<input required minLength={10} type="password" autoComplete="new-password" value={resetForm.confirm_password} onChange={(event) => setResetForm({ ...resetForm, confirm_password: event.target.value })} /></label><p className="muted wide">{t('users.forceChangeHint')}</p><div className="actions wide"><button type="button" className="secondary" onClick={closeModal}>{t('common.cancel')}</button><button className="primary">{t('users.resetPassword')}</button></div></form></UserModal>}
  </>
}
