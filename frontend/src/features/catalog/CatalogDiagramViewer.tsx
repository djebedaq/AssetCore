import { useEffect, useMemo, useRef, useState } from 'react'
import { Download, Maximize2, Move, RotateCcw, Save, ScanSearch, ZoomIn, ZoomOut } from 'lucide-react'

import { createApiObjectUrl, downloadApiFile } from '../../api'
import { friendlyError } from '../../industrialUi'
import { useI18n } from '../../i18n'
import { hasPermission } from '../../permissions'
import { catalogApi } from './catalogApi'
import {
  exceedsTapMovementThreshold,
  resolveHotspotActivation,
  type DiagramPointerKind,
} from './catalogInteraction'
import type { CatalogDiagram, CatalogPart, PositionHotspot } from './catalogTypes'

export type DiagramFocus = { position: string; nonce: number } | null

type DragState = {
  id: number
  mode: 'move' | 'resize'
  startX: number
  startY: number
  original: PositionHotspot
}

type PointerTrace = {
  startX: number
  startY: number
  x: number
  y: number
  pointerType: DiagramPointerKind
  hotspot: PositionHotspot | null
  trigger: HTMLButtonElement | null
}

type Props = {
  machineId: number
  diagram: CatalogDiagram
  hotspots: PositionHotspot[]
  selectedPosition: string | null
  focus: DiagramFocus
  kitPositions: Set<string>
  onSelectPosition: (position: string) => void
  onOpenPosition: (
    position: string,
    variants: CatalogPart[],
    trigger: HTMLButtonElement,
  ) => void
  onHotspotsChange: (items: PositionHotspot[]) => void
}

function clamp(value: number, minimum: number, maximum: number) {
  return Math.min(maximum, Math.max(minimum, value))
}

export function CatalogDiagramViewer({
  machineId,
  diagram,
  hotspots,
  selectedPosition,
  focus,
  kitPositions,
  onSelectPosition,
  onOpenPosition,
  onHotspotsChange,
}: Props) {
  const { t } = useI18n()
  const [url, setUrl] = useState('')
  const [zoom, setZoom] = useState(100)
  const [error, setError] = useState('')
  const [qaMode, setQaMode] = useState(false)
  const [qaHotspots, setQaHotspots] = useState<PositionHotspot[]>(hotspots)
  const [editingId, setEditingId] = useState<number | null>(null)
  const [reason, setReason] = useState('')
  const [saving, setSaving] = useState(false)
  const [drag, setDrag] = useState<DragState | null>(null)
  const pointers = useRef(new Map<number, PointerTrace>())
  const panStart = useRef<{ x: number; y: number; left: number; top: number } | null>(null)
  const gesture = useRef({ moved: false, pinched: false })
  const pinchDistance = useRef<number | null>(null)
  const viewport = useRef<HTMLDivElement>(null)
  const canvas = useRef<HTMLDivElement>(null)
  const canManage = hasPermission('parts.manage')
  const visibleHotspots = qaMode ? qaHotspots : hotspots

  useEffect(() => setQaHotspots(hotspots), [hotspots])

  useEffect(() => {
    let active = true
    let objectUrl = ''
    setUrl('')
    setError('')
    void createApiObjectUrl(diagram.preview_endpoint)
      .then((preview) => {
        objectUrl = preview.url
        if (active) setUrl(preview.url)
      })
      .catch((caught) => {
        if (active) setError(friendlyError(caught, t('catalog.documentPreviewError')))
      })
    return () => {
      active = false
      if (objectUrl) URL.revokeObjectURL(objectUrl)
    }
  }, [diagram.id, diagram.preview_endpoint, t])

  useEffect(() => {
    if (!qaMode) return
    let active = true
    void catalogApi.hotspots(machineId, diagram.id, false)
      .then((items) => {
        if (active) setQaHotspots(items)
      })
      .catch((caught) => {
        if (active) setError(friendlyError(caught, t('catalog.qaLoadError')))
      })
    return () => { active = false }
  }, [diagram.id, machineId, qaMode, t])

  useEffect(() => {
    if (!focus || !viewport.current || !canvas.current) return
    const hotspot = visibleHotspots.find((item) => item.position === focus.position)
    if (!hotspot) return
    setZoom((current) => Math.max(current, 140))
    const frame = window.requestAnimationFrame(() => {
      const view = viewport.current
      const sheet = canvas.current
      if (!view || !sheet) return
      const left = (hotspot.x + hotspot.width / 2) * sheet.scrollWidth - view.clientWidth / 2
      const top = (hotspot.y + hotspot.height / 2) * sheet.scrollHeight - view.clientHeight / 2
      if (typeof view.scrollTo === 'function') view.scrollTo({ left, top, behavior: 'smooth' })
      else { view.scrollLeft = left; view.scrollTop = top }
      ;[...sheet.querySelectorAll<HTMLElement>('[data-position]')]
        .find((element) => element.dataset.position === focus.position)
        ?.focus({ preventScroll: true })
    })
    return () => window.cancelAnimationFrame(frame)
  }, [focus, visibleHotspots])

  const editing = useMemo(
    () => qaHotspots.find((item) => item.id === editingId) || null,
    [editingId, qaHotspots],
  )

  function updateEditing(patch: Partial<PositionHotspot>) {
    if (!editingId) return
    setQaHotspots((current) => current.map((item) => item.id === editingId ? { ...item, ...patch } : item))
  }

  function startHotspotDrag(event: React.PointerEvent, hotspot: PositionHotspot, mode: 'move' | 'resize') {
    if (!qaMode) return
    event.preventDefault()
    event.stopPropagation()
    setEditingId(hotspot.id)
    setDrag({ id: hotspot.id, mode, startX: event.clientX, startY: event.clientY, original: hotspot })
    if (typeof event.currentTarget.setPointerCapture === 'function') {
      event.currentTarget.setPointerCapture(event.pointerId)
    }
  }

  function moveHotspot(event: React.PointerEvent) {
    if (!drag || !canvas.current) return
    const bounds = canvas.current.getBoundingClientRect()
    const deltaX = (event.clientX - drag.startX) / bounds.width
    const deltaY = (event.clientY - drag.startY) / bounds.height
    const original = drag.original
    updateEditing(drag.mode === 'move' ? {
      x: clamp(original.x + deltaX, 0, 1 - original.width),
      y: clamp(original.y + deltaY, 0, 1 - original.height),
    } : {
      width: clamp(original.width + deltaX, 0.004, 1 - original.x),
      height: clamp(original.height + deltaY, 0.004, 1 - original.y),
    })
  }

  async function saveEditing() {
    if (!editing || reason.trim().length < 5) return
    setSaving(true)
    setError('')
    try {
      const result = await catalogApi.updateHotspot(editing.id, {
        x: editing.x,
        y: editing.y,
        width: editing.width,
        height: editing.height,
        is_verified: editing.is_verified,
        reason: reason.trim(),
      })
      const updated = { ...editing, ...result }
      const next = qaHotspots.map((item) => item.id === editing.id ? updated : item)
      setQaHotspots(next)
      onHotspotsChange(next.filter((item) => item.is_verified))
      setReason('')
    } catch (caught) {
      setError(friendlyError(caught, t('catalog.qaSaveError')))
    } finally {
      setSaving(false)
    }
  }

  function pointerDown(event: React.PointerEvent<HTMLDivElement>) {
    if (qaMode) return
    const trigger = (event.target as HTMLElement).closest<HTMLButtonElement>('.catalog-v2-hotspot')
    const hotspotId = trigger?.dataset.hotspotId
    const hotspot = hotspotId
      ? visibleHotspots.find((item) => item.id === Number(hotspotId)) || null
      : null
    if (pointers.current.size === 0) gesture.current = { moved: false, pinched: false }
    pointers.current.set(event.pointerId, {
      startX: event.clientX,
      startY: event.clientY,
      x: event.clientX,
      y: event.clientY,
      pointerType: event.pointerType as DiagramPointerKind,
      hotspot,
      trigger,
    })
    if (typeof event.currentTarget.setPointerCapture === 'function') {
      event.currentTarget.setPointerCapture(event.pointerId)
    }
    if (pointers.current.size === 1 && viewport.current) {
      panStart.current = { x: event.clientX, y: event.clientY, left: viewport.current.scrollLeft, top: viewport.current.scrollTop }
    } else if (pointers.current.size > 1) {
      gesture.current.pinched = true
      panStart.current = null
    }
  }

  function pointerMove(event: React.PointerEvent<HTMLDivElement>) {
    if (drag) {
      moveHotspot(event)
      return
    }
    const trace = pointers.current.get(event.pointerId)
    if (!trace) return
    trace.x = event.clientX
    trace.y = event.clientY
    if (exceedsTapMovementThreshold(trace.startX, trace.startY, trace.x, trace.y)) {
      gesture.current.moved = true
    }
    const values = [...pointers.current.values()]
    if (values.length === 2) {
      gesture.current.pinched = true
      const distance = Math.hypot(values[0].x - values[1].x, values[0].y - values[1].y)
      if (pinchDistance.current) {
        const ratio = distance / pinchDistance.current
        setZoom((current) => clamp(Math.round(current * ratio), 75, 300))
      }
      pinchDistance.current = distance
    } else if (values.length === 1 && gesture.current.moved && panStart.current && viewport.current) {
      viewport.current.scrollLeft = panStart.current.left - (event.clientX - panStart.current.x)
      viewport.current.scrollTop = panStart.current.top - (event.clientY - panStart.current.y)
    }
  }

  function pointerUp(event: React.PointerEvent<HTMLDivElement>, cancelled = false) {
    const trace = pointers.current.get(event.pointerId)
    const isFinalPointer = pointers.current.size === 1
    pointers.current.delete(event.pointerId)
    if (pointers.current.size < 2) pinchDistance.current = null
    if (!pointers.current.size) panStart.current = null
    setDrag(null)
    if (!trace?.hotspot || !trace.trigger || !isFinalPointer) return
    const activation = resolveHotspotActivation({
      pointerType: trace.pointerType,
      selectedPosition,
      targetPosition: trace.hotspot.position,
      moved: gesture.current.moved,
      pinched: gesture.current.pinched,
      cancelled,
    })
    if (activation === 'ignore') return
    trace.trigger.focus({ preventScroll: true })
    if (activation === 'select') onSelectPosition(trace.hotspot.position)
    else onOpenPosition(trace.hotspot.position, trace.hotspot.variants, trace.trigger)
  }

  return <section className={`catalog-v2-diagram-panel ${qaMode ? 'qa-mode' : ''}`}>
    <div className="catalog-v2-diagram-toolbar">
      <span><b>{diagram.title}</b><small>{t('common.page')} {diagram.page_number}</small></span>
      <div>
        <button className="secondary compact" aria-label={t('catalog.zoomOut')} disabled={zoom <= 75} onClick={() => setZoom((value) => Math.max(75, value - 25))}><ZoomOut size={17} /></button>
        <b>{zoom}%</b>
        <button className="secondary compact" aria-label={t('catalog.zoomIn')} disabled={zoom >= 300} onClick={() => setZoom((value) => Math.min(300, value + 25))}><ZoomIn size={17} /></button>
        <button className="secondary compact" onClick={() => setZoom(100)}><RotateCcw size={16} />{t('catalog.fitDiagram')}</button>
        <button className="secondary compact" onClick={() => void viewport.current?.requestFullscreen()}><Maximize2 size={16} />{t('catalog.fullscreen')}</button>
        {canManage && <button className={`secondary compact ${qaMode ? 'active' : ''}`} aria-pressed={qaMode} onClick={() => { setQaMode((value) => !value); setEditingId(null) }}><ScanSearch size={16} />{t('catalog.qaMode')}</button>}
      </div>
    </div>
    {error && <div className="error">{error}</div>}
    <div
      className="catalog-v2-diagram-viewport"
      ref={viewport}
      onPointerDown={pointerDown}
      onPointerMove={pointerMove}
      onPointerUp={pointerUp}
      onPointerCancel={(event) => pointerUp(event, true)}
    >
      <div className="catalog-v2-diagram-canvas" ref={canvas} style={{ width: `${zoom}%` }}>
        {!url && !error && <div className="diagram-loading">{t('common.loading')}</div>}
        {url && <img src={url} alt={diagram.title} draggable={false} />}
        {visibleHotspots.map((hotspot) => {
          const variants = hotspot.variants
          const description = variants[0]?.description || t('common.noValue')
          return <button
            key={hotspot.id}
            type="button"
            data-position={hotspot.position}
            data-hotspot-id={hotspot.id}
            className={[
              'catalog-v2-hotspot',
              selectedPosition === hotspot.position ? 'selected' : '',
              kitPositions.has(hotspot.position) ? 'kit-position' : '',
              !hotspot.is_verified ? 'unverified' : '',
              editingId === hotspot.id ? 'editing' : '',
            ].filter(Boolean).join(' ')}
            style={{ left: `${hotspot.x * 100}%`, top: `${hotspot.y * 100}%`, width: `${hotspot.width * 100}%`, height: `${hotspot.height * 100}%` }}
            title={`${t('catalog.position')} ${hotspot.position} · ${description}`}
            aria-label={`${t('catalog.position')} ${hotspot.position}: ${description}`}
            onClick={(event) => {
              if (qaMode) setEditingId(hotspot.id)
              else if (event.detail === 0) onOpenPosition(hotspot.position, variants, event.currentTarget)
            }}
            onPointerDown={(event) => startHotspotDrag(event, hotspot, 'move')}
          >
            <span className="sr-only">{t('catalog.position')} {hotspot.position}</span>
            {qaMode && <span className="catalog-v2-resize-handle" aria-hidden="true" onPointerDown={(event) => startHotspotDrag(event, hotspot, 'resize')} />}
          </button>
        })}
      </div>
    </div>
    {qaMode && editing && <div className="catalog-v2-hotspot-editor" role="region" aria-label={t('catalog.qaEditor')}>
      <b><Move size={16} />{t('catalog.position')} {editing.position}</b>
      <div className="catalog-v2-provenance">
        <span>{t('catalog.qaProvenance')}</span>
        <strong>{t(editing.provenance === 'MANUALLY_CONFIRMED' ? 'catalog.provenanceManuallyConfirmed' : 'catalog.provenanceAutoMatched')}</strong>
      </div>
      {(['x', 'y', 'width', 'height'] as const).map((field) => <label key={field}>{field}<input type="number" min="0" max="1" step="0.001" value={editing[field]} onChange={(event) => updateEditing({ [field]: Number(event.target.value) })} /></label>)}
      <label>{t('catalog.qaVerified')}<input type="checkbox" checked={editing.is_verified} onChange={(event) => updateEditing({ is_verified: event.target.checked })} /></label>
      <label className="reason">{t('catalog.qaReason')}<input value={reason} onChange={(event) => setReason(event.target.value)} /></label>
      <button className="primary compact" disabled={saving || reason.trim().length < 5} onClick={() => void saveEditing()}><Save size={16} />{saving ? t('common.loading') : t('common.save')}</button>
    </div>}
    <div className="catalog-v2-diagram-footer">
      <span>{t('catalog.nonObstructivePositionHint')}<small>{t('catalog.panHint')}</small></span>
      <button className="secondary compact" onClick={() => void downloadApiFile(diagram.download_endpoint, `${diagram.source_id}.pdf`)}><Download size={16} />{t('catalog.openOriginalPdf')}</button>
    </div>
  </section>
}
