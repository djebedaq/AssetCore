import { useCallback, useEffect, useState } from 'react'
import { RefreshCw } from 'lucide-react'
import { api } from './api'
import OfficialDocumentSection from './features/officialDocuments/OfficialDocumentSection'
import type { OfficialDocumentRegistry } from './features/officialDocuments/types'
import { useI18n } from './i18n'

const EMPTY_REGISTRY: OfficialDocumentRegistry = {
  transfers: { count: 0, items: [] },
  repairs: { count: 0, items: [] },
  parts: { count: 0, items: [] },
}

export default function OfficialDocuments() {
  const { t } = useI18n()
  const [registry, setRegistry] = useState<OfficialDocumentRegistry>(EMPTY_REGISTRY)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  const load = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      setRegistry(await api<OfficialDocumentRegistry>('/official-documents/registry'))
    } catch {
      setError(t('official.loadError'))
    } finally {
      setLoading(false)
    }
  }, [t])

  useEffect(() => { void load() }, [load])

  return (
    <>
      <div className="toolbar official-registry-toolbar"><div><h3>{t('official.title')}</h3><p className="muted">{t('official.registrySubtitle')}</p></div><button className="secondary" disabled={loading} onClick={() => { void load() }}><RefreshCw size={16} />{t('official.refresh')}</button></div>
      {error && <div className="error" role="alert">{error}</div>}
      {loading ? <div className="loading" role="status">{t('common.loading')}</div> : <div className="official-registry-sections">
        <OfficialDocumentSection section={registry.transfers} titleKey="official.sectionTransfers" emptyKey="official.emptyTransfers" typeKey="official.typeTransferLifecycle" statusDomain="transfer" />
        <OfficialDocumentSection section={registry.repairs} titleKey="official.sectionRepairs" emptyKey="official.emptyRepairs" typeKey="official.typeRepair" statusDomain="repair" />
        <OfficialDocumentSection section={registry.parts} titleKey="official.sectionParts" emptyKey="official.emptyParts" typeKey="official.typeParts" statusDomain="part" />
      </div>}
    </>
  )
}
