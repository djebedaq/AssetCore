import { useEffect, useRef, useState } from 'react'
import { LocateFixed, Search } from 'lucide-react'

import { useI18n } from '../../i18n'
import { catalogDisplayName } from './catalogNames'
import type { CatalogPart } from './catalogTypes'
import { formatCatalogSourceQuantity } from '../partRequests/partRequestQuantities'

export function CatalogPartsTable({
  parts,
  query,
  selectedPart,
  diagramPositions,
  onQueryChange,
  onSelect,
  onShowDiagram,
}: {
  parts: CatalogPart[]
  query: string
  selectedPart: CatalogPart | null
  diagramPositions: Set<string>
  onQueryChange: (value: string) => void
  onSelect: (part: CatalogPart) => void
  onShowDiagram: (part: CatalogPart) => void
}) {
  const { t } = useI18n()
  const [position, setPosition] = useState('')
  const [navigatorError, setNavigatorError] = useState('')
  const rows = useRef(new Map<string, HTMLTableRowElement>())

  useEffect(() => {
    if (!selectedPart) return
    const row = rows.current.get(selectedPart.source_record_key)
    if (row && typeof row.scrollIntoView === 'function') {
      row.scrollIntoView({ block: 'nearest', behavior: 'smooth' })
    }
  }, [selectedPart])

  function navigate() {
    const normalized = position.trim()
    const part = parts.find((item) => item.position === normalized)
    if (!part || !diagramPositions.has(normalized)) {
      setNavigatorError(t('catalog.positionNotOnDiagram', { position: normalized || '—' }))
      return
    }
    setNavigatorError('')
    onSelect(part)
    onShowDiagram(part)
  }

  return <section className="catalog-v2-parts">
    <div className="catalog-v2-search-tools">
      <div className="searchbox"><Search size={17} /><input value={query} onChange={(event) => onQueryChange(event.target.value)} placeholder={t('catalog.searchPositions')} /></div>
      <div className="catalog-v2-position-navigator">
        <label>{t('catalog.positionNavigator')}<input value={position} onChange={(event) => setPosition(event.target.value)} onKeyDown={(event) => { if (event.key === 'Enter') navigate() }} inputMode="numeric" /></label>
        <button className="secondary compact" onClick={navigate}><LocateFixed size={17} />{t('catalog.showOnDiagram')}</button>
      </div>
    </div>
    {navigatorError && <div className="error">{navigatorError}</div>}
    <div className="table-card"><table><thead><tr><th>{t('catalog.position')}</th><th>{t('common.partNumber')}</th><th>{t('catalog.displayName')}</th><th>{t('catalog.sourceQuantity')}</th><th>{t('catalog.repairKit')}</th><th><span className="sr-only">{t('catalog.showOnDiagram')}</span></th></tr></thead><tbody>{parts.map((part) => <tr
      ref={(element) => { if (element) rows.current.set(part.source_record_key, element); else rows.current.delete(part.source_record_key) }}
      className={selectedPart?.source_record_key === part.source_record_key ? 'selected-catalog-row' : ''}
      key={part.source_record_key}
      tabIndex={0}
      onClick={() => onSelect(part)}
      onKeyDown={(event) => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); onSelect(part) } }}
    >
      <td><b>{part.position}</b></td>
      <td><code>{part.part_number || t('common.noValue')}</code>{part.replaced_by_part_number && <small>→ {part.replaced_by_part_number}</small>}</td>
      <td>{catalogDisplayName(part)}<small>{part.valid_for_raw}</small></td>
      <td>{formatCatalogSourceQuantity(part.quantity, part.quantity_raw) || t('common.noValue')}</td>
      <td>{part.repair_kit_code || t('common.noValue')}</td>
      <td>{diagramPositions.has(part.position) && <button className="link" aria-label={`${t('catalog.showOnDiagram')} ${part.position}`} onClick={(event) => { event.stopPropagation(); onSelect(part); onShowDiagram(part) }}><LocateFixed size={17} /><span>{t('catalog.showOnDiagram')}</span></button>}</td>
    </tr>)}</tbody></table></div>
    {!parts.length && <div className="empty-state">{t('catalog.empty')}</div>}
  </section>
}
