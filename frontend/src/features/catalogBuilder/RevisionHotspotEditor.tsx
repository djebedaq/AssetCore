import { useEffect, useRef, useState, type PointerEvent } from 'react'
import { api, ApiError, createApiObjectUrl } from '../../api'
import { useI18n, type TranslationKey } from '../../i18n'

type Page = { visual_page_id: number; artifact_id: number; artifact_title: string; filename: string;
  sha256: string; page_number: number; hotspot_count: number; verified_hotspot_count: number }
type Coverage = { position: string; part_count: number; part_numbers: string[];
  hotspot_count: number; verified_hotspot_count: number; state: 'NO_HOTSPOT' | 'UNVERIFIED' | 'VERIFIED' }
type Geometry = { x: number; y: number; width: number; height: number }
type Hotspot = Geometry & { id: number; visual_page_id: number; position: string; version: number;
  is_verified: boolean; provenance: string }
type Draft = Geometry & { id: number | null; position: string; version: number }
type Gesture = { kind: 'draw' | 'move' | 'resize'; pointerId: number; startX: number; startY: number;
  base: Draft }

const minimum = 0.002
const clamp = (value: number, min: number, max: number) => Math.max(min, Math.min(max, value))
const errorKeys: Record<string, TranslationKey> = {
  catalog_exploded_page_not_found: 'builder.mapping.error.page',
  catalog_hotspot_position_invalid: 'builder.mapping.error.position',
  catalog_hotspot_geometry_invalid: 'builder.mapping.error.geometry',
  catalog_hotspot_stale: 'builder.mapping.error.stale',
  catalog_revision_not_draft: 'builder.error.revisionImmutable',
  catalog_inactive: 'builder.error.inactive',
}

export default function RevisionHotspotEditor({ assemblyId, editable, highlightPositions = [] }: {
  assemblyId: number; editable: boolean; highlightPositions?: string[]
}) {
  const { t } = useI18n()
  const [pages, setPages] = useState<Page[]>([])
  const [coverage, setCoverage] = useState<Coverage[]>([])
  const [pageId, setPageId] = useState<number | null>(null)
  const [hotspots, setHotspots] = useState<Hotspot[]>([])
  const [position, setPosition] = useState('')
  const [draft, setDraft] = useState<Draft | null>(null)
  const [mode, setMode] = useState<'select' | 'draw' | 'pan'>('select')
  const [zoom, setZoom] = useState(100)
  const [url, setUrl] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const canvas = useRef<HTMLDivElement>(null)
  const viewport = useRef<HTMLDivElement>(null)
  const gesture = useRef<Gesture | null>(null)
  const panGesture = useRef<{ pointerId: number; startX: number; startY: number;
    scrollLeft: number; scrollTop: number } | null>(null)
  const page = pages.find(item => item.visual_page_id === pageId)
  const chosen = coverage.find(item => item.position === position)
  const current = hotspots.find(item => item.id === draft?.id)
  const dirty = !!draft && (!current || draft.position !== current.position ||
    (['x', 'y', 'width', 'height'] as const).some(key => draft[key] !== current[key]))

  function message(caught: unknown) {
    return t(caught instanceof ApiError && caught.code && errorKeys[caught.code]
      ? errorKeys[caught.code] : 'builder.error.generic')
  }
  async function loadPages() {
    const [pageRows, positionRows] = await Promise.all([
      api<Page[]>(`/admin/catalog-builder/assemblies/${assemblyId}/exploded-pages`),
      api<Coverage[]>(`/admin/catalog-builder/assemblies/${assemblyId}/hotspot-coverage`),
    ])
    setPages(pageRows); setCoverage(positionRows)
    setPageId(current => pageRows.some(item => item.visual_page_id === current) ? current : pageRows[0]?.visual_page_id ?? null)
    setPosition(current => positionRows.some(item => item.position === current) ? current : positionRows[0]?.position ?? '')
  }
  async function loadHotspots(id: number) {
    setHotspots(await api<Hotspot[]>(`/admin/catalog-builder/visual-pages/${id}/hotspots`))
  }
  useEffect(() => { setPageId(null); setDraft(null); void loadPages().catch(caught => setError(message(caught))) }, [assemblyId])
  useEffect(() => {
    setDraft(null); setHotspots([])
    if (pageId) void loadHotspots(pageId).catch(caught => setError(message(caught)))
  }, [pageId])
  useEffect(() => {
    let active = true
    let objectUrl = ''
    setUrl('')
    if (page) void createApiObjectUrl(`/admin/catalog-builder/artifacts/${page.artifact_id}/pages/${page.page_number}/preview`)
      .then(result => { objectUrl = result.url; if (active) setUrl(result.url) })
      .catch(caught => { if (active) setError(message(caught)) })
    return () => { active = false; if (objectUrl) URL.revokeObjectURL(objectUrl) }
  }, [page?.artifact_id, page?.page_number])

  function point(event: PointerEvent) {
    const rect = canvas.current?.getBoundingClientRect()
    if (!rect) return { x: 0, y: 0 }
    return { x: clamp((event.clientX - rect.left) / rect.width, 0, 1),
      y: clamp((event.clientY - rect.top) / rect.height, 0, 1) }
  }
  function begin(event: PointerEvent, kind: Gesture['kind'], base: Draft) {
    if (!editable || mode === 'pan') return
    event.preventDefault(); event.stopPropagation()
    const start = point(event)
    gesture.current = { kind, pointerId: event.pointerId, startX: start.x, startY: start.y, base }
    canvas.current?.setPointerCapture(event.pointerId)
    setDraft(base)
  }
  function beginDraw(event: PointerEvent<HTMLDivElement>) {
    if (mode === 'pan' && event.pointerType === 'mouse' && event.button === 0 && viewport.current) {
      panGesture.current = { pointerId: event.pointerId, startX: event.clientX, startY: event.clientY,
        scrollLeft: viewport.current.scrollLeft, scrollTop: viewport.current.scrollTop }
      canvas.current?.setPointerCapture(event.pointerId)
      event.preventDefault()
      return
    }
    if (!editable || mode !== 'draw' || !position || event.target !== event.currentTarget && event.target !== canvas.current?.querySelector('img')) return
    const start = point(event)
    begin(event, 'draw', { id: null, position, version: 0, x: start.x, y: start.y, width: 0, height: 0 })
  }
  function move(event: PointerEvent<HTMLDivElement>) {
    const pan = panGesture.current
    if (pan?.pointerId === event.pointerId && viewport.current) {
      viewport.current.scrollLeft = pan.scrollLeft - (event.clientX - pan.startX)
      viewport.current.scrollTop = pan.scrollTop - (event.clientY - pan.startY)
      return
    }
    const active = gesture.current
    if (!active || active.pointerId !== event.pointerId) return
    const now = point(event)
    const dx = now.x - active.startX; const dy = now.y - active.startY
    if (active.kind === 'draw') {
      setDraft({ ...active.base, x: Math.min(now.x, active.startX), y: Math.min(now.y, active.startY),
        width: Math.abs(dx), height: Math.abs(dy) })
    } else if (active.kind === 'move') {
      setDraft({ ...active.base, x: clamp(active.base.x + dx, 0, 1 - active.base.width),
        y: clamp(active.base.y + dy, 0, 1 - active.base.height) })
    } else {
      setDraft({ ...active.base, width: clamp(active.base.width + dx, minimum, 1 - active.base.x),
        height: clamp(active.base.height + dy, minimum, 1 - active.base.y) })
    }
  }
  function finish(event: PointerEvent<HTMLDivElement>) {
    if (panGesture.current?.pointerId === event.pointerId) {
      panGesture.current = null
      if (canvas.current?.hasPointerCapture(event.pointerId)) canvas.current.releasePointerCapture(event.pointerId)
      return
    }
    if (gesture.current?.pointerId !== event.pointerId) return
    if (canvas.current?.hasPointerCapture(event.pointerId)) canvas.current.releasePointerCapture(event.pointerId)
    gesture.current = null
  }
  function select(item: Hotspot, event: PointerEvent<HTMLElement>, kind: 'move' | 'resize') {
    const next = { id: item.id, position: item.position, version: item.version,
      x: item.x, y: item.y, width: item.width, height: item.height }
    setPosition(item.position)
    if (editable && mode === 'select') begin(event, kind, next)
    else { event.stopPropagation(); setDraft(next) }
  }
  async function refresh() {
    if (pageId) await loadHotspots(pageId)
    await loadPages()
  }
  async function save() {
    if (!draft || !pageId || busy || !editable) return
    setBusy(true)
    try {
      const payload = { position: draft.position, x: draft.x, y: draft.y,
        width: draft.width, height: draft.height }
      const saved = draft.id === null
        ? await api<Hotspot>(`/admin/catalog-builder/visual-pages/${pageId}/hotspots`,
          { method: 'POST', body: JSON.stringify(payload) })
        : await api<Hotspot>(`/admin/catalog-builder/hotspots/${draft.id}`,
          { method: 'PATCH', body: JSON.stringify({ ...payload, expected_version: draft.version }) })
      await refresh(); setDraft({ id: saved.id, position: saved.position, version: saved.version,
        x: saved.x, y: saved.y, width: saved.width, height: saved.height }); setError('')
    } catch (caught) { setError(message(caught)); setDraft(null); await refresh() } finally { setBusy(false) }
  }
  async function verify(verified: boolean) {
    if (!current || busy || dirty) return
    setBusy(true)
    try {
      const saved = await api<Hotspot>(`/admin/catalog-builder/hotspots/${current.id}/${verified ? 'verify' : 'unverify'}`,
        { method: 'POST', body: JSON.stringify({ expected_version: current.version }) })
      await refresh(); setDraft({ id: saved.id, position: saved.position, version: saved.version,
        x: saved.x, y: saved.y, width: saved.width, height: saved.height }); setError('')
    } catch (caught) { setError(message(caught)); setDraft(null); await refresh() } finally { setBusy(false) }
  }
  async function remove() {
    if (!current || busy || !window.confirm(t('builder.mapping.deleteConfirm'))) return
    setBusy(true)
    try {
      await api(`/admin/catalog-builder/hotspots/${current.id}?expected_version=${current.version}`, { method: 'DELETE' })
      setDraft(null); await refresh(); setError('')
    } catch (caught) { setError(message(caught)); setDraft(null); await refresh() } finally { setBusy(false) }
  }
  const shown = draft ? hotspots.filter(item => item.id !== draft.id) : hotspots
  return <div className="builder-workspace">
    {error && <p className="error" role="alert">{error}</p>}
    {!pages.length && <p>{t('builder.mapping.noPages')}</p>}
    {!!pages.length && <>
      <label>{t('builder.mapping.page')}<select value={pageId ?? ''} onChange={event => setPageId(Number(event.target.value))}>
        {pages.map(item => <option key={item.visual_page_id} value={item.visual_page_id}>{item.artifact_title} · {t('builder.pageNumber', { count: item.page_number })}</option>)}
      </select></label>
      <small>{page?.filename} · {t('builder.mapping.sha', { hash: page?.sha256 || '' })}</small>
      <div className="actions builder-tabs">
        {editable && <><button className={mode === 'select' ? 'primary compact' : 'secondary compact'} onClick={() => setMode('select')}>{t('builder.mapping.select')}</button>
          <button className={mode === 'draw' ? 'primary compact' : 'secondary compact'} onClick={() => setMode('draw')}>{t('builder.mapping.draw')}</button></>}
        <button className={mode === 'pan' ? 'primary compact' : 'secondary compact'} onClick={() => setMode('pan')}>{t('builder.mapping.pan')}</button>
        <button className="secondary compact" onClick={() => setZoom(value => Math.max(100, value - 25))}>{t('builder.mapping.zoomOut')}</button>
        <span>{zoom}%</span>
        <button className="secondary compact" onClick={() => setZoom(value => Math.min(300, value + 25))}>{t('builder.mapping.zoomIn')}</button>
      </div>
      <div className="builder-scheme-layout">
        <div ref={viewport} className="builder-scheme-viewport">
          <div ref={canvas} className={`builder-scheme-canvas mode-${mode}`} style={{ width: `${zoom}%` }}
            onPointerDown={beginDraw} onPointerMove={move} onPointerUp={finish} onPointerCancel={finish}>
            {url ? <img src={url} draggable={false} alt={t('builder.mapping.page')} /> : <div className="builder-scheme-loading">{t('builder.previewPending')}</div>}
            {shown.map(item => <button key={item.id} type="button"
              className={`builder-hotspot ${item.is_verified ? 'verified' : 'unverified'} ${highlightPositions.includes(item.position) ? 'highlight' : ''}`}
              style={{ left: `${item.x * 100}%`, top: `${item.y * 100}%`, width: `${item.width * 100}%`, height: `${item.height * 100}%` }}
              aria-label={t('builder.mapping.hotspotLabel', { position: item.position })}
              onPointerDown={event => select(item, event, 'move')}>
              <span>{item.position}</span>{editable && mode === 'select' && draft?.id === item.id &&
                <span className="builder-hotspot-handle" onPointerDown={event => select(item, event, 'resize')} />}
            </button>)}
            {draft && <button type="button" className="builder-hotspot draft"
              aria-label={t('builder.mapping.hotspotLabel', { position: draft.position })}
              style={{ left: `${draft.x * 100}%`, top: `${draft.y * 100}%`,
                width: `${draft.width * 100}%`, height: `${draft.height * 100}%` }}
              onPointerDown={event => { if (mode === 'select') begin(event, 'move', draft) }}>
              <span>{draft.position}</span>{editable && mode === 'select' &&
                <span className="builder-hotspot-handle" onPointerDown={event => begin(event, 'resize', draft)} />}</button>}
          </div>
        </div>
        <aside className="builder-scheme-details">
          <label>{t('builder.mapping.position')}<select value={position} onChange={event => {
            setPosition(event.target.value); if (draft) setDraft({ ...draft, position: event.target.value })
          }} disabled={!editable || !!highlightPositions.length}>
            {coverage.map(row => <option key={row.position} value={row.position}>{row.position} · {t('builder.mapping.variants', { count: row.part_count })}</option>)}
          </select></label>
          {chosen && <><b>{t('builder.mapping.variants', { count: chosen.part_count })}</b>
            <ul>{chosen.part_numbers.map(number => <li key={number}>{number}</li>)}</ul>
            <p>{t(`builder.mapping.state.${chosen.state}`)}</p></>}
          {draft && editable && <>
            <div className="builder-geometry-fields">{(['x', 'y', 'width', 'height'] as const).map(key =>
              <label key={key}>{t(`builder.mapping.${key}`)}<input type="number" min="0" max="1" step="0.001"
                value={draft[key]} onChange={event => setDraft({ ...draft, [key]: Number(event.target.value) })} /></label>)}</div>
            <div className="actions"><button className="primary compact" disabled={busy || !dirty || draft.width < minimum || draft.height < minimum}
              onClick={() => void save()}>{t('common.save')}</button>
              {current && <><button className="secondary compact" disabled={busy || dirty} onClick={() => void verify(!current.is_verified)}>
                {t(current.is_verified ? 'builder.mapping.unverify' : 'builder.mapping.verify')}</button>
                <button className="secondary compact" disabled={busy} onClick={() => void remove()}>{t('common.remove')}</button></>}</div>
            <p>{current?.is_verified && !dirty ? t('builder.mapping.verified') : t('builder.mapping.unverified')}</p>
          </>}
          {!!highlightPositions.length && <p>{t('builder.mapping.highlighted', { count: highlightPositions.length })}</p>}
        </aside>
      </div>
      <div className="builder-hotspot-list">{hotspots.map(item => <button key={item.id} type="button" className="secondary compact"
        onClick={() => { setDraft({ id: item.id, position: item.position, version: item.version, x: item.x, y: item.y,
          width: item.width, height: item.height }); setPosition(item.position) }}>
        {item.position} · {t(item.is_verified ? 'builder.mapping.verified' : 'builder.mapping.unverified')}
      </button>)}</div>
    </>}
  </div>
}
