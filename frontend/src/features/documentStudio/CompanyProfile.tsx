import { useEffect, useState, type FormEvent } from 'react'
import { api, createApiObjectUrl } from '../../api'
import { filePayload } from '../../industrialUi'
import { useI18n, type TranslationKey } from '../../i18n'
import { hasPermission } from '../../permissions'
import { studioError, type BrandImage, type Identity, type Profile } from './shared'

const textFields = ['legal_name', 'short_name', 'registration_number', 'vat_number', 'address', 'city', 'country', 'phone', 'email', 'website', 'timezone'] as const

function ImageThumbnail({ item }: { item: BrandImage }) {
  const { t } = useI18n()
  const [url, setUrl] = useState('')
  useEffect(() => {
    let live = true
    let objectUrl = ''
    void createApiObjectUrl(item.download_endpoint).then(value => {
      objectUrl = value.url
      if (live) setUrl(value.url)
      else URL.revokeObjectURL(value.url)
    }).catch(() => {})
    return () => { live = false; if (objectUrl) URL.revokeObjectURL(objectUrl) }
  }, [item.download_endpoint])
  return url ? <img src={url} alt={t('studio.image', { id: item.id })} /> : <span>{t('studio.image', { id: item.id })}</span>
}

export function CompanyProfile({ onDirty }: { onDirty: (dirty: boolean) => void }) {
  const { t } = useI18n()
  const editable = hasPermission('company.manage')
  const [profile, setProfile] = useState<Profile | null>(null)
  const [identity, setIdentity] = useState<Identity | null>(null)
  const [images, setImages] = useState<BrandImage[]>([])
  const [error, setError] = useState<TranslationKey | null>(null)
  const [busy, setBusy] = useState(false)
  const [confirmed, setConfirmed] = useState(false)
  const [file, setFile] = useState<File | null>(null)
  const [purpose, setPurpose] = useState<BrandImage['purpose']>('PRIMARY')
  const dirty = !!identity && JSON.stringify(identity) !== JSON.stringify(profile?.identity)
  useEffect(() => { onDirty(dirty || busy); return () => onDirty(false) }, [dirty, busy, onDirty])
  async function load() {
    setBusy(true)
    try {
      const [next, nextImages] = await Promise.all([api<Profile>('/studio/company'), api<BrandImage[]>('/studio/images')])
      setProfile(next); setIdentity(next.identity); setImages(nextImages); setConfirmed(false); setError(null)
    } catch (e) { setError(studioError(e)) } finally { setBusy(false) }
  }
  useEffect(() => { void load() }, [])
  function edit<K extends keyof Identity>(key: K, value: Identity[K]) {
    setIdentity(current => current ? { ...current, [key]: value } : current)
    setConfirmed(false)
  }
  async function save(event: FormEvent) {
    event.preventDefault()
    if (!profile || !identity) return
    setBusy(true); setError(null); setConfirmed(false)
    try {
      const next = await api<Profile>('/studio/company', { method: 'PUT', body: JSON.stringify({ expected_revision: profile.revision, identity }) })
      setProfile(next); setIdentity(next.identity); setConfirmed(true)
    } catch (e) { setError(studioError(e)) } finally { setBusy(false) }
  }
  async function upload(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!file) return
    if (file.size > 2_000_000 || !['image/png', 'image/jpeg'].includes(file.type)) { setError('studio.invalidImage'); return }
    const form = event.currentTarget
    setBusy(true); setError(null)
    try {
      const item = await api<BrandImage>('/studio/images', { method: 'POST', body: JSON.stringify({ ...await filePayload(file), purpose }) })
      setImages(current => [item, ...current]); setFile(null); form.reset()
      // Selection remains an explicit profile change until server-confirmed save.
      if (purpose === 'PRIMARY') edit('primary_logo_id', item.id)
      else if (purpose === 'SECONDARY') edit('secondary_logo_id', item.id)
      else edit('identity_image_ids', [...(identity?.identity_image_ids || []), item.id])
    } catch (e) { setError(studioError(e)) } finally { setBusy(false) }
  }
  return <div className="studio-company">
    {error && <p className="error" role="alert">{t(error)}</p>}
    {!identity || !profile ? <button className="secondary" disabled={busy} onClick={() => void load()}>{t(busy ? 'studio.loading' : 'studio.reload')}</button> : <>
      <form className="panel" onSubmit={save}>
        <div className="panel-title"><h3>{t('studio.company')}</h3><span className="badge">{t('studio.revision', { number: profile.revision })}</span></div>
        <p className="muted">{t('studio.identityHint')}</p>
        <fieldset disabled={!editable || busy} className="studio-fields">
          {textFields.map(key => <label key={key}>{t(`studio.${key}`)}<input required={key === 'legal_name' || key === 'timezone'} maxLength={key === 'address' ? 700 : key === 'website' ? 500 : key === 'short_name' || key === 'registration_number' || key === 'vat_number' || key === 'timezone' ? 100 : key === 'city' || key === 'country' ? 150 : key === 'phone' ? 80 : key === 'email' ? 254 : 255} type={key === 'email' ? 'email' : key === 'website' ? 'url' : 'text'} value={identity[key]} onChange={e => edit(key, e.target.value)} /></label>)}
          <label>{t('studio.default_language')}<select value={identity.default_language} onChange={e => edit('default_language', e.target.value as Identity['default_language'])}>{(['bg', 'en', 'ru'] as const).map(language => <option key={language} value={language}>{t(`language.${language}`)}</option>)}</select></label>
          {(['primary_color', 'secondary_color'] as const).map(key => <label key={key}>{t(`studio.${key}`)}<input type="color" value={identity[key]} onChange={e => edit(key, e.target.value)} /></label>)}
          {(['primary_logo_id', 'secondary_logo_id'] as const).map((key, index) => <label key={key}>{t(index ? 'studio.SECONDARY' : 'studio.PRIMARY')}<select value={identity[key] || ''} onChange={e => edit(key, e.target.value ? Number(e.target.value) : null)}><option value="">{t('studio.none')}</option>{images.map(image => <option key={image.id} value={image.id}>{t('studio.image', { id: image.id })}</option>)}</select></label>)}
        </fieldset>
        <fieldset disabled={!editable || busy} className="studio-image-selection"><legend>{t('studio.allowed')}</legend>
          {!images.length && <p className="muted">{t('studio.noImages')}</p>}
          <div className="studio-images">{images.map(image => <label key={image.id}><ImageThumbnail item={image} /><span>{t('studio.image', { id: image.id })} · {image.width} × {image.height}</span><input type="checkbox" checked={identity.identity_image_ids.includes(image.id)} onChange={e => edit('identity_image_ids', e.target.checked ? [...identity.identity_image_ids, image.id] : identity.identity_image_ids.filter(id => id !== image.id))} /></label>)}</div>
        </fieldset>
        <div className="actions studio-savebar"><span role="status">{t(busy ? 'studio.saving' : dirty ? 'studio.unsaved' : confirmed ? 'studio.saved' : 'studio.readOnly')}</span>{editable && <><button className="secondary" type="button" disabled={busy} onClick={() => { if (!dirty || window.confirm(t('studio.leave'))) void load() }}>{t('studio.reload')}</button><button className="primary" disabled={busy || !dirty}>{t('studio.save')}</button></>}</div>
      </form>
      {editable && <form className="panel" onSubmit={upload}><h3>{t('studio.images')}</h3><p className="muted">{t('studio.imageHint')}</p><fieldset disabled={busy} className="studio-fields"><label>{t('studio.images')}<input type="file" required accept="image/png,image/jpeg" onChange={e => setFile(e.target.files?.[0] || null)} /></label><label>{t('studio.type')}<select value={purpose} onChange={e => setPurpose(e.target.value as BrandImage['purpose'])}>{(['PRIMARY', 'SECONDARY', 'IDENTITY'] as const).map(value => <option key={value} value={value}>{t(`studio.${value}`)}</option>)}</select></label></fieldset><button className="secondary" disabled={busy || !file}>{t('studio.upload')}</button></form>}
    </>}
  </div>
}
