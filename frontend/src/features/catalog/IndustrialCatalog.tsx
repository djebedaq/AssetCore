import { useEffect, useMemo, useRef, useState } from 'react'
import {
  BookOpen,
  CheckCircle2,
  ChevronRight,
  Download,
  Maximize2,
  PackagePlus,
  RotateCcw,
  Search,
  ShoppingCart,
  Trash2,
  Undo2,
  ZoomIn,
  ZoomOut,
} from 'lucide-react'

import { api, createApiObjectUrl, downloadApiFile } from '../../api'
import { friendlyError } from '../../industrialUi'
import { statusText, useI18n } from '../../i18n'
import { hasPermission } from '../../permissions'
import type { Machine, MultiPartRequest } from '../../types'
import { catalogApi } from './catalogApi'
import { addPart, addRepairKit, updateCartQuantity } from './catalogState'
import type {
  AssemblyDetails,
  CatalogCartLine,
  CatalogDiagram,
  CatalogPart,
  CatalogRepairKit,
  MachineCatalog,
  PositionHotspot,
} from './catalogTypes'

type Props = {
  defaultMachineId?: number
  onUnknownPart?: () => void
}

function DiagramViewer({
  machineId,
  diagram,
  onSelect,
  onAdd,
  onVariants,
}: {
  machineId: number
  diagram: CatalogDiagram
  onSelect: (part: CatalogPart) => void
  onAdd: (part: CatalogPart) => void
  onVariants: (position: string, variants: CatalogPart[]) => void
}) {
  const { t } = useI18n()
  const [url, setUrl] = useState('')
  const [hotspots, setHotspots] = useState<PositionHotspot[]>([])
  const [zoom, setZoom] = useState(100)
  const [error, setError] = useState('')
  const viewport = useRef<HTMLDivElement>(null)

  useEffect(() => {
    let active = true
    let objectUrl = ''
    setUrl('')
    setError('')
    void Promise.all([
      createApiObjectUrl(diagram.preview_endpoint),
      catalogApi.hotspots(machineId, diagram.id),
    ]).then(([preview, items]) => {
      objectUrl = preview.url
      if (active) {
        setUrl(preview.url)
        setHotspots(items)
      }
    }).catch((caught) => setError(friendlyError(caught, t('catalog.documentPreviewError'))))
    return () => {
      active = false
      if (objectUrl) URL.revokeObjectURL(objectUrl)
    }
  }, [diagram.id, diagram.preview_endpoint, machineId, t])

  function activate(hotspot: PositionHotspot) {
    if (hotspot.variants.length === 1) {
      onSelect(hotspot.variants[0])
      onAdd(hotspot.variants[0])
      return
    }
    onVariants(hotspot.position, hotspot.variants)
  }

  return <div className="catalog-v2-diagram-panel">
    <div className="catalog-v2-diagram-toolbar">
      <span><b>{diagram.title}</b><small>{t('common.page')} {diagram.page_number}</small></span>
      <div>
        <button className="secondary compact" aria-label={t('catalog.zoomOut')} disabled={zoom <= 75} onClick={() => setZoom((value) => Math.max(75, value - 25))}><ZoomOut size={17} /></button>
        <b>{zoom}%</b>
        <button className="secondary compact" aria-label={t('catalog.zoomIn')} disabled={zoom >= 250} onClick={() => setZoom((value) => Math.min(250, value + 25))}><ZoomIn size={17} /></button>
        <button className="secondary compact" onClick={() => setZoom(100)}><RotateCcw size={16} />{t('catalog.resetView')}</button>
        <button className="secondary compact" onClick={() => void viewport.current?.requestFullscreen()}><Maximize2 size={16} />{t('catalog.fullscreen')}</button>
      </div>
    </div>
    {error && <div className="error">{error}</div>}
    <div className="catalog-v2-diagram-viewport" ref={viewport}>
      <div className="catalog-v2-diagram-canvas" style={{ width: `${zoom}%` }}>
        {!url && !error && <div className="diagram-loading">{t('common.loading')}</div>}
        {url && <img src={url} alt={diagram.title} draggable={false} />}
        {hotspots.map((hotspot) => <button
          key={hotspot.id}
          type="button"
          className="catalog-v2-hotspot"
          style={{
            left: `${hotspot.x * 100}%`,
            top: `${hotspot.y * 100}%`,
            width: `${hotspot.width * 100}%`,
            height: `${hotspot.height * 100}%`,
          }}
          title={`${t('catalog.position')} ${hotspot.position}`}
          aria-label={`${t('catalog.position')} ${hotspot.position}`}
          onClick={() => activate(hotspot)}
        >{hotspot.position}</button>)}
      </div>
    </div>
    <div className="catalog-v2-diagram-footer">
      <span>{t('catalog.panHint')}</span>
      <button className="secondary compact" onClick={() => void downloadApiFile(diagram.download_endpoint, `${diagram.source_id}.pdf`)}><Download size={16} />{t('catalog.openOriginalPdf')}</button>
    </div>
  </div>
}

function PartDetails({
  part,
  onAdd,
  onKit,
}: {
  part: CatalogPart
  onAdd: (part: CatalogPart) => void
  onKit: (code: string) => void
}) {
  const { t } = useI18n()
  return <article className="catalog-v2-part-card panel" aria-live="polite">
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

function RepairKitPreview({
  kit,
  onConfirm,
  onClose,
}: {
  kit: CatalogRepairKit
  onConfirm: () => void
  onClose: () => void
}) {
  const { t } = useI18n()
  return <div className="catalog-v2-kit-preview panel" role="dialog" aria-modal="true" aria-label={`${t('catalog.repairKit')} ${kit.code}`}>
    <div className="toolbar"><div><span className="badge batch-complete">{t('catalog.verified')}</span><h3>{t('catalog.repairKit')} {kit.code}</h3><p>{t('catalog.kitContains', { count: kit.components.length })}</p></div></div>
    <div className="catalog-v2-kit-components">{kit.components.map((component) => <div key={component.id}><b>{t('catalog.position')} {component.position} · {component.part_number || t('common.noValue')}</b><span>{component.description}</span><em>{t('catalog.sourceQuantity')}: {component.quantity_raw}</em></div>)}</div>
    <div className="actions"><button className="secondary" onClick={onClose}>{t('common.cancel')}</button><button className="primary" onClick={onConfirm}><PackagePlus size={17} />{t('catalog.addWholeKit')}</button></div>
  </div>
}

function RequestCart({
  machineId,
  lines,
  onChange,
  undoAvailable,
  onUndo,
}: {
  machineId: number
  lines: CatalogCartLine[]
  onChange: (lines: CatalogCartLine[]) => void
  undoAvailable: boolean
  onUndo: () => void
}) {
  const { locale, t } = useI18n()
  const [confirming, setConfirming] = useState(false)
  const [reason, setReason] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState('')
  const [created, setCreated] = useState('')

  async function submit() {
    setSubmitting(true)
    setError('')
    try {
      const request = await api<MultiPartRequest>('/part-requests/multi', {
        method: 'POST',
        body: JSON.stringify({
          machine_id: machineId,
          priority: 'NORMAL',
          language: locale,
          reason: reason || null,
          lines: lines.map((line) => ({
            catalog_part_id: line.catalog_part_id,
            position: line.position,
            part_number: line.part_number,
            description: line.description,
            quantity: line.quantity,
            source_document: line.source_document,
            source_page: line.source_page,
            assembly: line.assembly,
          })),
        }),
      })
      setCreated(request.request_reference)
      setConfirming(false)
      onChange([])
    } catch (caught) {
      setError(friendlyError(caught, t('parts.saveError')))
    } finally {
      setSubmitting(false)
    }
  }

  return <aside className="catalog-v2-cart panel">
    <header><ShoppingCart size={21} /><span><h3>{t('catalog.requestCart')}</h3><small>{t('catalog.selectedCount', { count: lines.length })}</small></span></header>
    {created && <div className="success" role="status"><CheckCircle2 size={18} />{t('catalog.requestCreated')} <b>{created}</b></div>}
    {error && <div className="error">{error}</div>}
    <div className="catalog-v2-cart-lines">{lines.map((line) => <div key={line.source_record_key}>
      <span><b>{t('catalog.position')} {line.position} · {line.part_number || t('common.noValue')}</b><small>{line.description}</small>{line.replacement_applied && <small className="verified">{t('catalog.oldNumber')}: {line.source_part_number}</small>}</span>
      <label>{t('catalog.requestedQuantity')}<input aria-label={`${t('catalog.requestedQuantity')} ${line.part_number}`} type="number" min="0.01" step="0.01" value={line.quantity} onChange={(event) => onChange(updateCartQuantity(lines, line.source_record_key, Number(event.target.value)))} /></label>
      <button className="link" aria-label={t('common.remove')} onClick={() => onChange(lines.filter((item) => item.source_record_key !== line.source_record_key))}><Trash2 size={16} /></button>
    </div>)}</div>
    {!lines.length && <div className="empty-state">{t('catalog.emptyCart')}</div>}
    {undoAvailable && <button className="secondary" onClick={onUndo}><Undo2 size={16} />{t('catalog.undoKitAddition')}</button>}
    {lines.length > 0 && <div className="catalog-v2-cart-actions"><button className="link" onClick={() => onChange([])}>{t('catalog.clearCart')}</button>{hasPermission('requests.create') && <button className="primary" onClick={() => setConfirming(true)}>{t('catalog.createRequest')}</button>}</div>}
    {confirming && <div className="catalog-v2-confirmation" role="dialog" aria-modal="true">
      <h4>{t('requests.confirm')}</h4>
      <p>{t('catalog.confirmRequestSummary', { count: lines.length })}</p>
      <div>{lines.map((line) => <span key={line.source_record_key}><b>{line.part_number || t('common.noValue')}</b> × {line.quantity}</span>)}</div>
      <label>{t('parts.reason')}<textarea value={reason} onChange={(event) => setReason(event.target.value)} /></label>
      <div className="actions"><button className="secondary" disabled={submitting} onClick={() => setConfirming(false)}>{t('common.cancel')}</button><button className="primary" disabled={submitting} onClick={() => void submit()}>{submitting ? t('common.loading') : t('requests.submit')}</button></div>
    </div>}
  </aside>
}

export function IndustrialCatalog({ defaultMachineId, onUnknownPart }: Props = {}) {
  const { t } = useI18n()
  const [machines, setMachines] = useState<Machine[]>([])
  const [machineId, setMachineId] = useState<number | ''>(defaultMachineId || '')
  const [context, setContext] = useState<MachineCatalog | null>(null)
  const [sourceId, setSourceId] = useState('')
  const [details, setDetails] = useState<AssemblyDetails | null>(null)
  const [diagramId, setDiagramId] = useState<number | ''>('')
  const [partsQuery, setPartsQuery] = useState('')
  const [selectedPart, setSelectedPart] = useState<CatalogPart | null>(null)
  const [variantChoice, setVariantChoice] = useState<{ position: string; variants: CatalogPart[] } | null>(null)
  const [kits, setKits] = useState<CatalogRepairKit[]>([])
  const [kitPreview, setKitPreview] = useState<CatalogRepairKit | null>(null)
  const [cart, setCart] = useState<CatalogCartLine[]>([])
  const [undoCart, setUndoCart] = useState<CatalogCartLine[] | null>(null)
  const [toast, setToast] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    void api<Machine[]>('/machines')
      .then(setMachines)
      .catch((caught) => setError(friendlyError(caught, t('catalog.loadError'))))
  }, [t])
  useEffect(() => {
    if (defaultMachineId) setMachineId(defaultMachineId)
  }, [defaultMachineId])
  useEffect(() => {
    setContext(null)
    setDetails(null)
    setSourceId('')
    setSelectedPart(null)
    setKits([])
    setError('')
    if (!machineId) return
    setLoading(true)
    void catalogApi.machine(machineId)
      .then((value) => {
        setContext(value)
        setSourceId(value.assemblies[0]?.source_id || '')
      })
      .catch((caught) => setError(friendlyError(caught, t('catalog.loadError'))))
      .finally(() => setLoading(false))
  }, [machineId, t])
  useEffect(() => {
    setDetails(null)
    setSelectedPart(null)
    setKitPreview(null)
    if (!machineId || !sourceId) return
    setLoading(true)
    void Promise.all([
      catalogApi.assembly(machineId, sourceId),
      catalogApi.repairKits(machineId, sourceId),
    ]).then(([assembly, repairKits]) => {
      setDetails(assembly)
      setKits(repairKits)
      setDiagramId(assembly.diagrams[0]?.id || '')
      setError('')
    }).catch((caught) => setError(friendlyError(caught, t('catalog.loadError'))))
      .finally(() => setLoading(false))
  }, [machineId, sourceId, t])

  const machine = machines.find((item) => item.id === machineId)
  const diagram = details?.diagrams.find((item) => item.id === diagramId)
  const filteredParts = useMemo(() => {
    const query = partsQuery.trim().toLocaleLowerCase()
    if (!query) return details?.parts || []
    return (details?.parts || []).filter((part) => [
      part.position,
      part.part_number,
      part.replaced_by_part_number,
      part.description,
      part.original_name,
      part.description_2,
      part.repair_kit_code,
      part.valid_for_raw,
    ].some((value) => value?.toLocaleLowerCase().includes(query)))
  }, [details, partsQuery])

  function addSelectedPart(part: CatalogPart) {
    setCart((current) => addPart(current, part))
    setUndoCart(null)
    setToast(t('catalog.positionAdded', { position: part.position }))
  }
  function openKit(code: string) {
    setKitPreview(kits.find((kit) => kit.code === code) || null)
  }
  function confirmKit(kit: CatalogRepairKit) {
    if (!details) return
    setUndoCart(cart)
    setCart(addRepairKit(cart, kit, details.parts))
    setKitPreview(null)
    setToast(t('catalog.kitAdded', { code: kit.code }))
  }

  return <>
    <div className="toolbar"><div><h3>{t('catalog.title')}</h3><p className="muted">{t('catalog.machineFirstHint')}</p></div></div>
    {toast && <div className="success catalog-v2-toast" role="status"><CheckCircle2 size={18} />{toast}<button className="link" onClick={() => setToast('')}>{t('common.close')}</button></div>}
    {error && <div className="error">{error}</div>}
    <section className="catalog-v2-machine panel">
      <label>{t('catalog.chooseMachine')}<select value={machineId} onChange={(event) => setMachineId(event.target.value ? Number(event.target.value) : '')}><option value="">{t('catalog.chooseMachinePlaceholder')}</option>{machines.map((item) => <option value={item.id} key={item.id}>№{item.inventory_number} · {item.brand} {item.model || ''}</option>)}</select></label>
      {machine && <div><b>№{machine.inventory_number} · {machine.brand}</b><span>{machine.model || t('common.noValue')}</span><small>{t('machines.pressure')}: {machine.pressure_bar ?? t('common.noValue')} · {t('common.status')}: {statusText(t, machine.status)} · {t('common.location')}: {machine.location?.name || t('common.noValue')}</small></div>}
      {context?.supported && <label>{t('catalog.chooseAssembly')}<select value={sourceId} onChange={(event) => setSourceId(event.target.value)}>{context.assemblies.map((assembly) => <option key={assembly.source_id} value={assembly.source_id}>{assembly.title} · {assembly.part_count}</option>)}</select></label>}
    </section>
    {loading && <div className="empty-state">{t('common.loading')}</div>}
    {!machineId && !loading && <div className="empty-state visual-catalog-empty"><BookOpen size={36} /><h3>{t('catalog.chooseMachineTitle')}</h3><p>{t('catalog.chooseMachineExplanation')}</p></div>}
    {context && !context.supported && <div className="empty-state visual-catalog-empty"><BookOpen size={36} /><h3>{context.message}</h3>{onUnknownPart && hasPermission('requests.create') && <button className="secondary" onClick={onUnknownPart}>{t('unknownPart.new')}</button>}</div>}
    {details && machineId && <div className="catalog-v2-layout">
      <main className="catalog-v2-workspace">
        <nav className="catalog-v2-diagram-tabs" aria-label={t('catalog.visualWorkspace')}>{details.diagrams.map((item) => <button className={item.id === diagramId ? 'active' : ''} key={item.id} onClick={() => setDiagramId(item.id)}>{t('common.page')} {item.page_number}</button>)}</nav>
        {diagram && <DiagramViewer machineId={machineId} diagram={diagram} onSelect={setSelectedPart} onAdd={addSelectedPart} onVariants={(position, variants) => setVariantChoice({ position, variants })} />}
        {!diagram && <div className="empty-state">{t('catalog.noVerifiedDiagram')}</div>}
        {variantChoice && <div className="catalog-v2-variants panel" role="dialog" aria-label={t('catalog.variantChoice', { position: variantChoice.position })}><h3>{t('catalog.variantChoice', { position: variantChoice.position })}</h3>{variantChoice.variants.map((part) => <button key={part.source_record_key} onClick={() => { setSelectedPart(part); setVariantChoice(null) }}><span><b>{part.part_number || t('common.noValue')}</b><small>{part.description}</small><em>{part.valid_for_raw || t('common.noValue')}</em></span><ChevronRight size={17} /></button>)}<button className="secondary" onClick={() => setVariantChoice(null)}>{t('common.cancel')}</button></div>}
        <section className="catalog-v2-parts">
          <div className="searchbox"><Search size={17} /><input value={partsQuery} onChange={(event) => setPartsQuery(event.target.value)} placeholder={t('catalog.searchPositions')} /></div>
          <div className="table-card"><table><thead><tr><th>{t('catalog.position')}</th><th>{t('common.partNumber')}</th><th>{t('catalog.description')}</th><th>{t('catalog.sourceQuantity')}</th><th>{t('catalog.repairKit')}</th></tr></thead><tbody>{filteredParts.map((part) => <tr className={selectedPart?.source_record_key === part.source_record_key ? 'selected-catalog-row' : ''} key={part.source_record_key} tabIndex={0} onClick={() => setSelectedPart(part)} onKeyDown={(event) => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); setSelectedPart(part) } }}><td><b>{part.position}</b></td><td><code>{part.part_number || t('common.noValue')}</code>{part.replaced_by_part_number && <small>→ {part.replaced_by_part_number}</small>}</td><td>{part.description}<small>{part.valid_for_raw}</small></td><td>{part.quantity_raw || t('common.noValue')}</td><td>{part.repair_kit_code || t('common.noValue')}</td></tr>)}</tbody></table></div>
          {!filteredParts.length && <div className="empty-state">{t('catalog.empty')}</div>}
        </section>
        {selectedPart && <PartDetails part={selectedPart} onAdd={addSelectedPart} onKit={openKit} />}
        <section className="catalog-v2-kits"><div className="toolbar"><div><h3>{t('catalog.kits')}</h3><p className="muted">{t('catalog.kitsHint')}</p></div></div><div>{kits.map((kit) => <button key={kit.id} onClick={() => setKitPreview(kit)}><span className="badge batch-complete">{t('catalog.verified')}</span><b>{kit.code}</b><small>{t('catalog.kitContains', { count: kit.components.length })}</small><ChevronRight size={17} /></button>)}</div>{!kits.length && <div className="empty-state">{t('catalog.noKits')}</div>}</section>
        {kitPreview && <RepairKitPreview kit={kitPreview} onClose={() => setKitPreview(null)} onConfirm={() => confirmKit(kitPreview)} />}
        {onUnknownPart && hasPermission('requests.create') && <button className="secondary catalog-v2-unknown" onClick={onUnknownPart}>{t('unknownPart.notFound')}</button>}
      </main>
      <RequestCart machineId={machineId} lines={cart} onChange={setCart} undoAvailable={undoCart !== null} onUndo={() => { if (undoCart) setCart(undoCart); setUndoCart(null); setToast(t('catalog.kitAdditionUndone')) }} />
    </div>}
  </>
}
