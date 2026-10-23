import { useEffect, useState, type FormEvent } from 'react'
import { api } from '../../api'
import { Modal, filePayload } from '../../industrialUi'
import { useI18n, type TranslationKey } from '../../i18n'
import { studioError, type StudioTemplate, type StudioVersion } from './shared'

export function ProposalDialog({ template, version, close, submitted }: {
  template: StudioTemplate; version: StudioVersion; close: () => void; submitted: (id: number) => void
}) {
  const { t, locale } = useI18n()
  const [title, setTitle] = useState(''), [description, setDescription] = useState('')
  const [files, setFiles] = useState<File[]>([]), [previews, setPreviews] = useState<string[]>([])
  const [busy, setBusy] = useState(false), [error, setError] = useState<TranslationKey | null>(null)
  useEffect(() => {
    const urls = files.map(file => URL.createObjectURL(file)); setPreviews(urls)
    return () => urls.forEach(url => URL.revokeObjectURL(url))
  }, [files])
  useEffect(() => {
    const before = (event: BeforeUnloadEvent) => { if (title || description || files.length || busy) event.preventDefault() }
    window.addEventListener('beforeunload', before)
    return () => window.removeEventListener('beforeunload', before)
  }, [title, description, files.length, busy])
  const finish = () => { if (!busy && (!(title || description || files.length) || window.confirm(t('studio.leave')))) close() }
  async function send(event: FormEvent) {
    event.preventDefault(); setBusy(true); setError(null)
    try {
      const attachments = []
      for (const file of files) {
        if (file.size > 2_000_000 || !['image/png', 'image/jpeg'].includes(file.type)) { setError('studio.invalidImage'); return }
        const payload = await filePayload(file)
        attachments.push({ filename: file.name, media_type: file.type, content_base64: payload.content_base64 })
      }
      const p = await api<{ id: number }>('/studio/proposals', { method: 'POST', body: JSON.stringify({
        template_id: template.id, target_version_id: version.id, language: version.language,
        title, description, attachments,
      }) })
      submitted(p.id)
    } catch (e) { setError(studioError(e)) } finally { setBusy(false) }
  }
  return <Modal title={t('proposal.propose')} onClose={finish}>
    <p><strong>{template[`name_${locale}`] || template.name_bg}</strong><br />{t('studio.version', { number: version.version })} · {t(`language.${version.language}`)}</p>
    {error && <p className="error" role="alert">{t(error)}</p>}
    <form className="studio-inline-form" onSubmit={send}><fieldset disabled={busy} className="studio-proposal-fields">
      <label>{t('proposal.title')}<input autoFocus required minLength={3} maxLength={255} value={title} onChange={e => setTitle(e.target.value)} /></label>
      <label>{t('proposal.description')}<textarea required minLength={10} maxLength={10000} rows={6} value={description} onChange={e => setDescription(e.target.value)} /></label>
      <label>{t('proposal.images')}<input type="file" multiple accept="image/png,image/jpeg" onChange={e => {
        const next = [...(e.target.files || [])]
        if (next.length > 3 || next.some(f => f.size > 2_000_000 || !['image/png', 'image/jpeg'].includes(f.type))) { setError('studio.invalidImage'); e.target.value = ''; setFiles([]) }
        else { setFiles(next); setError(null) }
      }} /></label><small>{t('proposal.imageHint')}</small>
      <div className="studio-proposal-images">{previews.map((url, i) => <img key={url} src={url} alt={t('proposal.evidence', { number: i + 1 })} />)}</div>
    </fieldset><button className="primary" disabled={busy || title.trim().length < 3 || description.trim().length < 10}>{t('proposal.submit')}</button></form>
  </Modal>
}
