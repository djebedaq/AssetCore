import { useEffect, useState } from 'react'

import { api } from '../../api'
import { filePayload, friendlyError, Modal } from '../../industrialUi'
import { statusText, useI18n } from '../../i18n'
import type { MachinePassport } from '../../types'
import { PassportHeroSummary } from './PassportHeroSummary'
import {
  PassportAuditTab,
  PassportFilesTab,
  PassportHistoryTab,
  PassportOverviewTab,
  PassportPartsTab,
  PassportProtocolsTab,
  PassportRepairsTab,
  PassportTabList,
  type PassportTab,
} from './PassportTabs'

type Props = {
  machineId: number
  onClose: () => void
  onOpenCatalog?: () => void
}

export function MachinePassportModal({ machineId, onClose, onOpenCatalog }: Props) {
  const { t } = useI18n()
  const [passport, setPassport] = useState<MachinePassport | null>(null)
  const [tab, setTab] = useState<PassportTab>('overview')
  const [error, setError] = useState('')
  const [uploading, setUploading] = useState(false)
  const [customValues, setCustomValues] = useState<Record<number, string>>({})

  const load = () => api<MachinePassport>(`/machines/${machineId}/passport`)
    .then((data) => {
      setPassport(data)
      setCustomValues(Object.fromEntries(data.custom_fields.map((field) => [field.field_id, field.value || ''])))
      setError('')
    })
    .catch((caught) => setError(friendlyError(caught, t('passport.loadError'))))

  useEffect(() => { void load() }, [machineId])

  async function upload(file?: File) {
    if (!file) return
    setUploading(true)
    try {
      await api(`/machines/${machineId}/attachments`, {
        method: 'POST',
        body: JSON.stringify({
          ...(await filePayload(file)),
          kind: file.type.startsWith('image/') ? 'PHOTO' : 'DOCUMENT',
        }),
      })
      await load()
      setTab('files')
    } catch (caught) {
      setError(friendlyError(caught, t('passport.uploadError')))
    } finally {
      setUploading(false)
    }
  }

  async function saveCustomFields() {
    try {
      await api(`/machines/${machineId}/custom-fields`, {
        method: 'PUT',
        body: JSON.stringify({
          values: Object.entries(customValues).map(([fieldId, value]) => ({
            field_id: Number(fieldId),
            value: value || null,
          })),
        }),
      })
      await load()
    } catch (caught) {
      setError(friendlyError(caught, t('passport.saveFieldsError')))
    }
  }

  const title = passport
    ? t('passport.title', { number: passport.machine.inventory_number })
    : t('passport.loadingTitle')

  return <Modal title={title} onClose={onClose} wide>
    {error && <div className="error" role="alert">{error}</div>}
    {!passport ? <div className="loading" role="status">{t('common.loading')}</div> : passport.limited_view ? (
      <section className="passport-limited-view" aria-labelledby="limited-passport-title">
        <span className="eyebrow">{t('passport.limitedView')}</span>
        <h2 id="limited-passport-title">{t('passport.machineNumber', { number: passport.machine.inventory_number })}</h2>
        <strong>{passport.machine.name}</strong>
        <dl className="detail-grid">
          <div><dt>{t('machines.brand')}</dt><dd>{passport.machine.brand}</dd></div>
          <div><dt>{t('machines.model')}</dt><dd>{passport.machine.model || t('common.noValue')}</dd></div>
          <div><dt>{t('common.status')}</dt><dd><span className="badge">{statusText(t, passport.machine.status)}</span></dd></div>
          <div><dt>{t('common.location')}</dt><dd>{passport.machine.location?.name || t('common.notSpecified')}</dd></div>
          <div><dt>{t('passport.availability')}</dt><dd>{passport.current_state.available ? t('bulk.available') : t('bulk.unavailable')}</dd></div>
        </dl>
      </section>
    ) : <>
      <PassportHeroSummary machineId={machineId} passport={passport} />
      <PassportTabList active={tab} auditVisible={passport.audit_visible} onChange={setTab} />
      <div id={`passport-panel-${tab}`} role="tabpanel" aria-labelledby={`passport-tab-${tab}`} className="passport-tab-panel">
        {tab === 'overview' && <PassportOverviewTab passport={passport} customValues={customValues} setCustomValues={setCustomValues} onSave={() => void saveCustomFields()} />}
        {tab === 'history' && <PassportHistoryTab passport={passport} />}
        {tab === 'repairs' && <PassportRepairsTab passport={passport} />}
        {tab === 'protocols' && <PassportProtocolsTab passport={passport} />}
        {tab === 'parts' && <PassportPartsTab passport={passport} onOpenCatalog={onOpenCatalog} />}
        {tab === 'files' && <PassportFilesTab passport={passport} uploading={uploading} onUpload={(file) => void upload(file)} />}
        {tab === 'audit' && passport.audit_visible && <PassportAuditTab passport={passport} />}
      </div>
    </>}
  </Modal>
}
