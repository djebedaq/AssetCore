import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { BookOpen, CheckCircle2, ChevronRight } from 'lucide-react'

import SharedReferences from './SharedReferences'
import { api } from '../../api'
import { friendlyError } from '../../industrialUi'
import { statusText, useI18n } from '../../i18n'
import type { Machine } from '../../types'
import { CatalogDiagramViewer, type DiagramFocus } from './CatalogDiagramViewer'
import { CatalogPartsTable } from './CatalogPartsTable'
import { CatalogRequestCart } from './CatalogRequestCart'
import { CatalogPartDetails, CatalogRepairKitPreview, CatalogVariantDialog } from './CatalogSelectionPanels'
import { catalogApi } from './catalogApi'
import { catalogDisplayName, catalogSourceDescription } from './catalogNames'
import { addPart, addRepairKit } from './catalogState'
import type { AssemblyDetails, CatalogCartLine, CatalogPart, CatalogRepairKit, MachineCatalog, PositionHotspot } from './catalogTypes'
import { Select } from '../../ui/Select'
import { CategorySelect, MachineSelect, useCategories } from '../../ui/workspace'

type Props = { defaultMachineId?: number }
type MachineCartState = { machineId: number | null; lines: CatalogCartLine[] }
const EMPTY_MACHINE_CART: MachineCartState = { machineId: null, lines: [] }

export function IndustrialCatalog({ defaultMachineId }: Props = {}) {
  const { t, locale } = useI18n()
  const [machines, setMachines] = useState<Machine[]>([])
  const [machineId, setMachineId] = useState<number | ''>(defaultMachineId || '')
  const [categoryId, setCategoryId] = useState('')
  const { categories, error: categoryError } = useCategories('catalog')
  const [pendingCategoryId, setPendingCategoryId] = useState<string | null>(null)
  const currentMachine = useRef(machineId)
  currentMachine.current = machineId
  const previousDefaultMachineId = useRef(defaultMachineId)
  const [pendingMachineId, setPendingMachineId] = useState<number | '' | null>(null)
  const [referenceRefresh, setReferenceRefresh] = useState(0)
  const [context, setContext] = useState<MachineCatalog | null>(null)
  const [sourceId, setSourceId] = useState('')
  const reference = context?.assemblies.find(item => item.source_id === sourceId || item.pages?.some(page => page.source_id === sourceId))
  const logicalPage = reference?.pages?.find(page => page.source_id === sourceId)
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
  const currentCart = useRef(cart)
  currentCart.current = cart
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
    let active = true
    setMachines([])
    if (!machineId) return
    void api<Machine>(`/machines/${machineId}`).then(machine => {
      if (active) { setMachines([machine]); setCategoryId(String(machine.category_id || '')) }
    }).catch(caught => { if (active) setError(friendlyError(caught, t('catalog.loadError'))) })
    return () => { active = false }
  }, [machineId, t])
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
      if (active) { setContext(value); setSourceId(value.assemblies[0]?.pages?.[0]?.source_id || value.assemblies[0]?.source_id || '') }
    }).catch((caught) => { if (active) setError(friendlyError(caught, t('catalog.loadError'))) })
      .finally(() => { if (active) setLoading(false) })
    return () => { active = false }
  }, [machineId, t, referenceRefresh])
  useEffect(() => {
    let active = true
    setDetails(null); setSelectedPart(null); setSelectedPosition(null); setVariantChoice(null); setKitPreview(null)
    setKitPositions(new Set()); setHotspotsByDiagram({})
    if (!machineId || !sourceId || context?.machine_id !== machineId || !context.assemblies.some((assembly) => assembly.source_id === sourceId || assembly.pages?.some(page => page.source_id === sourceId))) return
    setLoading(true)
    void Promise.all([catalogApi.assembly(machineId, sourceId), catalogApi.repairKits(machineId, context.assemblies.find(item => item.source_id === sourceId || item.pages?.some(page => page.source_id === sourceId))?.source_id || sourceId)]).then(async ([assembly, repairKits]) => {
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
    return (details?.parts || []).filter((part) => [part.position, part.part_number, part.replaced_by_part_number, part.alternative_part_number, part.supplier, part.supplier_code, part.assembly, part.description_bg, part.description_en, part.description_ru, catalogDisplayName(part, locale), catalogSourceDescription(part), part.description, part.description_2, part.repair_kit_code, part.valid_for_raw].some((value) => value?.toLocaleLowerCase().includes(query)))
  }, [details, partsQuery, locale])

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
    setCart((current) => ({ machineId, lines: addPart(current.lines, part, locale) })); setUndoCart(null)
    setToast(t('catalog.positionAdded', { position: part.position }))
  }
  function openKit(code: string) {
    setKitPreview(kits.find((kit) => kit.code === code) || null)
    setKitPositions(new Set())
    setSelectedPart(null)
  }
  function toggleKitPositions(kit: CatalogRepairKit) {
    if (kitPositions.size) { setKitPositions(new Set()); return }
    const positions = new Set(kit.components.filter(component => details?.parts.some(part => part.id === component.part_id)).map((component) => component.position))
    setKitPositions(positions)
    const firstPart = details?.parts.find((part) => positions.has(part.position) && diagramPositions.has(part.position))
    if (firstPart) focusPartOnDiagram(firstPart)
  }
  async function confirmKit(kit: CatalogRepairKit) {
    if (!details || !machineId || loading) return
    if (cart.lines.length > 0 && cart.machineId !== machineId) { setError(t('catalog.cartMachineMismatch')); return }
    const selectedMachine = machineId
    const missing = [...new Set(kit.components.filter(component => !details.parts.some(part => part.id === component.part_id)).map(component => component.source_id).filter((id): id is string => !!id))]
    try {
      setLoading(true)
      const extra = await Promise.all(missing.map(id => catalogApi.assembly(selectedMachine, id)))
      if (currentMachine.current !== selectedMachine) return
      const parts = [...details.parts, ...extra.flatMap(item => item.parts)]
      if (kit.components.some(component => !parts.some(part => part.id === component.part_id))) { setError(t('catalog.loadError')); return }
      const latestCart = currentCart.current
      if (latestCart.lines.length && latestCart.machineId !== selectedMachine) return
      setUndoCart(latestCart)
      setCart({ machineId: selectedMachine, lines: addRepairKit(latestCart.lines, kit, parts, locale) })
      setKitPreview(null); setKitPositions(new Set()); setToast(t('catalog.kitAdded', { code: kit.code }))
    } catch { setError(t('catalog.loadError')) } finally { setLoading(false) }
  }
  function changeCart(lines: CatalogCartLine[]) {
    setCart((current) => ({ machineId: lines.length ? current.machineId : null, lines })); if (!lines.length) setUndoCart(null)
  }
  function requestMachineSelection(nextMachineId: number | '') {
    if (nextMachineId === machineId) return
    if (cart.lines.length > 0) setPendingMachineId(nextMachineId); else applyMachineSelection(nextMachineId)
  }
  function requestCategorySelection(nextCategory: string) {
    if (nextCategory === categoryId) return
    if (cart.lines.length) { setPendingCategoryId(nextCategory); setPendingMachineId(''); return }
    applyMachineSelection(''); setCategoryId(nextCategory)
  }

  return <>
    <div className="toolbar"><div><h3>{t('catalog.title')}</h3><p className="muted">{t('ux.catalogHint')}</p></div></div>
    {toast && <div className="success catalog-v2-toast" role="status"><CheckCircle2 size={18} />{toast}<button className="link" onClick={() => setToast('')}>{t('common.close')}</button></div>}
    {error && <div className="error">{error}</div>}
    {categoryError && <div className="error" role="alert">{t('catalog.loadError')}</div>}
    <section className="catalog-v2-machine panel">
      <CategorySelect categories={categories} value={categoryId} onChange={requestCategorySelection} all={false} />
      <MachineSelect module="catalog" label={t('catalog.chooseMachine')} category={categoryId} value={String(machineId)} onChange={value => requestMachineSelection(value ? Number(value) : '')} disabled={!categoryId} />
      {machine && <div><b>№{machine.inventory_number} · {machine.brand}</b><span>{machine.model || t('common.noValue')}</span><small>{machine.pressure_bar != null && <>{t('machines.pressure')}: {machine.pressure_bar} · </>}{t('common.status')}: {statusText(t, machine.status)} · {t('common.location')}: {machine.location?.name || t('common.noValue')}</small></div>}
      {context?.supported && <label>{t('catalog.chooseAssembly')}<Select label={t('catalog.chooseAssembly')} value={reference?.source_id || sourceId} onChange={value => { const item = context.assemblies.find(assembly => assembly.source_id === value); setSourceId(item?.pages?.[0]?.source_id || value) }} options={context.assemblies.map(assembly => ({ value: assembly.source_id, label: `${t(assembly.is_supplemental ? 'ref.additional' : 'ref.primary')} · ${assembly[`name_${locale}`] || assembly.title} · ${assembly.part_count}` }))} /></label>}
    </section>
    {context && <SharedReferences references={context.references || []} onChanged={() => setReferenceRefresh(value => value + 1)} />}
    {pendingMachineId !== null && <div className="catalog-v2-machine-switch panel" role="dialog" aria-modal="true" aria-labelledby="catalog-machine-switch-title"><h3 id="catalog-machine-switch-title">{t('catalog.changeMachineTitle')}</h3><p>{t('catalog.changeMachineWarning')}</p><div className="actions"><button className="secondary" onClick={() => { setPendingMachineId(null); setPendingCategoryId(null) }}>{t('common.cancel')}</button><button className="primary" onClick={() => { applyMachineSelection(pendingMachineId); if (pendingCategoryId !== null) setCategoryId(pendingCategoryId); setPendingCategoryId(null) }}>{t('catalog.changeMachineConfirm')}</button></div></div>}
    {loading && <div className="empty-state">{t('common.loading')}</div>}
    {!machineId && !loading && <div className="empty-state visual-catalog-empty"><BookOpen size={36} /><h3>{t('catalog.chooseMachineTitle')}</h3><p>{t('catalog.chooseMachineExplanation')}</p></div>}
    {context && !context.supported && <div className="empty-state visual-catalog-empty"><BookOpen size={36} /><h3>{context.message}</h3></div>}
    {details && machineId && <div className="catalog-v2-layout">
      <main className="catalog-v2-workspace">
        {!!reference?.pages?.length && <nav className="catalog-v2-diagram-tabs" aria-label={t('guided.pages')}>
          {reference.pages.map(page => <button key={page.id} className={page.source_id === sourceId ? 'active' : ''}
            aria-current={page.source_id === sourceId ? 'page' : undefined} onClick={() => setSourceId(page.source_id)}>{page.title || t('guided.page', { number: page.number })}</button>)}
        </nav>}
        <nav className="catalog-v2-diagram-tabs" aria-label={t('catalog.visualWorkspace')}>{details.diagrams.map((item, index) => <button className={item.id === diagramId ? 'active' : ''} key={item.id} onClick={() => setDiagramId(item.id)}>{logicalPage ? t('guided.schemeNumber', { number: index + 1 }) : `${t('common.page')} ${item.page_number}`}</button>)}</nav>
        {diagram && <CatalogDiagramViewer machineId={machineId} editableQa={details.dataset_version === 'PARTS_CATALOG_V2'} diagram={diagram} hotspots={currentHotspots} selectedPosition={selectedPosition} focus={focus} kitPositions={kitPositions} onSelectPosition={selectDiagramPosition} onOpenPosition={openDiagramPosition} onHotspotsChange={(items) => setHotspotsByDiagram((current) => ({ ...current, [diagram.id]: items }))} />}
        {!diagram && <div className="empty-state">{t('catalog.noVerifiedDiagram')}</div>}
        {variantChoice && <CatalogVariantDialog position={variantChoice.position} variants={variantChoice.variants} onSelect={(part) => { setSelectedPart(part); setVariantChoice(null) }} onClose={() => setVariantChoice(null)} />}
        <CatalogPartsTable parts={filteredParts} query={partsQuery} selectedPart={selectedPart} diagramPositions={diagramPositions} onQueryChange={setPartsQuery} onSelect={selectPartFromTable} onShowDiagram={focusPartOnDiagram} />
        {selectedPart && <CatalogPartDetails key={selectedPart.source_record_key} part={selectedPart} onAdd={addSelectedPart} onKit={openKit} onClose={() => setSelectedPart(null)} />}
        <section className="catalog-v2-kits"><div className="toolbar"><div><h3>{t('catalog.kits')}</h3><p className="muted">{t('catalog.kitsHint')}</p></div></div><div>{kits.map((kit) => <button key={kit.id} onClick={() => { setKitPreview(kit); setKitPositions(new Set()) }}><span className="badge batch-complete">{t('catalog.verified')}</span><b>{kit.code}</b><small>{t('catalog.kitContains', { count: kit.components.length })}</small><ChevronRight size={17} /></button>)}</div>{!kits.length && <div className="empty-state">{t('catalog.noKits')}</div>}</section>
        {kitPreview && <CatalogRepairKitPreview kit={kitPreview} positionsVisible={kitPositions.size > 0} onTogglePositions={() => toggleKitPositions(kitPreview)} onClose={() => { setKitPreview(null); setKitPositions(new Set()) }} onConfirm={() => void confirmKit(kitPreview)} />}
      </main>
      <CatalogRequestCart key={machineId} machineId={machineId} cartMachineId={cart.machineId} lines={cart.lines} onChange={changeCart} undoAvailable={undoCart !== null} onUndo={() => { if (undoCart) setCart(undoCart); setUndoCart(null); setToast(t('catalog.kitAdditionUndone')) }} />
    </div>}
  </>
}
