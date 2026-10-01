import { useEffect, useRef, useState, type PointerEvent } from 'react'
import { api, ApiError, createApiObjectUrl } from '../../api'
import { useI18n, type TranslationKey } from '../../i18n'
import useDraftGuard from './useDraftGuard'

type Page = { visual_page_id: number; artifact_id: number; artifact_title: string; filename: string;
  sha256: string; page_number: number; hotspot_count: number; verified_hotspot_count: number }
type Coverage = { position: string; part_count: number; part_numbers: string[];
  names?: Array<{ name_bg: string | null; name_en: string | null; name_ru: string | null; description?: string | null }>;
  hotspot_count: number; verified_hotspot_count: number; state: 'NO_HOTSPOT' | 'UNVERIFIED' | 'VERIFIED' }
type Geometry = { x: number; y: number; width: number; height: number }
type Hotspot = Geometry & { id: number; visual_page_id: number; position: string; version: number;
  is_verified: boolean; provenance: string }
type Draft = Geometry & { id: number | null; position: string; version: number }
type Gesture = { kind: 'point' | 'draw' | 'move' | 'resize'; pointerId: number; startX: number; startY: number;
  base: Draft; latest: Draft; clientX: number; clientY: number; previousDraft: Draft | null }

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

type PositionFilter = 'all' | 'unmarked' | 'unverified' | 'completed'

export default function RevisionHotspotEditor({ assemblyId, editable, highlightPositions = [], simple = false,
  initialFilter = 'all', initialPageId, initialPosition, referencePageId, onChanged, onDirtyChange }: {
  assemblyId: number; referencePageId?: number; onChanged?: () => Promise<void>; editable: boolean; highlightPositions?: string[]; simple?: boolean;
  initialFilter?: PositionFilter; initialPageId?: number; initialPosition?: string; onDirtyChange?: (dirty: boolean) => void
}) {
  const { locale, t } = useI18n()
  const [pages, setPages] = useState<Page[]>([])
  const [coverage, setCoverage] = useState<Coverage[]>([])
  const [pageId, setPageId] = useState<number | null>(null)
  const [hotspots, setHotspots] = useState<Hotspot[]>([])
  const [position, setPosition] = useState('')
  const [draft, setDraft] = useState<Draft | null>(null)
  const [mode, setMode] = useState<'point' | 'select' | 'draw' | 'pan'>(simple ? 'point' : 'select')
  const [autoVerify, setAutoVerify] = useState(true)
  const [pointSize, setPointSize] = useState(3)
  const [filter, setFilter] = useState<PositionFilter>(initialFilter)
  const [search, setSearch] = useState('')
  const [lastPlaced, setLastPlaced] = useState<Hotspot | null>(null)
  const [saveState, setSaveState] = useState<'saved' | 'saving' | 'retry' | null>(null)
  const saving = useRef(false)
  const pageRequest = useRef(0)
  const currentAssembly = useRef(`${assemblyId}/${referencePageId ?? "legacy"}`)
  currentAssembly.current = `${assemblyId}/${referencePageId ?? "legacy"}`
  const [zoom, setZoom] = useState(100)
  const [url, setUrl] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const canvas = useRef<HTMLDivElement>(null)
  const viewport = useRef<HTMLDivElement>(null)
  const gesture = useRef<Gesture | null>(null)
  const touchPointers = useRef(new Set<number>())
  const navigationGesture = useRef(false)
  const panGesture = useRef<{ pointerId: number; startX: number; startY: number;
    scrollLeft: number; scrollTop: number } | null>(null)
  const page = pages.find(item => item.visual_page_id === pageId)
  const chosen = coverage.find(item => item.position === position)
  const current = hotspots.find(item => item.id === draft?.id)
  const dirty = !!draft && (!current || draft.position !== current.position ||
    (['x', 'y', 'width', 'height'] as const).some(key => draft[key] !== current[key]))

  useDraftGuard(dirty || busy, onDirtyChange)
  useEffect(() => { setFilter(initialFilter) }, [initialFilter])
  useEffect(() => { if (initialPageId) setPageId(initialPageId); if (initialPosition) setPosition(initialPosition) }, [initialPageId, initialPosition])

  function message(caught: unknown) {
    return t(caught instanceof ApiError && caught.code && errorKeys[caught.code]
      ? errorKeys[caught.code] : 'builder.error.generic')
  }
  async function loadPages() {
    const [pageRows, positionRows] = await Promise.all([
      api<Page[]>(referencePageId ? `/admin/catalog-builder/reference-pages/${referencePageId}/exploded-pages` : `/admin/catalog-builder/assemblies/${assemblyId}/exploded-pages`),
      api<Coverage[]>(referencePageId ? `/admin/catalog-builder/reference-pages/${referencePageId}/coverage` : `/admin/catalog-builder/assemblies/${assemblyId}/hotspot-coverage`),
    ])
    if (currentAssembly.current !== `${assemblyId}/${referencePageId ?? "legacy"}`) return positionRows
    setPages(pageRows); setCoverage(positionRows)
    setPageId(current => pageRows.some(item => item.visual_page_id === current) ? current : pageRows.find(item => item.visual_page_id === initialPageId)?.visual_page_id ?? pageRows[0]?.visual_page_id ?? null)
    setPosition(current => positionRows.some(item => item.position === current) ? current : initialPosition && positionRows.some(item => item.position === initialPosition) ? initialPosition : positionRows.find(item => item.hotspot_count === 0)?.position ?? positionRows[0]?.position ?? '')
    return positionRows
  }
  async function loadHotspots(id: number) {
    const request = ++pageRequest.current
    const rows = await api<Hotspot[]>(`/admin/catalog-builder/visual-pages/${id}/hotspots`)
    if (request === pageRequest.current) setHotspots(rows)
  }
  useEffect(() => { setPageId(null); setDraft(null); void loadPages().catch(caught => setError(message(caught))) }, [assemblyId, referencePageId])
  useEffect(() => {
    setDraft(null); setHotspots([]); setLastPlaced(null)
    if (pageId) void loadHotspots(pageId).catch(caught => setError(message(caught)))
    return () => {
      pageRequest.current += 1; cancelGesture(); touchPointers.current.clear()
      navigationGesture.current = false; panGesture.current = null
    }
  }, [pageId])
  useEffect(() => {
    let active = true
    let objectUrl = ''
    setUrl('')
    if (page) void createApiObjectUrl(`/admin/catalog-builder/artifacts/${page.artifact_id}/pages/${page.page_number}/preview`)
      .then(result => { if (!active) { URL.revokeObjectURL(result.url); return }; objectUrl = result.url; setUrl(result.url) })
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
    if (!editable || saving.current || busy || !url || mode === 'pan' || navigationGesture.current || event.pointerType !== 'touch' && event.button !== 0) return
    event.preventDefault(); event.stopPropagation()
    const start = point(event)
    gesture.current = { kind, pointerId: event.pointerId, startX: start.x, startY: start.y, base, latest: base, clientX: event.clientX, clientY: event.clientY, previousDraft: draft }
    canvas.current?.setPointerCapture(event.pointerId)
    setDraft(base)
  }
  function cancelGesture() {
    const active = gesture.current
    if (!active) return
    if (canvas.current?.hasPointerCapture(active.pointerId)) canvas.current.releasePointerCapture(active.pointerId)
    gesture.current = null
    setDraft(active.previousDraft)
  }
  function trackPointer(event: PointerEvent<HTMLDivElement>) {
    if (event.pointerType !== 'touch') return
    touchPointers.current.add(event.pointerId)
    if (touchPointers.current.size > 1) {
      navigationGesture.current = true
      cancelGesture()
    }
  }
  function beginDraw(event: PointerEvent<HTMLDivElement>) {
    if (mode === 'pan' && event.pointerType === 'mouse' && event.button === 0 && viewport.current) {
      panGesture.current = { pointerId: event.pointerId, startX: event.clientX, startY: event.clientY,
        scrollLeft: viewport.current.scrollLeft, scrollTop: viewport.current.scrollTop }
      canvas.current?.setPointerCapture(event.pointerId)
      event.preventDefault()
      return
    }
    if (!editable || (mode !== 'draw' && mode !== 'point')) return
    if (!position) { setError(t('guided.noPositions')); return }
    // Overlays own selection gestures; image/background descendants are valid
    // placement targets, including pointer events delivered through wrappers.
    if ((event.target as Element).closest('[data-hotspot-overlay]')) return
    const start = point(event)
    const size = clamp(pointSize / 100, .004, .12)
    begin(event, mode === 'point' ? 'point' : 'draw', { id: null, position, version: 0,
      x: mode === 'point' ? clamp(start.x - size / 2, 0, 1 - size) : start.x,
      y: mode === 'point' ? clamp(start.y - size / 2, 0, 1 - size) : start.y,
      width: mode === 'point' ? size : 0, height: mode === 'point' ? size : 0 })
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
    if (active.kind === 'point') {
      if (Math.hypot(event.clientX - active.clientX, event.clientY - active.clientY) > 8) cancelGesture()
      return
    }
    const next = active.kind === 'draw'
      ? { ...active.base, x: Math.min(now.x, active.startX), y: Math.min(now.y, active.startY), width: Math.abs(dx), height: Math.abs(dy) }
      : active.kind === 'move'
        ? { ...active.base, x: clamp(active.base.x + dx, 0, 1 - active.base.width), y: clamp(active.base.y + dy, 0, 1 - active.base.height) }
        : { ...active.base, width: clamp(active.base.width + dx, minimum, 1 - active.base.x), height: clamp(active.base.height + dy, minimum, 1 - active.base.y) }
    active.latest = next
    setDraft(next)
  }
  function finish(event: PointerEvent<HTMLDivElement>) {
    touchPointers.current.delete(event.pointerId)
    if (!touchPointers.current.size) navigationGesture.current = false
    if (event.type === 'pointercancel') cancelGesture()
    if (panGesture.current?.pointerId === event.pointerId) {
      panGesture.current = null
      if (canvas.current?.hasPointerCapture(event.pointerId)) canvas.current.releasePointerCapture(event.pointerId)
      return
    }
    if (gesture.current?.pointerId !== event.pointerId) return
    if (gesture.current.kind === 'point' &&
        Math.hypot(event.clientX - gesture.current.clientX, event.clientY - gesture.current.clientY) > 8) {
      cancelGesture(); return
    }
    if (canvas.current?.hasPointerCapture(event.pointerId)) canvas.current.releasePointerCapture(event.pointerId)
    const completed = gesture.current
    gesture.current = null
    if (simple) {
      if (completed.latest.width >= minimum && completed.latest.height >= minimum) void save(completed.latest)
      else setDraft(completed.previousDraft)
    }
  }
  function select(item: Hotspot, event: PointerEvent<HTMLElement>, kind: 'move' | 'resize') {
    const next = { id: item.id, position: item.position, version: item.version,
      x: item.x, y: item.y, width: item.width, height: item.height }
    setPosition(item.position)
    if (simple && mode !== 'pan') setMode('select')
    if (editable && mode === 'select') begin(event, kind, next)
    else { event.stopPropagation(); setDraft(next) }
  }
  async function refresh() {
    if (pageId) await loadHotspots(pageId)
    const rows = await loadPages()
    await onChanged?.()
    return rows
  }
  async function save(candidate = draft) {
    if (!candidate || !pageId || saving.current || busy || !editable) return
    saving.current = true; setBusy(true); setSaveState('saving'); setError('')
    let saved: Hotspot | null = null
    try {
      const payload = { position: candidate.position, x: candidate.x, y: candidate.y, width: candidate.width, height: candidate.height }
      saved = candidate.id === null
        ? await api<Hotspot>(`/admin/catalog-builder/visual-pages/${pageId}/hotspots`, { method: 'POST', body: JSON.stringify(payload) })
        : await api<Hotspot>(`/admin/catalog-builder/hotspots/${candidate.id}`, { method: 'PATCH', body: JSON.stringify({ ...payload, expected_version: candidate.version }) })
      // Keep the saved ID before verification so a retry cannot create a duplicate.
      setDraft({ ...saved, id: saved.id })
      if (simple && autoVerify) saved = await api<Hotspot>(`/admin/catalog-builder/hotspots/${saved.id}/verify`, {
        method: 'POST', body: JSON.stringify({ expected_version: saved.version }),
      })
      if (candidate.id === null) setLastPlaced(saved)
      const rows = await refresh()
      setDraft({ ...saved, id: saved.id }); setSaveState('saved')
      if (simple) {
        const index = rows.findIndex(row => row.position === candidate.position)
        const next = [...rows.slice(index + 1), ...rows.slice(0, index + 1)].find(row => row.hotspot_count === 0)
        if (next) { setPosition(next.position); setDraft(null) }
      }
    } catch (caught) {
      setSaveState('retry')
      setError(saved && simple && autoVerify ? t('wizard.verifyFailed') : message(caught))
      if (saved) setDraft({ ...saved, id: saved.id })
      else if (caught instanceof ApiError && caught.code === 'catalog_hotspot_stale') setDraft(null)
      try { await refresh() } catch { /* Keep the original actionable save error. */ }
    } finally { saving.current = false; setBusy(false) }
  }
  async function verify(verified: boolean) {
    if (!current || busy || dirty) return
    setBusy(true)
    try {
      const saved = await api<Hotspot>(`/admin/catalog-builder/hotspots/${current.id}/${verified ? 'verify' : 'unverify'}`,
        { method: 'POST', body: JSON.stringify({ expected_version: current.version }) })
      const rows = await refresh(); setDraft({ id: saved.id, position: saved.position, version: saved.version,
        x: saved.x, y: saved.y, width: saved.width, height: saved.height }); setError('')
      if (simple) {
        setSaveState('saved')
        const index = rows.findIndex(row => row.position === saved.position)
        const next = [...rows.slice(index + 1), ...rows.slice(0, index + 1)].find(row => row.hotspot_count === 0)
        if (verified && next) { setPosition(next.position); setDraft(null) }
      }
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
  function nextPosition(direction: number) {
    if (busy || dirty || !coverage.length) return
    const index = coverage.findIndex(row => row.position === position)
    setPosition(coverage[(index + direction + coverage.length) % coverage.length].position); setDraft(null)
  }
  async function undoPlacement() {
    if (!lastPlaced || busy || dirty) return
    setBusy(true)
    try {
      await api(`/admin/catalog-builder/hotspots/${lastPlaced.id}?expected_version=${lastPlaced.version}`, { method: 'DELETE' })
      setPosition(lastPlaced.position); setDraft(null); setLastPlaced(null); await refresh()
    } catch (caught) { setError(message(caught)) } finally { setBusy(false) }
  }
  const filtered = coverage.filter(row => (filter === 'all' || filter === 'unmarked' && row.hotspot_count === 0 || filter === 'unverified' && row.state === 'UNVERIFIED' || filter === 'completed' && row.state === 'VERIFIED') && [row.position, ...row.part_numbers, ...(row.names || []).flatMap(name => [name.name_bg, name.name_en, name.name_ru, name.description])].some(value => (value || '').toLocaleLowerCase().includes(search.toLocaleLowerCase())))
  const changePage = (id: number) => { if (!dirty || simple || window.confirm(t('wizard.unsaved'))) setPageId(id) }
  const shown = draft ? hotspots.filter(item => item.id !== draft.id) : hotspots
  return <div className="builder-workspace">
    {simple && <p>{t('wizard.hotspotHelp')}</p>}
    {saveState && <p role="status">{t(`wizard.${saveState}`)}</p>}
    {error && <p className="error" role="alert">{error}</p>}
    {!pages.length && <p>{t('builder.mapping.noPages')}</p>}
    {editable && !coverage.length && <p role="status">{t('guided.noPositions')}</p>}
    {!!pages.length && <>
      <label>{t('builder.mapping.page')}<select disabled={busy || simple && dirty} value={pageId ?? ''} onChange={event => changePage(Number(event.target.value))}>
        {pages.map(item => <option key={item.visual_page_id} value={item.visual_page_id}>{item.artifact_title} · {t('builder.pageNumber', { count: item.page_number })}</option>)}
      </select></label>
      {simple && <p>{t('wizard.schemeCount', { number: pages.findIndex(item => item.visual_page_id === pageId) + 1, count: pages.length })}</p>}
      {!simple && <small>{page?.filename} · {t('builder.mapping.sha', { hash: page?.sha256 || '' })}</small>}
      <div className="actions builder-tabs">
        {editable && <>{simple && <button disabled={busy || dirty} className={mode === 'point' ? 'primary compact' : 'secondary compact'} onClick={() => setMode('point')}>{t('wizard.point')}</button>}<button disabled={busy || simple && dirty} className={mode === 'select' ? 'primary compact' : 'secondary compact'} onClick={() => setMode('select')}>{t('builder.mapping.select')}</button>
          <button disabled={busy || simple && dirty} className={mode === 'draw' ? 'primary compact' : 'secondary compact'} onClick={() => setMode('draw')}>{t(simple ? 'wizard.rectangle' : 'builder.mapping.draw')}</button></>}
        <button disabled={busy || simple && dirty} className={mode === 'pan' ? 'primary compact' : 'secondary compact'} onClick={() => setMode('pan')}>{t('builder.mapping.pan')}</button>
        <button className="secondary compact" onClick={() => setZoom(value => Math.max(100, value - 25))}>{t('builder.mapping.zoomOut')}</button>
        <span>{zoom}%</span>
        <button className="secondary compact" onClick={() => setZoom(value => Math.min(300, value + 25))}>{t('builder.mapping.zoomIn')}</button>
      </div>
      {simple && editable && position && <p role="status">{t('guided.clickPosition', { position })}</p>}
      {simple && editable && <div className="actions">
        <button className="secondary" disabled={busy || dirty || !coverage.length} onClick={() => nextPosition(-1)}>{t('wizard.back')}</button>
        <button className="secondary" disabled={busy || dirty || !coverage.length} onClick={() => nextPosition(1)}>{t('guided.skip')}</button>
        <button className="secondary" disabled={busy || dirty || !position} onClick={() => { setMode('point'); setDraft(null) }}>{t('guided.another')}</button>
        <button className="secondary" disabled={busy || dirty || !lastPlaced} onClick={() => void undoPlacement()}>{t('guided.undo')}</button>
      </div>}
      {simple && editable && <div className="actions"><label>{t('wizard.pointSize')}<input type="number" min="0.4" max="12" step="0.5" value={pointSize} disabled={busy} onChange={event => setPointSize(Number(event.target.value))} /></label>
        <label><input type="checkbox" checked={autoVerify} disabled={busy} onChange={event => setAutoVerify(event.target.checked)} />{t('wizard.autoVerify')}</label></div>}
      <div className="builder-scheme-layout">
        <div ref={viewport} className="builder-scheme-viewport">
          <div ref={canvas} className={`builder-scheme-canvas mode-${mode}`} style={{ width: `${zoom}%` }}
            onPointerDownCapture={trackPointer} onPointerDown={beginDraw} onPointerMove={move} onPointerUp={finish} onPointerCancel={finish}>
            {url ? <img src={url} draggable={false} alt={t('builder.mapping.page')} /> : <div className="builder-scheme-loading">{t('builder.previewPending')}</div>}
            {shown.map(item => <button key={item.id} type="button"
              data-hotspot-overlay
              className={`builder-hotspot ${item.is_verified ? 'verified' : 'unverified'} ${highlightPositions.includes(item.position) ? 'highlight' : ''}`}
              style={{ left: `${item.x * 100}%`, top: `${item.y * 100}%`, width: `${item.width * 100}%`, height: `${item.height * 100}%` }}
              aria-label={t('builder.mapping.hotspotLabel', { position: item.position })}
              onPointerDown={event => select(item, event, 'move')}>
              <span>{item.position}</span>{editable && mode === 'select' && draft?.id === item.id &&
                <span className="builder-hotspot-handle" onPointerDown={event => select(item, event, 'resize')} />}
            </button>)}
            {draft && <button type="button" className="builder-hotspot draft"
              data-hotspot-overlay
              aria-label={t('builder.mapping.hotspotLabel', { position: draft.position })}
              style={{ left: `${draft.x * 100}%`, top: `${draft.y * 100}%`,
                width: `${draft.width * 100}%`, height: `${draft.height * 100}%` }}
              onPointerDown={event => { if (mode === 'select') begin(event, 'move', draft) }}>
              <span>{draft.position}</span>{editable && mode === 'select' &&
                <span className="builder-hotspot-handle" onPointerDown={event => begin(event, 'resize', draft)} />}</button>}
          </div>
        </div>
        <aside className="builder-scheme-details">
          {simple && <><input aria-label={t('wizard.positionSearch')} placeholder={t('wizard.positionSearch')} value={search} onChange={event => setSearch(event.target.value)} />
            <label>{t('builder.part.state')}<select value={filter} onChange={event => setFilter(event.target.value as PositionFilter)}>{(['all', 'unmarked', 'unverified', 'completed'] as const).map(value => <option key={value} value={value}>{t(`wizard.${value}`)}</option>)}</select></label>
            {!filtered.length && <p>{t('wizard.noPositions')}</p>}
            <div className="wizard-position-list">{filtered.map(row => <button type="button" key={row.position} disabled={busy || dirty} aria-pressed={position === row.position} className={position === row.position ? 'primary' : 'secondary'} onClick={() => { setPosition(row.position); setDraft(null) }}>
              <b>{t('builder.mapping.hotspotLabel', { position: row.position })}</b><span>{row.part_numbers.join(', ')}</span>
              <span>{(row.names || []).map(name => name[`name_${locale}`] || name.name_bg || name.name_en || name.name_ru || name.description).filter(Boolean).join(', ')}</span>
              <small>{t(`builder.mapping.state.${row.state}`)}</small></button>)}</div></>}
          <label>{t('builder.mapping.position')}<select value={position} onChange={event => {
            setPosition(event.target.value); if (simple) setDraft(null); else if (draft) setDraft({ ...draft, position: event.target.value })
          }} disabled={!editable || busy || simple && dirty || !!highlightPositions.length}>
            {coverage.map(row => <option key={row.position} value={row.position}>{row.position} · {t('builder.mapping.variants', { count: row.part_count })}</option>)}
          </select></label>
          {chosen && <><b>{t('builder.mapping.variants', { count: chosen.part_count })}</b>
            <ul>{chosen.part_numbers.map(number => <li key={number}>{number}</li>)}</ul>
            <p>{t(`builder.mapping.state.${chosen.state}`)}</p></>}
          {draft && editable && <>
            {!simple && <div className="builder-geometry-fields">{(['x', 'y', 'width', 'height'] as const).map(key =>
              <label key={key}>{t(`builder.mapping.${key}`)}<input type="number" min="0" max="1" step="0.001"
                value={draft[key]} onChange={event => setDraft({ ...draft, [key]: Number(event.target.value) })} /></label>)}</div>}
            <div className="actions"><button className="primary compact" disabled={busy || !dirty || draft.width < minimum || draft.height < minimum}
              onClick={() => void save()}>{t(simple ? 'wizard.retry' : 'common.save')}</button>
              {current && <><button className="secondary compact" disabled={busy || dirty} onClick={() => void verify(!current.is_verified)}>
                {t(current.is_verified ? 'builder.mapping.unverify' : 'builder.mapping.verify')}</button>
                <button className="secondary compact" disabled={busy} onClick={() => void remove()}>{t('common.remove')}</button></>}</div>
            <p>{current?.is_verified && !dirty ? t('builder.mapping.verified') : t('builder.mapping.unverified')}</p>
          </>}
          {!!highlightPositions.length && <p>{t('builder.mapping.highlighted', { count: highlightPositions.length })}</p>}
        </aside>
      </div>
      <div className="builder-hotspot-list">{hotspots.map(item => <button key={item.id} type="button" className="secondary compact"
        disabled={busy || simple && dirty} onClick={() => { if (simple) setMode('select'); setDraft({ id: item.id, position: item.position, version: item.version, x: item.x, y: item.y,
          width: item.width, height: item.height }); setPosition(item.position) }}>
        {item.position} · {t(item.is_verified ? 'builder.mapping.verified' : 'builder.mapping.unverified')}
      </button>)}</div>
    </>}
  </div>
}
