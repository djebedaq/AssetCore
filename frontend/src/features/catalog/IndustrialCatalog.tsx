import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { BookOpen, CheckCircle2, ChevronRight } from 'lucide-react'

import { api } from '../../api'
import { friendlyError } from '../../industrialUi'
import { statusText, useI18n } from '../../i18n'
import { hasPermission } from '../../permissions'
import type { Machine } from '../../types'
import { CatalogDiagramViewer, type DiagramFocus } from './CatalogDiagramViewer'
import { CatalogPartsTable } from './CatalogPartsTable'
import { CatalogRequestCart } from './CatalogRequestCart'
import { CatalogPartDetails, CatalogRepairKitPreview, CatalogVariantDialog } from './CatalogSelectionPanels'
import { catalogApi } from './catalogApi'
import { addPart, addRepairKit } from './catalogState'
import type { AssemblyDetails, CatalogCartLine, CatalogPart, CatalogRepairKit, MachineCatalog, PositionHotspot } from './catalogTypes'

type Props = { defaultMachineId?: number; onUnknownPart?: () => void }
type MachineCartState = { machineId: number | null; lines: CatalogCartLine[] }
const EMPTY_MACHINE_CART: MachineCartState = { machineId: null, lines: [] }

export function IndustrialCatalog({ defaultMachineId, onUnknownPart }: Props = {}) {
  const { t } = useI18n()
  const [machines, setMachines] = useState<Machine[]>([])
  const [machineId, setMachineId] = useState<number | ''>(defaultMachineId || '')
  const previousDefaultMachineId = useRef(defaultMachineId)
  const [pendingMachineId, setPendingMachineId] = useState<number | '' | null>(null)
  const [context, setContext] = useState<MachineCatalog | null>(null)
  const [sourceId, setSourceId] = useState('')
  const [details, setDetails] = useState<AssemblyDetails | null>(null)
  const [diagramId, setDiagramId] = useState<number | ''>('')
  const [hotspotsByDiagram, setHotspotsByDiagram] = useState<Record<number, PositionHotspot[]>>({})
  const [focus, setFocus] = useState<DiagramFocus>(null)
  const [partsQuery, setPartsQuery] = useState('')
  const [selectedPosition, setSelectedPosition] = useState<string | null>(null)
  const [selectedPart, setSelectedPart] = useState<CatalogPart | null>(null)
  const [variantChoice, setVariantChoice] = useState<{ position: string; variants: CatalogPart[] } | null>(null)
  const [kits, setKits] = useState<CatalogRepairKit[]>([])
  const [kitPreview, setKitPreview] = useState<CatalogRepairKit | null>(null)
  const [kitPositions, setKitPositions] = useState<Set<string>>(new Set())
  const [cart, setCart] = useState<MachineCartState>(EMPTY_MACHINE_CART)
  const [undoCart, setUndoCart] = useState<MachineCartState | null>(null)
  const [toast, setToast] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  const applyMachineSelection = useCallback((nextMachineId: number | '') => {
    setCart(EMPTY_MACHINE_CART); setUndoCart(null); setToast(''); setSelectedPart(null); setSelectedPosition(null)
    setVariantChoice(null); setKitPreview(null); setKitPositions(new Set()); setContext(null)
    setDetails(null); setDiagramId(''); setHotspotsByDiagram({}); setFocus(null); setSourceId('')
    setPartsQuery(''); setKits([]); setError(''); setPendingMachineId(null); setMachineId(nextMachineId)
  }, [])

  useEffect(() => {
    void api<Machine[]>('/machines').then(setMachines).catch((caught) => setError(friendlyError(caught, t('catalog.loadError'))))
  }, [t])
  useEffect(() => {
    const previous = previousDefaultMachineId.current
    previousDefaultMachineId.current = defaultMachineId
    if (defaultMachineId !== undefined && defaultMachineId !== previous && defaultMachineId !== machineId) applyMachineSelection(defaultMachineId)
  }, [applyMachineSelection, defaultMachineId, machineId])
  useEffect(() => {
    let active = true
    setContext(null); setDetails(null); setSourceId(''); setSelectedPart(null); setSelectedPosition(null); setKits([]); setError('')
    if (!machineId) return
    setLoading(true)
    void catalogApi.machine(machineId).then((value) => {
      if (active) { setContext(value); setSourceId(value.assemblies[0]?.source_id || '') }
    }).catch((caught) => { if (active) setError(friendlyError(caught, t('catalog.loadError'))) })
      .finally(() => { if (active) setLoading(false) })
    return () => { active = false }
  }, [machineId, t])
  useEffect(() => {
    let active = true
    setDetails(null); setSelectedPart(null); setSelectedPosition(null); setVariantChoice(null); setKitPreview(null)
    setKitPositions(new Set()); setHotspotsByDiagram({})
    if (!machineId || !sourceId || context?.machine_id !== machineId || !context.assemblies.some((assembly) => assembly.source_id === sourceId)) return
    setLoading(true)
    void Promise.all([catalogApi.assembly(machineId, sourceId), catalogApi.repairKits(machineId, sourceId)]).then(async ([assembly, repairKits]) => {
      const entries = await Promise.all(assembly.diagrams.map(async (item) => [item.id, await catalogApi.hotspots(machineId, item.id)] as const))
      if (active) {
        setDetails(assembly); setKits(repairKits); setDiagramId(assembly.diagrams[0]?.id || '')
        setHotspotsByDiagram(Object.fromEntries(entries)); setError('')
      }
    }).catch((caught) => { if (active) setError(friendlyError(caught, t('catalog.loadError'))) })
      .finally(() => { if (active) setLoading(false) })
    return () => { active = false }
  }, [context, machineId, sourceId, t])

  const machine = machines.find((item) => item.id === machineId)
  const diagram = details?.diagrams.find((item) => item.id === diagramId)
  const currentHotspots = diagram ? hotspotsByDiagram[diagram.id] || [] : []
  const allHotspots = useMemo(() => Object.entries(hotspotsByDiagram).flatMap(([id, items]) => items.map((hotspot) => ({ diagramId: Number(id), hotspot }))), [hotspotsByDiagram])
  const diagramPositions = useMemo(() => new Set(allHotspots.map((item) => item.hotspot.position)), [allHotspots])
  const filteredParts = useMemo(() => {
    const query = partsQuery.trim().toLocaleLowerCase()
    if (!query) return details?.parts || []
    return (details?.parts || []).filter((part) => [part.position, part.part_number, part.replaced_by_part_number, part.description, part.original_name, part.description_2, part.repair_kit_code, part.valid_for_raw].some((value) => value?.toLocaleLowerCase().includes(query)))
  }, [details, partsQuery])

  function focusPartOnDiagram(part: CatalogPart) {
    const here = currentHotspots.find((item) => item.position === part.position)
    const match = here ? { diagramId: Number(diagramId), hotspot: here } : allHotspots.find((item) => item.hotspot.position === part.position)
    if (!match) { setError(t('catalog.positionNotOnDiagram', { position: part.position })); return }
    setDiagramId(match.diagramId); setFocus({ position: part.position, nonce: Date.now() }); setError('')
  }
  function selectPartFromTable(part: CatalogPart) { setSelectedPosition(part.position); setSelectedPart(part); focusPartOnDiagram(part) }
  function selectDiagramPosition(position: string) {
    setSelectedPosition(position)
    setSelectedPart(null)
    setVariantChoice(null)
  }
  function openDiagramPosition(position: string, variants: CatalogPart[]) {
    setSelectedPosition(position)
    if (variants.length === 1) { setSelectedPart(variants[0]); setVariantChoice(null) }
    else setVariantChoice({ position, variants })
  }
  function addSelectedPart(part: CatalogPart) {
    if (!machineId) return
    if (cart.lines.length > 0 && cart.machineId !== machineId) { setError(t('catalog.cartMachineMismatch')); return }
    setCart((current) => ({ machineId, lines: addPart(current.lines, part) })); setUndoCart(null)
    setToast(t('catalog.positionAdded', { position: part.position }))
  }
  function openKit(code: string) {
    setKitPreview(kits.find((kit) => kit.code === code) || null)
    setKitPositions(new Set())
    setSelectedPart(null)
  }
  function toggleKitPositions(kit: CatalogRepairKit) {
    if (kitPositions.size) { setKitPositions(new Set()); return }
    const positions = new Set(kit.components.map((component) => component.position))
    setKitPositions(positions)
    const firstPart = details?.parts.find((part) => positions.has(part.position) && diagramPositions.has(part.position))
    if (firstPart) focusPartOnDiagram(firstPart)
  }
  function confirmKit(kit: CatalogRepairKit) {
    if (!details || !machineId) return
    if (cart.lines.length > 0 && cart.machineId !== machineId) { setError(t('catalog.cartMachineMismatch')); return }
    setUndoCart(cart); setCart({ machineId, lines: addRepairKit(cart.lines, kit, details.parts) })
    setKitPreview(null); setKitPositions(new Set()); setToast(t('catalog.kitAdded', { code: kit.code }))
  }
  function changeCart(lines: CatalogCartLine[]) {
    setCart((current) => ({ machineId: lines.length ? current.machineId : null, lines })); if (!lines.length) setUndoCart(null)
  }
  function requestMachineSelection(nextMachineId: number | '') {
    if (nextMachineId === machineId) return
    if (cart.lines.length > 0) setPendingMachineId(nextMachineId); else applyMachineSelection(nextMachineId)
  }

  return <>
    <div className="toolbar"><div><h3>{t('catalog.title')}</h3><p className="muted">{t('catalog.machineFirstHint')}</p></div></div>
    {toast && <div className="success catalog-v2-toast" role="status"><CheckCircle2 size={18} />{toast}<button className="link" onClick={() => setToast('')}>{t('common.close')}</button></div>}
    {error && <div className="error">{error}</div>}
    <section className="catalog-v2-machine panel">
      <label>{t('catalog.chooseMachine')}<select value={machineId} onChange={(event) => requestMachineSelection(event.target.value ? Number(event.target.value) : '')}><option value="">{t('catalog.chooseMachinePlaceholder')}</option>{machines.map((item) => <option value={item.id} key={item.id}>№{item.inventory_number} · {item.brand} {item.model || ''}</option>)}</select></label>
      {machine && <div><b>№{machine.inventory_number} · {machine.brand}</b><span>{machine.model || t('common.noValue')}</span><small>{t('machines.pressure')}: {machine.pressure_bar ?? t('common.noValue')} · {t('common.status')}: {statusText(t, machine.status)} · {t('common.location')}: {machine.location?.name || t('common.noValue')}</small></div>}
      {context?.supported && <label>{t('catalog.chooseAssembly')}<select value={sourceId} onChange={(event) => setSourceId(event.target.value)}>{context.assemblies.map((assembly) => <option key={assembly.source_id} value={assembly.source_id}>{assembly.title} · {assembly.part_count}</option>)}</select></label>}
    </section>
    {pendingMachineId !== null && <div className="catalog-v2-machine-switch panel" role="dialog" aria-modal="true" aria-labelledby="catalog-machine-switch-title"><h3 id="catalog-machine-switch-title">{t('catalog.changeMachineTitle')}</h3><p>{t('catalog.changeMachineWarning')}</p><div className="actions"><button className="secondary" onClick={() => setPendingMachineId(null)}>{t('common.cancel')}</button><button className="primary" onClick={() => applyMachineSelection(pendingMachineId)}>{t('catalog.changeMachineConfirm')}</button></div></div>}
    {loading && <div className="empty-state">{t('common.loading')}</div>}
    {!machineId && !loading && <div className="empty-state visual-catalog-empty"><BookOpen size={36} /><h3>{t('catalog.chooseMachineTitle')}</h3><p>{t('catalog.chooseMachineExplanation')}</p></div>}
    {context && !context.supported && <div className="empty-state visual-catalog-empty"><BookOpen size={36} /><h3>{context.message}</h3>{onUnknownPart && hasPermission('requests.create') && <button className="secondary" onClick={onUnknownPart}>{t('unknownPart.new')}</button>}</div>}
    {details && machineId && <div className="catalog-v2-layout">
      <main className="catalog-v2-workspace">
        <nav className="catalog-v2-diagram-tabs" aria-label={t('catalog.visualWorkspace')}>{details.diagrams.map((item) => <button className={item.id === diagramId ? 'active' : ''} key={item.id} onClick={() => setDiagramId(item.id)}>{t('common.page')} {item.page_number}</button>)}</nav>
        {diagram && <CatalogDiagramViewer machineId={machineId} diagram={diagram} hotspots={currentHotspots} selectedPosition={selectedPosition} focus={focus} kitPositions={kitPositions} onSelectPosition={selectDiagramPosition} onOpenPosition={openDiagramPosition} onHotspotsChange={(items) => setHotspotsByDiagram((current) => ({ ...current, [diagram.id]: items }))} />}
        {!diagram && <div className="empty-state">{t('catalog.noVerifiedDiagram')}</div>}
        {variantChoice && <CatalogVariantDialog position={variantChoice.position} variants={variantChoice.variants} onSelect={(part) => { setSelectedPart(part); setVariantChoice(null) }} onClose={() => setVariantChoice(null)} />}
        <CatalogPartsTable parts={filteredParts} query={partsQuery} selectedPart={selectedPart} diagramPositions={diagramPositions} onQueryChange={setPartsQuery} onSelect={selectPartFromTable} onShowDiagram={focusPartOnDiagram} />
        {selectedPart && <CatalogPartDetails key={selectedPart.source_record_key} part={selectedPart} onAdd={addSelectedPart} onKit={openKit} onClose={() => setSelectedPart(null)} />}
        <section className="catalog-v2-kits"><div className="toolbar"><div><h3>{t('catalog.kits')}</h3><p className="muted">{t('catalog.kitsHint')}</p></div></div><div>{kits.map((kit) => <button key={kit.id} onClick={() => { setKitPreview(kit); setKitPositions(new Set()) }}><span className="badge batch-complete">{t('catalog.verified')}</span><b>{kit.code}</b><small>{t('catalog.kitContains', { count: kit.components.length })}</small><ChevronRight size={17} /></button>)}</div>{!kits.length && <div className="empty-state">{t('catalog.noKits')}</div>}</section>
        {kitPreview && <CatalogRepairKitPreview kit={kitPreview} positionsVisible={kitPositions.size > 0} onTogglePositions={() => toggleKitPositions(kitPreview)} onClose={() => { setKitPreview(null); setKitPositions(new Set()) }} onConfirm={() => confirmKit(kitPreview)} />}
        {onUnknownPart && hasPermission('requests.create') && <button className="secondary catalog-v2-unknown" onClick={onUnknownPart}>{t('unknownPart.notFound')}</button>}
      </main>
      <CatalogRequestCart key={machineId} machineId={machineId} cartMachineId={cart.machineId} lines={cart.lines} onChange={changeCart} undoAvailable={undoCart !== null} onUndo={() => { if (undoCart) setCart(undoCart); setUndoCart(null); setToast(t('catalog.kitAdditionUndone')) }} />
    </div>}
  </>
}
