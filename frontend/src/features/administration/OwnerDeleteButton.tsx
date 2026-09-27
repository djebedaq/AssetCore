import { useEffect, useRef, useState, type FormEvent } from 'react'
import { createPortal } from 'react-dom'
import { Trash2, X } from 'lucide-react'
import { api, ApiError } from '../../api'
import { useI18n, type TranslationKey } from '../../i18n'
import { storedUser } from '../../permissions'

export type DeleteResource = 'user' | 'department' | 'location' | 'asset_category' | 'category_field' | 'machine' | 'external_signer' | 'signature_slot'
type Dependency = { code: string; count: number; label_key: string }
export type DeletionPreview = {
  identity: string; can_delete: boolean; blockers: Dependency[]
  owned_records_to_delete: Dependency[]; confirmation_text: string
}
type Props = {
  resource: DeleteResource; resourceId: number; identity: string; categoryId?: number
  protectedOwner?: boolean; onDeleted: () => void | Promise<unknown>
}

const errors: Record<string, TranslationKey> = {
  owner_only: 'ownerDeletion.error.ownerOnly', system_owner_protected: 'ownerDeletion.error.ownerProtected',
  deletion_target_not_found: 'ownerDeletion.error.notFound', deletion_confirmation_mismatch: 'ownerDeletion.error.confirmation',
  reauthentication_failed: 'ownerDeletion.error.password', deletion_blocked: 'ownerDeletion.error.blocked',
  unsupported_delete_resource: 'ownerDeletion.error.unsupported', deletion_conflict: 'ownerDeletion.error.conflict',
  authentication_throttled: 'ownerDeletion.error.throttled',
  deletion_category_required: 'ownerDeletion.error.unsupported',
}

export function OwnerDeleteButton(props: Props) {
  const { t } = useI18n()
  const [open, setOpen] = useState(false)
  if (!storedUser()?.is_system_owner || props.protectedOwner) return null
  return <>
    <button type="button" className="owner-delete-button" aria-label={t('ownerDeletion.actionFor', { identity: props.identity })} onClick={() => setOpen(true)}><Trash2 size={15} />{t('ownerDeletion.action')}</button>
    {open && <OwnerDeletionDialog {...props} onClose={() => setOpen(false)} />}
  </>
}

export function OwnerDeletionDialog({ resource, resourceId, categoryId, onDeleted, onClose }: Props & { onClose: () => void }) {
  const { t } = useI18n()
  const [preview, setPreview] = useState<DeletionPreview | null>(null)
  const [password, setPassword] = useState('')
  const [confirmation, setConfirmation] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<TranslationKey | null>(null)
  const dialog = useRef<HTMLElement>(null)
  const closeButton = useRef<HTMLButtonElement>(null)
  const path = `/owner/data-deletion/${resource}/${resourceId}`

  useEffect(() => {
    let active = true
    void api<DeletionPreview>(`${path}/preview${categoryId ? `?category_id=${categoryId}` : ''}`)
      .then(value => { if (active) setPreview(value) })
      .catch(caught => { if (active) setError(caught instanceof ApiError ? errors[caught.code || ''] || 'ownerDeletion.error.generic' : 'ownerDeletion.error.generic') })
    return () => { active = false }
  }, [path, categoryId])

  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null
    const overflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    closeButton.current?.focus()
    return () => {
      document.body.style.overflow = overflow
      if (previous?.isConnected) previous.focus()
    }
  }, [])

  async function submit(event: FormEvent) {
    event.preventDefault()
    if (busy || !preview?.can_delete || !password || confirmation !== preview.confirmation_text) return
    setBusy(true)
    setError(null)
    try {
      await api(`${path}/execute`, { method: 'POST', body: JSON.stringify({ current_password: password, confirmation_text: confirmation, ...(categoryId ? { category_id: categoryId } : {}) }) })
    } catch (caught) {
      setPassword('')
      setError(caught instanceof ApiError ? errors[caught.code || ''] || 'ownerDeletion.error.generic' : 'ownerDeletion.error.generic')
      if (caught instanceof ApiError && Array.isArray(caught.data.blockers)) {
        setPreview(current => current && { ...current, can_delete: false, blockers: caught.data.blockers as Dependency[] })
      }
      setBusy(false)
      return
    }
    setPassword('')
    setConfirmation('')
    // The deletion already committed. A refresh failure must never suggest retrying DELETE.
    onClose()
    await onDeleted()
  }

  function dependencies(items: Dependency[]) {
    return <ul>{items.map(item => <li key={item.code}>{t(item.label_key as TranslationKey)}: <strong>{item.count}</strong></li>)}</ul>
  }

  return createPortal(<div className="modal-bg owner-deletion-backdrop"><section ref={dialog} className="modal owner-deletion-dialog" role="dialog" aria-modal="true" aria-label={t('ownerDeletion.title')} onKeyDown={event => {
    if (event.key === 'Escape' && !busy) { event.stopPropagation(); onClose() }
    if (event.key !== 'Tab') return
    const elements = [...(dialog.current?.querySelectorAll<HTMLElement>('button:not(:disabled), input:not(:disabled), [tabindex="0"]') || [])]
    const first = elements[0], last = elements.at(-1)
    if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus() }
    else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus() }
  }}>
    <div className="modal-head"><h3>{t('ownerDeletion.title')}</h3><button type="button" ref={closeButton} disabled={busy} onClick={onClose} aria-label={t('common.close')}><X /></button></div>
    <p className="owner-deletion-warning">{t('ownerDeletion.warning')}</p>
    {error && <p className="error" role="alert">{t(error)}</p>}
    {!preview && !error && <p role="status">{t('common.loading')}</p>}
    {preview && <>
      <strong className="owner-deletion-identity">{preview.identity}</strong>
      {preview.blockers.length > 0 && <div><h4>{t('ownerDeletion.blockers')}</h4>{dependencies(preview.blockers)}<p>{t('ownerDeletion.resolve')}</p></div>}
      {preview.owned_records_to_delete.length > 0 && <div><h4>{t('ownerDeletion.children')}</h4>{dependencies(preview.owned_records_to_delete)}</div>}
      {preview.can_delete && <form onSubmit={event => void submit(event)}>
        <label>{t('ownerDeletion.password')}<input required type="password" autoComplete="off" value={password} disabled={busy} onChange={event => setPassword(event.target.value)} /></label>
        <label>{t('ownerDeletion.confirmation')}<code>{preview.confirmation_text}</code><input required autoComplete="off" spellCheck={false} value={confirmation} disabled={busy} onChange={event => setConfirmation(event.target.value)} /></label>
        <div className="actions"><button type="button" className="secondary" disabled={busy} onClick={onClose}>{t('common.cancel')}</button><button className="owner-delete-button" disabled={busy || !password || confirmation !== preview.confirmation_text}>{t(busy ? 'common.loading' : 'ownerDeletion.action')}</button></div>
      </form>}
    </>}
  </section></div>, document.body)
}
