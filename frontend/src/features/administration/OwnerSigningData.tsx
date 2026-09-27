import { useEffect, useState } from 'react'
import { api } from '../../api'
import { useI18n } from '../../i18n'
import { storedUser } from '../../permissions'
import { OwnerDeleteButton } from './OwnerDeleteButton'

type Signer = { id: number; first_name: string; middle_name?: string; last_name: string; is_active: boolean }
type Slot = { id: number; document_type: string; code: string; label_bg: string; label_en?: string; label_ru?: string; is_active: boolean }

export function OwnerSigningData() {
  const { t, locale } = useI18n()
  const [signers, setSigners] = useState<Signer[]>([])
  const [slots, setSlots] = useState<Slot[]>([])
  const [error, setError] = useState(false)
  const owner = storedUser()?.is_system_owner
  async function load() {
    try {
      const [people, positions] = await Promise.all([api<Signer[]>('/external-signers?include_inactive=true'), api<Slot[]>('/signature-slots')])
      setSigners(people); setSlots(positions); setError(false)
    } catch { setError(true) }
  }
  useEffect(() => { if (owner) void load() }, [owner])
  if (!owner) return null
  return <section className="panel wide"><h3>{t('ownerDeletion.signingData')}</h3>{error && <p role="alert">{t('admin.loadError')}</p>}
    <h4>{t('ownerDeletion.references.signers')}</h4><div className="admin-list">{signers.map(signer => {
      const name = [signer.first_name, signer.middle_name, signer.last_name].filter(Boolean).join(' ')
      return <div key={signer.id}><span>{name}</span><span className="badge">{t(signer.is_active ? 'admin.active' : 'admin.inactive')}</span><OwnerDeleteButton resource="external_signer" resourceId={signer.id} identity={name} onDeleted={load} /></div>
    })}</div>
    <h4>{t('ownerDeletion.references.slots')}</h4><div className="admin-list">{slots.map(slot => <div key={slot.id}><span>{slot[`label_${locale}`] || slot.label_bg}<small>{slot.document_type} · {slot.code}</small></span><span className="badge">{t(slot.is_active ? 'admin.active' : 'admin.inactive')}</span><OwnerDeleteButton resource="signature_slot" resourceId={slot.id} identity={`${slot.document_type}/${slot.code}`} onDeleted={load} /></div>)}</div>
  </section>
}
