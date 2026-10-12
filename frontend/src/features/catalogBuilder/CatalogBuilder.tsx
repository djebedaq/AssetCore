import { useState } from 'react'
import { useI18n } from '../../i18n'
import { hasPermission } from '../../permissions'
import SimpleCatalogBuilder from './SimpleCatalogBuilder'
import ReferenceLinker from './ReferenceLinker'

export default function CatalogBuilder() {
  const { t } = useI18n()
  const [dirty, setDirty] = useState(false)
  const [linking, setLinking] = useState(false)
  if (!hasPermission('parts.manage')) return null
  return <div>
    {linking ? <ReferenceLinker onClose={() => setLinking(false)} /> : <SimpleCatalogBuilder onDirtyChange={setDirty} onLink={() => {
      if (dirty && !window.confirm(t('wizard.unsaved'))) return
      setLinking(true)
    }} />}
  </div>
}
