import { useState } from 'react'
import { useI18n } from '../../i18n'
import { hasPermission } from '../../permissions'
import AdvancedCatalogBuilder from './AdvancedCatalogBuilder'
import SimpleCatalogBuilder from './SimpleCatalogBuilder'
import ReferenceLinker from './ReferenceLinker'

export default function CatalogBuilder() {
  const { t } = useI18n()
  const [advanced, setAdvanced] = useState(false)
  const [dirty, setDirty] = useState(false)
  const [linking, setLinking] = useState(false)
  if (!hasPermission('parts.manage')) return null
  return <div>
    <div className="actions wizard-mode"><button className="secondary" onClick={() => {
      if (dirty && !window.confirm(t('wizard.unsaved'))) return
      setLinking(value => !value); setDirty(false)
    }}>{t('ref.link')}</button><button className="secondary" onClick={() => {
      if (dirty && !window.confirm(t('wizard.unsaved'))) return
      setAdvanced(value => !value); setDirty(false)
    }}>{t(advanced ? 'wizard.simple' : 'wizard.advanced')}</button></div>
    {linking ? <ReferenceLinker onClose={() => setLinking(false)} /> : advanced ? <AdvancedCatalogBuilder onDirtyChange={setDirty} /> : <SimpleCatalogBuilder onDirtyChange={setDirty} />}
  </div>
}
