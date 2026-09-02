import { type ReactNode, useEffect, useId, useRef } from 'react'
import { ChevronRight, Layers3, PackagePlus, X } from 'lucide-react'

import { useI18n } from '../../i18n'
import { hasPermission } from '../../permissions'
import { catalogDisplayName, catalogSourceDescription } from './catalogNames'
import type { CatalogPart, CatalogRepairKit } from './catalogTypes'
import { formatCatalogSourceQuantity } from '../partRequests/partRequestQuantities'

const FOCUSABLE_ELEMENTS = [
  'a[href]',
  'button:not([disabled])',
  'input:not([disabled])',
  'select:not([disabled])',
  'textarea:not([disabled])',
  '[tabindex]:not([tabindex="-1"])',
].join(',')

function CatalogDialog({
  title,
  onClose,
  children,
  contentClassName = '',
}: {
  title: string
  onClose: () => void
  children: ReactNode
  contentClassName?: string
}) {
  const { t } = useI18n()
  const titleId = useId()
  const dialog = useRef<HTMLDivElement>(null)
  const closeButton = useRef<HTMLButtonElement>(null)
  const onCloseRef = useRef(onClose)

  useEffect(() => { onCloseRef.current = onClose }, [onClose])

  useEffect(() => {
    const previouslyFocused = document.activeElement instanceof HTMLElement
      ? document.activeElement
      : null
    const previousOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'

    function keyDown(event: KeyboardEvent) {
      if (event.key === 'Escape') {
        event.preventDefault()
        onCloseRef.current()
        return
      }
      if (event.key !== 'Tab' || !dialog.current) return
      const focusable = [...dialog.current.querySelectorAll<HTMLElement>(FOCUSABLE_ELEMENTS)]
      if (!focusable.length) {
        event.preventDefault()
        dialog.current.focus({ preventScroll: true })
        return
      }
      const first = focusable[0]
      const last = focusable[focusable.length - 1]
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault()
        last.focus({ preventScroll: true })
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault()
        first.focus({ preventScroll: true })
      }
    }

    document.addEventListener('keydown', keyDown)
    closeButton.current?.focus({ preventScroll: true })
    return () => {
      document.removeEventListener('keydown', keyDown)
      document.body.style.overflow = previousOverflow
      previouslyFocused?.focus({ preventScroll: true })
    }
  }, [])

  return <div
    className="catalog-v2-part-overlay"
    onClick={(event) => { if (event.target === event.currentTarget) onCloseRef.current() }}
  >
    <div
      ref={dialog}
      className="catalog-v2-part-dialog"
      role="dialog"
      aria-modal="true"
      aria-labelledby={titleId}
      tabIndex={-1}
    >
      <header className="catalog-v2-part-dialog-header">
        <h3 id={titleId}>{title}</h3>
        <button ref={closeButton} type="button" className="catalog-v2-part-dialog-close" aria-label={t('common.close')} onClick={() => onCloseRef.current()}><X size={22} /></button>
      </header>
      <div className={`catalog-v2-part-dialog-content ${contentClassName}`.trim()}>{children}</div>
    </div>
  </div>
}

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
  const title = `${t('catalog.position')} ${part.position} · ${part.part_number || t('common.noValue')}`
  return <CatalogDialog title={title} onClose={onClose} contentClassName="catalog-v2-part-details-scroll">
    <article className="catalog-v2-part-details" aria-live="polite">
    <header>
      <span className="badge batch-complete">{t('catalog.verified')}</span>
      <p>{catalogDisplayName(part)}</p>
    </header>
    {part.replaced_by_part_number && <div className="catalog-v2-replacement" role="status">
      <b>{t('catalog.oldNumber')}: {part.part_number}</b>
      <span>{t('catalog.replacedWith')}: {part.replaced_by_part_number}</span>
      <small>{t('catalog.replacementRequestNotice', { number: part.replaced_by_part_number })}</small>
    </div>}
    <dl className="detail-grid">
      <div><dt>{t('catalog.displayName')}</dt><dd>{catalogDisplayName(part)}</dd></div>
      <div><dt>{t('catalog.originalDescription')}</dt><dd>{catalogSourceDescription(part)}</dd></div>
      <div><dt>{t('catalog.specification')}</dt><dd>{part.description_2 || t('common.noValue')}</dd></div>
      <div><dt>{t('catalog.sourceQuantity')}</dt><dd>{formatCatalogSourceQuantity(part.quantity, part.quantity_raw) || t('common.noValue')}</dd></div>
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
      <span>{part.translation_version} · {t(part.translation_qa_status === 'VERIFIED' ? 'catalog.translationVerified' : 'catalog.translationNeedsReview')}</span>
    </details>
    {hasPermission('requests.create') && <button className="primary" onClick={() => onAdd(part)}><PackagePlus size={17} />{t('catalog.addToRequest')}</button>}
    </article>
  </CatalogDialog>
}

export function CatalogVariantDialog({
  position,
  variants,
  onSelect,
  onClose,
}: {
  position: string
  variants: CatalogPart[]
  onSelect: (part: CatalogPart) => void
  onClose: () => void
}) {
  const { t } = useI18n()
  return <CatalogDialog title={t('catalog.variantChoice', { position })} onClose={onClose} contentClassName="catalog-v2-variants-dialog">
    <div className="catalog-v2-variants-list">
      {variants.map((part) => <button key={part.source_record_key} onClick={() => onSelect(part)}>
        <span><b>{part.part_number || t('common.noValue')}</b><small>{catalogDisplayName(part)}</small><em>{part.valid_for_raw || t('common.noValue')}</em></span>
        <ChevronRight size={17} />
      </button>)}
    </div>
  </CatalogDialog>
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
  return <CatalogDialog title={`${t('catalog.repairKit')} ${kit.code}`} onClose={onClose} contentClassName="catalog-v2-kit-dialog">
    <div className="catalog-v2-kit-preview">
    <div className="toolbar"><div><span className="badge batch-complete">{t('catalog.verified')}</span><h3>{t('catalog.repairKit')} {kit.code}</h3><p>{t('catalog.kitContains', { count: kit.components.length })}</p></div></div>
    <button className={`secondary ${positionsVisible ? 'active' : ''}`} aria-pressed={positionsVisible} onClick={onTogglePositions}><Layers3 size={17} />{positionsVisible ? t('catalog.hideKitPositions') : t('catalog.showKitPositions')}</button>
    <div className="catalog-v2-kit-components">{kit.components.map((component) => <div key={component.id}><b>{t('catalog.position')} {component.position} · {component.part_number || t('common.noValue')}</b><span>{catalogDisplayName(component)}</span><em>{t('catalog.sourceQuantity')}: {formatCatalogSourceQuantity(component.quantity, component.quantity_raw)}</em></div>)}</div>
    <div className="actions"><button className="secondary" onClick={onClose}>{t('common.cancel')}</button><button className="primary" onClick={onConfirm}><PackagePlus size={17} />{t('catalog.addWholeKit')}</button></div>
    </div>
  </CatalogDialog>
}
