import { Layers3, PackagePlus, X } from 'lucide-react'

import { useI18n } from '../../i18n'
import { hasPermission } from '../../permissions'
import type { CatalogPart, CatalogRepairKit } from './catalogTypes'

export function CatalogPartDetails({
  part,
  onAdd,
  onKit,
  onClose,
}: {
  part: CatalogPart
  onAdd: (part: CatalogPart) => void
  onKit: (code: string) => void
  onClose: () => void
}) {
  const { t } = useI18n()
  return <article className="catalog-v2-part-card panel" aria-live="polite">
    <button className="link catalog-v2-part-close" aria-label={t('common.close')} onClick={onClose}><X size={18} /></button>
    <header>
      <span className="badge batch-complete">{t('catalog.verified')}</span>
      <h3>{t('catalog.position')} {part.position} · <code>{part.part_number || t('common.noValue')}</code></h3>
      <p>{part.description}</p>
    </header>
    {part.replaced_by_part_number && <div className="catalog-v2-replacement" role="status">
      <b>{t('catalog.oldNumber')}: {part.part_number}</b>
      <span>{t('catalog.replacedWith')}: {part.replaced_by_part_number}</span>
      <small>{t('catalog.replacementRequestNotice', { number: part.replaced_by_part_number })}</small>
    </div>}
    <dl className="detail-grid">
      <div><dt>{t('catalog.originalDescription')}</dt><dd>{part.original_name || part.description}</dd></div>
      <div><dt>{t('catalog.specification')}</dt><dd>{part.description_2 || t('common.noValue')}</dd></div>
      <div><dt>{t('catalog.sourceQuantity')}</dt><dd>{part.quantity_raw || t('common.noValue')}</dd></div>
      <div><dt>{t('catalog.assembly')}</dt><dd>{part.assembly}</dd></div>
      <div><dt>{t('catalog.validFor')}</dt><dd>{part.valid_for_raw || t('common.noValue')}</dd></div>
      <div><dt>{t('catalog.repairKit')}</dt><dd>{part.repair_kit_code ? <button className="link" onClick={() => onKit(part.repair_kit_code as string)}>{part.repair_kit_code}</button> : t('common.noValue')}</dd></div>
      <div><dt>{t('catalog.sourceDocument')}</dt><dd>{part.source_document}</dd></div>
      <div><dt>{t('common.page')}</dt><dd>{part.source_page}</dd></div>
    </dl>
    <details className="catalog-v2-technical-details">
      <summary>{t('catalog.technicalDetails')}</summary>
      <code>SHA-256 {part.source_document_sha256}</code>
      <span>{part.source_version} · {part.source_record_key}</span>
      <span>{part.verification_status}</span>
    </details>
    {hasPermission('requests.create') && <button className="primary" onClick={() => onAdd(part)}><PackagePlus size={17} />{t('catalog.addToRequest')}</button>}
  </article>
}

export function CatalogRepairKitPreview({
  kit,
  positionsVisible,
  onTogglePositions,
  onConfirm,
  onClose,
}: {
  kit: CatalogRepairKit
  positionsVisible: boolean
  onTogglePositions: () => void
  onConfirm: () => void
  onClose: () => void
}) {
  const { t } = useI18n()
  return <div className="catalog-v2-kit-preview panel" role="dialog" aria-modal="true" aria-label={`${t('catalog.repairKit')} ${kit.code}`}>
    <div className="toolbar"><div><span className="badge batch-complete">{t('catalog.verified')}</span><h3>{t('catalog.repairKit')} {kit.code}</h3><p>{t('catalog.kitContains', { count: kit.components.length })}</p></div></div>
    <button className={`secondary ${positionsVisible ? 'active' : ''}`} aria-pressed={positionsVisible} onClick={onTogglePositions}><Layers3 size={17} />{positionsVisible ? t('catalog.hideKitPositions') : t('catalog.showKitPositions')}</button>
    <div className="catalog-v2-kit-components">{kit.components.map((component) => <div key={component.id}><b>{t('catalog.position')} {component.position} · {component.part_number || t('common.noValue')}</b><span>{component.description}</span><em>{t('catalog.sourceQuantity')}: {component.quantity_raw}</em></div>)}</div>
    <div className="actions"><button className="secondary" onClick={onClose}>{t('common.cancel')}</button><button className="primary" onClick={onConfirm}><PackagePlus size={17} />{t('catalog.addWholeKit')}</button></div>
  </div>
}
