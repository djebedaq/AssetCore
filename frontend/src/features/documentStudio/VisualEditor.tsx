import { useCallback, useEffect, useLayoutEffect, useRef, useState, type CSSProperties, type PointerEvent } from 'react'
import { ArrowDown, ArrowUp, Check, Copy, Download, GripVertical, Minus, Plus, Redo2, Save, Trash2, Undo2, X } from 'lucide-react'
import { api, createApiObjectUrl, ApiError } from '../../api'
import { useI18n, type TranslationKey } from '../../i18n'
import { hasPermission, storedUser } from '../../permissions'
import { allBlocks, emptyGrid, insertInCell, relocateToCell, siblings, blockId, change, defaultStyle, duplicateBlock, moveBlock, patchBlock, redo, removeBlock, requiredBlock, tableKeys, undo, type Block, type BlockType, type EditorContent, type History, type Style } from './editorModel'
import { studioError, type BrandImage, type Draft, type Profile } from './shared'
import './editor.css'
import { flowPages, type Slice } from './flowPages'
import { GridInspector, type CellTarget } from './GridInspector'

const types: BlockType[] = ['grid', 'text', 'heading', 'field', 'logo', 'image', 'table', 'dynamic_table', 'line', 'frame', 'signature', 'qr', 'page_number', 'page_break', 'conditional']
type Field = { code: string; group: string }
type Preview = { receipt: string; docx: string; pdf: string; report: { page_count: number; docx_sha256: string; pdf_sha256: string; pages: { png: string }[] } }
const content = (d: Draft): EditorContent => ({ title: d.title, layout: d.layout })
const newHistory = (d: Draft): History => ({ present: content(d), past: [], future: [] })
const labelKey = (key: string) => `editor.${key}` as TranslationKey

function ImageView({ image }: { image?: BrandImage }) {
  const [url, setUrl] = useState('')
  useEffect(() => {
    let live = true, object = ''
    if (image) void createApiObjectUrl(image.download_endpoint).then(value => { object = value.url; if (live) setUrl(object); else URL.revokeObjectURL(object) }).catch(() => { if (live) setUrl('') })
    return () => { live = false; if (object) URL.revokeObjectURL(object) }
  }, [image])
  return url ? <img src={url} alt="" draggable={false} /> : null
}

export function VisualEditor({ draft, documentType, saved, onDirty, close, published }: {
  draft: Draft; documentType: string; saved: (d: Draft) => void; onDirty: (value: boolean) => void; close: () => void; published: () => Promise<void>
}) {
  const { t } = useI18n(), editable = hasPermission('templates.manage')
  const key = `assetcore-studio-${storedUser()?.id}-${draft.id}`
  const [base, setBase] = useState(draft), [history, setHistory] = useState(() => newHistory(draft))
  const [cellTarget, setCellTarget] = useState<CellTarget | null>(null), [paletteOpen, setPaletteOpen] = useState(true), [inspectorOpen, setInspectorOpen] = useState(true)
  const [selected, setSelected] = useState<string | null>(null), [drag, setDrag] = useState<string | null>(null), [drop, setDrop] = useState<string | null>(null)
  const [fields, setFields] = useState<Field[]>([]), [images, setImages] = useState<BrandImage[]>([]), [allowed, setAllowed] = useState<number[]>([])
  const [error, setError] = useState<TranslationKey | null>(null), [busy, setBusy] = useState(false), [conflict, setConflict] = useState(false), [autosave, setAutosave] = useState(true)
  const [zoom, setZoom] = useState(.65), [panel, setPanel] = useState<'canvas' | 'blocks' | 'inspector'>('canvas')
  const measure = useRef<HTMLDivElement>(null), [pages, setPages] = useState<Slice[][]>([])
  const [fieldSearch, setFieldSearch] = useState(''), [picker, setPicker] = useState(false), [region, setRegion] = useState<'body' | 'header' | 'footer'>('body')
  const [preview, setPreview] = useState<Preview | null>(null), [showPdf, setShowPdf] = useState(false), [page, setPage] = useState(0), [rows, setRows] = useState<1 | 5 | 30>(5)
  const [note, setNote] = useState(''), [recovery, setRecovery] = useState<{ revision: number; content: EditorContent } | null>(() => {
    if (!editable) return null
    try {
      const raw = sessionStorage.getItem(key), value = raw ? JSON.parse(raw) : null
      return value && Number.isInteger(value.revision) && typeof value.content?.title === 'string' && Array.isArray(value.content?.layout?.blocks) && value.content?.layout?.page ? value : null
    } catch { return null }
  }), [status, setStatus] = useState<TranslationKey>('studio.DRAFT')
  const { title, layout } = history.present, current = allBlocks(layout.blocks).find(b => b.id === selected)
  useEffect(() => {
    if (typeof matchMedia === 'undefined') return
    const media = matchMedia('(max-width: 650px)')
    const readable = () => setZoom(media.matches ? 1 : .65)
    readable(); media.addEventListener('change', readable)
    return () => media.removeEventListener('change', readable)
  }, [])
  useLayoutEffect(() => {
    const node = measure.current
    if (!node) return
    const update = () => {
      const heights: Record<string, number> = {}
      for (const block of node.querySelectorAll<HTMLElement>(':scope > [data-block-id]')) heights[block.dataset.blockId!] = block.getBoundingClientRect().height + parseFloat(getComputedStyle(block).marginBottom || '0')
      setPages(flowPages(layout.blocks.filter(b => (b.region || 'body') === 'body'), heights,
        ((layout.page.orientation === 'portrait' ? 297 : 210) - Math.max(layout.page.margin_mm, (layout.page.header_mm || 0) + 6) - Math.max(layout.page.margin_mm, (layout.page.footer_mm || 0) + 6)) * 96 / 25.4))
    }
    update()
    if (typeof ResizeObserver === 'undefined') return
    const observer = new ResizeObserver(update); observer.observe(node)
    return () => observer.disconnect()
  }, [layout, showPdf])
  useEffect(() => {
    if (!cellTarget) return
    const grid = allBlocks(layout.blocks).find(b => b.id === cellTarget.grid)
    if (!grid?.grid_rows?.[cellTarget.row]?.cells[cellTarget.cell]) setCellTarget(null)
  }, [layout, cellTarget])
  const dirty = JSON.stringify(history.present) !== JSON.stringify(content(base))
  const stateRef = useRef({ base, current: history.present, busy, conflict })
  const failures = useRef(0)
  stateRef.current = { base, current: history.present, busy, conflict }
  useEffect(() => {
    void Promise.all([api<{ fields: Field[] }>('/studio/schema'), api<BrandImage[]>('/studio/images'), api<Profile>('/studio/company')]).then(([schema, list, profile]) => {
      setFields(schema.fields.filter(f => !((f.group === 'repair' && documentType !== 'REPAIR_PROTOCOL') || (f.group === 'request' && documentType !== 'PART_REQUEST') || (f.group === 'transfer' && !documentType.startsWith('TRANSFER_')) || (f.code === 'REMARKS' && documentType === 'REPAIR_PROTOCOL'))))
      setImages(list); setAllowed([...profile.identity.identity_image_ids, profile.identity.primary_logo_id, profile.identity.secondary_logo_id].filter((id): id is number => id !== null))
    }).catch(e => setError(studioError(e)))
  }, [documentType, key])
  useEffect(() => { onDirty(dirty || busy); return () => onDirty(false) }, [dirty, busy, onDirty])
  useEffect(() => {
    if (!editable) return
    try {
      if (dirty) sessionStorage.setItem(key, JSON.stringify({ revision: base.revision, content: history.present }))
      else if (!recovery) sessionStorage.removeItem(key)
    } catch { /* Server saves remain available without browser storage. */ }
  }, [base.revision, dirty, editable, history.present, key, recovery])
  const edit = useCallback((next: EditorContent) => {
    if (!editable || stateRef.current.busy) return
    setHistory(h => change(h, next)); setPreview(null); setStatus('studio.unsaved')
  }, [editable])
  const update = (id: string, patch: Partial<Block>) => edit({ title, layout: patchBlock(layout, id, patch) })
  async function save() {
    const state = stateRef.current
    if (!editable || state.busy || state.conflict) return null
    setBusy(true); setError(null); setStatus('studio.saving')
    try {
      const next = await api<Draft>(`/studio/drafts/${draft.id}`, { method: 'PUT', body: JSON.stringify({ ...state.current, expected_revision: state.base.revision }) })
      setBase(next); setHistory(h => ({ ...h, present: content(next) })); saved(next); setStatus('studio.saved'); setRecovery(null); failures.current = 0
      return next
    } catch (e) {
      setError(studioError(e)); setStatus('studio.unsaved')
      failures.current += 1
      if (e instanceof ApiError && e.status === 409) setConflict(true)
      return null
    } finally { setBusy(false) }
  }
  const saveRef = useRef(save); saveRef.current = save
  useEffect(() => {
    if (!dirty || !editable || !autosave || busy || conflict || recovery) return
    const timer = window.setTimeout(() => void saveRef.current(), Math.min(30000, 1600 * 2 ** Math.min(failures.current, 5)))
    return () => clearTimeout(timer)
  }, [dirty, history.present, editable, autosave, busy, conflict, recovery])
  useEffect(() => {
    const keyboard = (e: KeyboardEvent) => {
      const typing = e.target instanceof Element && !!e.target.closest('input,textarea,select,[contenteditable]')
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 's') { e.preventDefault(); if (editable) void saveRef.current(); return }
      if (!editable || busy || typing) return
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'z') { e.preventDefault(); setHistory(h => e.shiftKey ? redo(h) : undo(h)); setPreview(null) }
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'y') { e.preventDefault(); setHistory(redo); setPreview(null) }
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'd' && selected) { e.preventDefault(); edit({ title, layout: duplicateBlock(layout, selected) }) }
      if ((e.key === 'Delete' || e.key === 'Backspace') && selected) { e.preventDefault(); edit({ title, layout: removeBlock(layout, selected) }) }
      if ((e.ctrlKey || e.metaKey) && e.altKey && selected && ['ArrowUp', 'ArrowDown'].includes(e.key)) {
        e.preventDefault(); const items = siblings(layout, selected), index = items.findIndex(b => b.id === selected), other = items[index + (e.key === 'ArrowUp' ? -1 : 1)]
        if (other) edit({ title, layout: moveBlock(layout, selected, other.id) })
      }
    }
    window.addEventListener('keydown', keyboard); return () => window.removeEventListener('keydown', keyboard)
  }, [editable, busy, selected, edit, layout, title])
  function add(type: BlockType, field?: string) {
    if (type === 'field' && !field) { setPicker(true); setPanel('blocks'); return }
    if (type === 'signature') { setError('studio.requiredBlock'); return }
    if ((type === 'image' || type === 'logo') && !allowed.length) { setError('editor.error.studio_image_not_allowed'); return }
    const block: Block = { id: blockId(), type, region, style: { ...defaultStyle } }
    if (['text', 'heading', 'conditional'].includes(type)) block.text = t(labelKey(type))
    if (type === 'grid') Object.assign(block, emptyGrid())
    if (type === 'heading') block.style = { ...block.style, size_pt: 16, bold: true }
    if (type === 'field') block.field = field
    if (type === 'conditional') block.when_field = documentType === 'REPAIR_PROTOCOL' ? 'DIAGNOSIS' : 'REMARKS'
    if (type === 'table') { block.rows = [[t('editor.description'), t('editor.quantity')], ['', '']]; block.widths = [70, 30]; block.repeat_header = true; block.style = { ...block.style, border_pt: .5 } }
    if (type === 'dynamic_table') {
      block.style = { ...block.style, border_pt: .5 }
      block.source = documentType.startsWith('TRANSFER_') ? 'EQUIPMENT_CHECKLIST' : documentType === 'PART_REQUEST' ? 'REQUEST_LINES' : 'PARTS_USED'; block.repeat_header = true; block.flow = true
      block.columns = (block.source === 'EQUIPMENT_CHECKLIST' ? ['component', 'condition'] : ['description', 'quantity']).map(key => ({ key, label: t(labelKey(`column.${key}`)), width_percent: 50 }))
    }
    if (['image', 'logo', 'frame', 'qr', 'line'].includes(type)) { block.width_mm = type === 'qr' ? 20 : 40; block.height_mm = 20 }
    if (type === 'frame') block.style = { ...block.style, border_pt: .5 }
    if (type === 'image' || type === 'logo') block.image_id = allowed[0]
    if (['page_break', 'dynamic_table'].includes(type)) block.region = 'body'
    edit({ title, layout: cellTarget ? insertInCell(layout, cellTarget, block) : { ...layout, schema_version: type === 'grid' ? 3 : layout.schema_version, blocks: [...layout.blocks, block] } }); setSelected(block.id); setPicker(false); setPanel('inspector')
  }
  async function reload() {
    if (dirty && !window.confirm(t('studio.leave'))) return
    setBusy(true)
    try { const next = await api<Draft>(`/studio/drafts/${draft.id}`); setBase(next); saved(next); setHistory(newHistory(next)); setConflict(false); setRecovery(null); setPreview(null); setError(null); setStatus('studio.saved'); sessionStorage.removeItem(key) }
    catch (e) { setError(studioError(e)) } finally { setBusy(false) }
  }
  async function generate() {
    if (dirty || busy || conflict) return
    setBusy(true); setError(null)
    try { const result = await api<Preview>(`/studio/drafts/${draft.id}/preview`, { method: 'POST', body: JSON.stringify({ expected_revision: base.revision, rows }) }); setPreview(result); setPage(0); setShowPdf(true) }
    catch (e) { setError(studioError(e)) } finally { setBusy(false) }
  }
  async function publish() {
    if (!preview || dirty || !note.trim()) return
    setBusy(true); setError(null)
    try {
      const result = await api<{ draft_revision: number }>(`/studio/drafts/${draft.id}/publish`, { method: 'POST', body: JSON.stringify({ expected_revision: base.revision, rows, receipt: preview.receipt, change_note: note }) })
      const next = { ...base, revision: result.draft_revision }; setBase(next); saved(next); setHistory(newHistory(next)); setNote(''); setPreview(null); setShowPdf(false); setStatus('editor.published'); await published()
    } catch (e) { setError(studioError(e)); if (e instanceof ApiError && e.status === 409) setConflict(true) } finally { setBusy(false) }
  }
  function download(kind: 'pdf' | 'docx') {
    if (!preview) return
    const bytes = Uint8Array.from(atob(preview[kind]), c => c.charCodeAt(0)), url = URL.createObjectURL(new Blob([bytes], { type: kind === 'pdf' ? 'application/pdf' : 'application/vnd.openxmlformats-officedocument.wordprocessingml.document' }))
    const a = document.createElement('a'); a.href = url; a.download = `studio-preview.${kind}`; a.click(); window.setTimeout(() => URL.revokeObjectURL(url), 1000)
  }
  function resize(event: PointerEvent<HTMLButtonElement>, block: Block) {
    event.preventDefault(); event.stopPropagation()
    const startX = event.clientX, startY = event.clientY, width = block.width_mm || 40, height = block.height_mm || 20, start = history.present
    const handle = event.currentTarget; handle.setPointerCapture(event.pointerId)
    const move = (e: globalThis.PointerEvent) => {
      const patch = { width_mm: Math.min(180, Math.max(5, Math.round(width + (e.clientX - startX) / (3.78 * zoom)))), height_mm: Math.min(100, Math.max(5, Math.round(height + (e.clientY - startY) / (3.78 * zoom)))) }
      setHistory(h => ({ ...h, present: { ...start, layout: patchBlock(start.layout, block.id, patch) } })); setPreview(null)
    }
    const end = () => { setHistory(h => ({ ...h, past: [...h.past.slice(-49), start], future: [] })); handle.removeEventListener('pointermove', move); handle.removeEventListener('pointerup', end); handle.removeEventListener('pointercancel', end) }
    handle.addEventListener('pointermove', move); handle.addEventListener('pointerup', end); handle.addEventListener('pointercancel', end)
  }
  const style = { ...defaultStyle, ...current?.style }
  const changeStyle = (patch: Partial<Style>) => { if (current) update(current.id, { style: { ...style, ...patch } }) }
  function draw(block: Block) {
    const s = { ...defaultStyle, ...block.style }, selectedBlock = block.id === selected
    const css: CSSProperties = { fontFamily: s.font, fontSize: `${s.size_pt}pt`, color: s.color, textAlign: s.align, fontWeight: s.bold ? 700 : 400, fontStyle: s.italic ? 'italic' : 'normal', background: s.background, border: `${s.border_pt}pt solid ${s.color}`, marginBottom: `${s.spacing_mm}mm`, width: `${s.width_percent}%`, marginLeft: s.align === 'right' ? 'auto' : s.align === 'center' ? 'auto' : 0, marginRight: s.align === 'center' ? 'auto' : undefined }
    const physical: CSSProperties = { width: `${block.width_mm}mm`, height: `${block.height_mm}mm`, marginLeft: s.align === 'right' || s.align === 'center' ? 'auto' : 0, marginRight: s.align === 'center' ? 'auto' : 0 }
    const cell: CSSProperties = { border: `${s.border_pt}pt solid ${s.color}` }
    if (block.type === 'frame' || block.type === 'line') css.width = `${block.width_mm}mm`
    if (block.type === 'frame') css.minHeight = `${block.height_mm}mm`
    if (['grid', 'table', 'dynamic_table', 'line'].includes(block.type)) css.border = 0
    return <div key={block.id} className={`editor-block ${selectedBlock ? 'selected' : ''} ${drop === block.id ? 'drop-target' : ''}`} style={css} tabIndex={0} role="button" aria-label={t(labelKey(block.type))} aria-pressed={selectedBlock} data-block-id={block.id}
      draggable={editable && !busy} onDragStart={e => { e.stopPropagation(); setDrag(block.id); e.dataTransfer.setData('text/plain', block.id); e.dataTransfer.effectAllowed = 'move' }} onDragOver={e => { e.preventDefault(); e.dataTransfer.dropEffect = 'move'; setDrop(block.id) }} onDragEnd={() => { setDrag(null); setDrop(null) }} onDrop={e => { e.stopPropagation(); e.preventDefault(); const source = e.dataTransfer.getData('text/plain') || drag; if (source) edit({ title, layout: moveBlock(layout, source, block.id) }); setDrag(null); setDrop(null) }}
      onClick={e => { e.stopPropagation(); setSelected(block.id); setPanel('inspector') }} onKeyDown={e => { if (e.target !== e.currentTarget) return; if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); setSelected(block.id); setPanel('inspector') } }}>
      <span className="editor-block-tag"><GripVertical size={12} />{t(labelKey(block.type))}{requiredBlock(block) && <Check size={12} />}</span>
      {block.type === 'grid' && <table className="editor-grid"><colgroup>{block.widths?.map((w, i) => <col key={i} style={{ width: `${w}%` }} />)}</colgroup><tbody>{block.grid_rows?.map((row, i) => <tr key={i} style={{ minHeight: `${row.min_height_mm}mm`, height: `${row.min_height_mm}mm` }}>{row.cells.map((c, j) => <td key={j} colSpan={c.colspan} className={cellTarget?.grid === block.id && cellTarget.row === i && cellTarget.cell === j ? 'editor-cell-selected' : ''} style={{ padding: `${c.padding_mm}mm`, verticalAlign: c.vertical_align === 'center' ? 'middle' : c.vertical_align, background: c.style?.background, border: `${c.style?.border_pt || 0}pt solid ${c.style?.color || '#000000'}` }} onClick={e => { e.stopPropagation(); setSelected(block.id); setCellTarget({ grid: block.id, row: i, cell: j }); setPanel('inspector') }}>{c.blocks.map(draw)}<button type="button" className="editor-cell-select" aria-label={t('editor.cell', { row: i + 1, column: j + 1 })} onClick={e => { e.stopPropagation(); setSelected(block.id); setCellTarget({ grid: block.id, row: i, cell: j }); setPanel('inspector') }}>+</button></td>)}</tr>)}</tbody></table>}
      {['text', 'heading', 'conditional'].includes(block.type) && <div className={block.type === 'heading' ? 'editor-heading-text' : ''}>{block.text || '\u00a0'}</div>}
      {block.type === 'field' && <span className="editor-field-token">{'{ '}{t(labelKey(`field.${block.field}`))}{' }'}</span>}
      {block.type === 'signature' && <div className="editor-signature">{t(`studio.field.${block.slot}` as TranslationKey)}<div>________________________</div></div>}
      {(block.type === 'image' || block.type === 'logo') && <div className="editor-image" style={physical}><ImageView image={images.find(i => i.id === block.image_id)} /></div>}
      {block.type === 'table' && <table><tbody>{block.rows?.map((row, i) => <tr key={i}>{row.map((value, j) => <td style={{ ...cell, width: `${block.widths?.[j] || 100 / row.length}%`, fontWeight: i === 0 && block.repeat_header ? 700 : undefined }} key={j}>{value || '\u00a0'}</td>)}</tr>)}</tbody></table>}
      {block.type === 'dynamic_table' && <table><thead><tr>{block.columns?.map(c => <th key={c.key} style={{ ...cell, width: `${c.width_percent}%` }}>{c.label}</th>)}</tr></thead><tbody>{[1, 2, 3].map(n => <tr key={n}>{block.columns?.map(c => <td key={c.key} style={cell}>{t(labelKey(`column.${c.key}`))} · {n}</td>)}</tr>)}</tbody></table>}
      {block.type === 'line' && <hr style={{ width: '100%', margin: 0, border: 0, borderTop: `${Math.max(.5, s.border_pt)}pt solid ${s.color}` }} />}
      {block.type === 'frame' && <div>{block.text}</div>}
      {block.type === 'qr' && <div className="editor-qr" style={{ ...physical, height: `${block.width_mm}mm` }}>QR</div>}
      {block.type === 'page_number' && <span>{t('editor.page')} 1 / {pages.length}</span>}
      {block.type === 'page_break' && <div className="editor-page-break">{t('editor.page_break')}</div>}
      {editable && !busy && selectedBlock && ['image', 'logo', 'frame'].includes(block.type) && <button className="editor-resize" aria-label={t('editor.resize')} onPointerDown={e => resize(e, block)} />}
    </div>
  }
  return <section className="visual-editor editor-focused" aria-label={t('editor.title')}>
    <div className="editor-topbar"><div><strong>{t('editor.title')}</strong><span role="status">{t(busy ? 'studio.saving' : dirty ? 'studio.unsaved' : status)} · {t('studio.revision', { number: base.revision })}</span></div><button className="secondary" disabled={busy} onClick={() => { if (!dirty || window.confirm(t('studio.leave'))) close() }}><X size={16} />{t('studio.close')}</button></div>
    {error && <p role="alert" className="error">{t(error)}</p>}
    {recovery && <div className="studio-notice">{t('editor.recovery')}<button className="secondary" onClick={() => { setHistory(h => change(h, recovery.content)); setConflict(recovery.revision !== base.revision); setRecovery(null); setPreview(null) }}>{t('editor.restore')}</button><button className="secondary" onClick={() => { setRecovery(null); sessionStorage.removeItem(key) }}>{t('editor.discard')}</button></div>}
    <div className="editor-toolbar">
      <button className="editor-sidebar-toggle" aria-pressed={paletteOpen} onClick={() => setPaletteOpen(v => !v)}>{t('editor.blocks')}</button><button className="editor-sidebar-toggle" aria-pressed={inspectorOpen} onClick={() => setInspectorOpen(v => !v)}>{t('editor.inspector')}</button>
      <button title={t('editor.undo')} aria-label={t('editor.undo')} disabled={!editable || busy || !history.past.length} onClick={() => { setHistory(undo); setPreview(null) }}><Undo2 size={18} /></button>
      <button title={t('editor.redo')} aria-label={t('editor.redo')} disabled={!editable || busy || !history.future.length} onClick={() => { setHistory(redo); setPreview(null) }}><Redo2 size={18} /></button>
      <label>{t('editor.zoom')}<select aria-label={t('editor.zoom')} value={zoom} onChange={e => setZoom(Number(e.target.value))}>{[.35, .5, .65, .8, 1, 1.25, 1.5].map(z => <option key={z} value={z}>{Math.round(z * 100)}%</option>)}</select></label>
      <label>{t('studio.orientation')}<select aria-label={t('studio.orientation')} disabled={!editable || busy} value={layout.page.orientation} onChange={e => edit({ title, layout: { ...layout, page: { ...layout.page, orientation: e.target.value as 'portrait' | 'landscape' } } })}><option value="portrait">{t('studio.portrait')}</option><option value="landscape">{t('studio.landscape')}</option></select></label>
      <label>{t('studio.margin')}<input type="number" min={5} max={40} step={.5} value={layout.page.margin_mm} disabled={!editable || busy} onChange={e => edit({ title, layout: { ...layout, page: { ...layout.page, margin_mm: Number(e.target.value) } } })} /></label>
      <label>{t('editor.headerReserve')}<input type="number" min={0} max={40} value={layout.page.header_mm || 0} disabled={!editable || busy} onChange={e => edit({ title, layout: { ...layout, page: { ...layout.page, header_mm: Number(e.target.value) } } })} /></label>
      {editable && <><label className="editor-check"><input type="checkbox" checked={autosave} onChange={e => setAutosave(e.target.checked)} />{t('editor.autosave')}</label><button className="primary" disabled={busy || !dirty || conflict} onClick={() => void save()}><Save size={16} />{t('studio.save')}</button></>}
      <button className="secondary" disabled={busy} onClick={() => void reload()}>{t('studio.reload')}</button>
      <label>{t('editor.rows')}<select aria-label={t('editor.rows')} value={rows} disabled={busy} onChange={e => { setRows(Number(e.target.value) as 1 | 5 | 30); setPreview(null) }}>{[1, 5, 30].map(n => <option key={n} value={n}>{n}</option>)}</select></label>
      <button className="primary" disabled={busy || dirty || conflict} onClick={() => void generate()}>{t('editor.preview')}</button>
    </div>
    {showPdf && preview ? <div className="editor-pdf" aria-label={t('editor.actualPdf')}><div className="editor-toolbar"><button onClick={() => setShowPdf(false)}>{t('editor.back')}</button><button aria-label={t('editor.previousPage')} disabled={!page} onClick={() => setPage(p => p - 1)}>←</button><span>{t('editor.page')} {page + 1} / {preview.report.page_count}</span><button aria-label={t('editor.nextPage')} disabled={page + 1 === preview.report.page_count} onClick={() => setPage(p => p + 1)}>→</button><button onClick={() => download('docx')}><Download size={16} />DOCX</button><button onClick={() => download('pdf')}><Download size={16} />PDF</button></div><p>{t('editor.synthetic')}</p><div className="editor-pdf-scroll"><img alt={t('editor.actualPdf')} src={`data:image/png;base64,${preview.report.pages[page].png}`} style={{ width: `${595 * zoom}px` }} /></div><small>DOCX SHA-256: {preview.report.docx_sha256}<br />PDF SHA-256: {preview.report.pdf_sha256}</small></div> : <>
      <nav className="editor-mobile-tabs" aria-label={t('editor.panels')}>{(['blocks', 'canvas', 'inspector'] as const).map(p => <button aria-pressed={panel === p} key={p} onClick={() => setPanel(p)}>{t(labelKey(p))}</button>)}</nav>
      <div className={`editor-workspace show-${panel} ${paletteOpen ? '' : 'palette-closed'} ${inspectorOpen ? '' : 'inspector-closed'}`}>
        <aside className="editor-palette">{cellTarget && <div className="editor-cell-target"><p>{t('editor.addToCell')}</p><button onClick={() => setCellTarget(null)}>{t('editor.addToPage')}</button></div>}<h4>{t('editor.blocks')}</h4><label>{t('editor.region')}<select aria-label={t('editor.region')} value={region} onChange={e => setRegion(e.target.value as typeof region)}>{(['body', 'header', 'footer'] as const).map(r => <option key={r} value={r}>{t(labelKey(r))}</option>)}</select></label><div className="editor-palette-grid">{types.map(type => <button key={type} disabled={!editable || busy || layout.blocks.length >= 200 || type === 'signature'} onClick={() => add(type)}><Plus size={14} />{t(labelKey(type))}</button>)}</div>
          <button className="secondary" onClick={() => setPicker(p => !p)}>{t('editor.fields')}</button>{picker && <div className="editor-field-picker"><label>{t('editor.findField')}<input value={fieldSearch} onChange={e => setFieldSearch(e.target.value)} /></label>{fields.filter(f => t(labelKey(`field.${f.code}`)).toLowerCase().includes(fieldSearch.toLowerCase())).map(f => <button key={f.code} disabled={!editable || busy || ['DOCUMENT_NUMBER', 'PREPARER_NAME', 'SIGNATURE_STATUS'].includes(f.code)} onClick={() => add('field', f.code)}><span>{t(labelKey(`field.${f.code}`))}</span><small>{t(labelKey(`group.${f.group}`))}</small></button>)}</div>}
        </aside>
        <main className="editor-canvas"><p className="editor-canvas-hint">{t('editor.canvasHint')}</p>
          <div ref={measure} className="editor-measure" aria-hidden="true" inert style={{ width: `${(layout.page.orientation === 'portrait' ? 210 : 297) - 2 * layout.page.margin_mm}mm` }}>{layout.blocks.filter(b => (b.region || 'body') === 'body').map(draw)}</div>
          <div className="editor-paper-stack" style={{ zoom } as CSSProperties}>{pages.map((body, index) => <article className={`editor-paper ${layout.page.orientation}`} key={index} style={{ padding: `${Math.max(layout.page.margin_mm, (layout.page.header_mm || 0) + 6)}mm ${layout.page.margin_mm}mm ${Math.max(layout.page.margin_mm, (layout.page.footer_mm || 0) + 6)}mm`, '--studio-margin': `${layout.page.margin_mm}mm` } as CSSProperties}><div className="editor-region editor-header">{layout.blocks.filter(b => b.region === 'header').map(draw)}</div><div className="editor-body">{body.map((slice, part) => <div className="editor-flow-slice" key={`${slice.block.id}-${part}`} style={{ height: slice.height, overflow: slice.split ? 'hidden' : 'visible' }}><div style={{ transform: `translateY(-${slice.offset}px)` }}>{draw(slice.block)}</div></div>)}</div><div className="editor-region editor-footer">{layout.blocks.filter(b => b.region === 'footer').map(draw)}</div><span className="editor-paper-number">A4 · {index + 1}</span></article>)}</div>
        </main>
        <aside className="editor-inspector"><h4>{t('editor.inspector')}</h4><label>{t('studio.draftTitle')}<input maxLength={255} value={title} disabled={!editable || busy} onChange={e => edit({ title: e.target.value, layout })} /></label>{current ? <fieldset disabled={!editable || busy}>
          <strong>{t(labelKey(current.type))}</strong>
          <div className="editor-block-actions"><button type="button" aria-label={t('editor.up')} onClick={() => { const items = siblings(layout, current.id), i = items.indexOf(current); if (i > 0) edit({ title, layout: moveBlock(layout, current.id, items[i - 1].id) }) }}><ArrowUp size={17} /></button><button type="button" aria-label={t('editor.down')} onClick={() => { const items = siblings(layout, current.id), i = items.indexOf(current); if (i + 1 < items.length) edit({ title, layout: moveBlock(layout, current.id, items[i + 1].id) }) }}><ArrowDown size={17} /></button><button type="button" aria-label={t('editor.duplicate')} disabled={requiredBlock(current)} onClick={() => edit({ title, layout: duplicateBlock(layout, current.id) })}><Copy size={17} /></button><button type="button" aria-label={t('editor.delete')} disabled={requiredBlock(current)} onClick={() => edit({ title, layout: removeBlock(layout, current.id) })}><Trash2 size={17} /></button></div>
          <label>{t('editor.region')}<select aria-label={t('editor.region')} value={current.region || 'body'} disabled={['signature', 'dynamic_table', 'page_break'].includes(current.type) || !layout.blocks.some(b => b.id === current.id)} onChange={e => update(current.id, { region: e.target.value as Block['region'] })}>{(['body', 'header', 'footer'] as const).map(r => <option key={r} value={r}>{t(labelKey(r))}</option>)}</select></label>
          {current.type === 'grid' && <GridInspector nested={!layout.blocks.some(b => b.id === current.id)} block={current} target={cellTarget} select={setCellTarget} update={patch => update(current.id, patch)} />}
          <label>{t('editor.moveToCell')}<select aria-label={t('editor.moveToCell')} value="" onChange={e => { const target = JSON.parse(e.target.value) as CellTarget; edit({ title, layout: relocateToCell(layout, target, current.id) }); setCellTarget(target) }}><option value="">{t('editor.selectCell')}</option>{allBlocks(layout.blocks).filter(b => b.type === 'grid' && !allBlocks([current]).some(c => c.id === b.id)).flatMap((g, index) => g.grid_rows!.flatMap((r, i) => r.cells.map((_, j) => <option key={`${g.id}-${i}-${j}`} value={JSON.stringify({ grid: g.id, row: i, cell: j })}>{g.label || t('editor.containerNumber', { number: index + 1 })} · {t('editor.cell', { row: i + 1, column: j + 1 })}</option>)))}</select></label>
          {current.type === 'signature' && <><label>{t('editor.signatureLabel')}<input maxLength={100} value={current.label || ''} onChange={e => update(current.id, { label: e.target.value })} /></label><label className="editor-check"><input type="checkbox" checked={current.show_identity !== false} onChange={e => update(current.id, { show_identity: e.target.checked })} />{t('editor.showIdentity')}</label><label>{t('editor.minHeight')}<input type="number" min={14} max={40} value={current.min_height_mm || 14} onChange={e => update(current.id, { min_height_mm: Number(e.target.value) })} /></label></>}
          {['text', 'heading', 'conditional', 'frame', 'line'].includes(current.type) && <label>{t('editor.text')}<textarea aria-label={t('editor.text')} maxLength={current.type === 'frame' || current.type === 'line' ? 2000 : 10000} value={current.text || ''} onChange={e => update(current.id, { text: e.target.value })} /></label>}
          {['field', 'conditional'].includes(current.type) && <label>{t('editor.fields')}<select aria-label={t('editor.fields')} disabled={requiredBlock(current)} value={current.type === 'field' ? current.field : current.when_field} onChange={e => update(current.id, current.type === 'field' ? { field: e.target.value } : { when_field: e.target.value })}>{fields.filter(f => !['DOCUMENT_NUMBER', 'PREPARER_NAME', 'SIGNATURE_STATUS'].includes(f.code) || f.code === current.field).map(f => <option key={f.code} value={f.code}>{t(labelKey(`field.${f.code}`))}</option>)}</select></label>}
          {['image', 'logo'].includes(current.type) && <label>{t('editor.image')}<select aria-label={t('editor.image')} value={current.image_id} onChange={e => update(current.id, { image_id: Number(e.target.value) })}>{images.filter(i => allowed.includes(i.id)).map(i => <option key={i.id} value={i.id}>{t(`studio.${i.purpose}`)} · {i.id}</option>)}</select></label>}
          {['image', 'logo', 'frame', 'qr', 'line'].includes(current.type) && <label>{t('editor.width')}<input type="number" min={5} max={180} value={current.width_mm || 40} onChange={e => update(current.id, { width_mm: Number(e.target.value) })} /></label>}
          {['image', 'logo', 'frame'].includes(current.type) && <label>{t('editor.height')}<input type="number" min={5} max={100} value={current.height_mm || 20} onChange={e => update(current.id, { height_mm: Number(e.target.value) })} /></label>}
          {current.type === 'table' && <div className="editor-table-controls"><h5>{t('editor.table')}</h5>{current.rows?.map((row, i) => <div className="editor-cell-row" key={i}>{row.map((value, j) => <input aria-label={t('editor.cell', { row: i + 1, column: j + 1 })} maxLength={2000} key={j} value={value} onChange={e => update(current.id, { rows: current.rows!.map((r, ri) => ri === i ? r.map((v, ci) => ci === j ? e.target.value : v) : r) })} />)}<button aria-label={t('editor.removeRow')} disabled={current.rows!.length <= 1} onClick={() => update(current.id, { rows: current.rows!.filter((_, ri) => ri !== i) })}><Minus size={14} /></button></div>)}<button disabled={current.rows!.length >= 50} onClick={() => update(current.id, { rows: [...current.rows!, current.rows![0].map(() => '')] })}>{t('editor.addRow')}</button><button disabled={current.rows![0].length >= 8} onClick={() => update(current.id, { rows: current.rows!.map(r => [...r, '']), widths: null })}>{t('editor.addColumn')}</button><button disabled={current.rows![0].length <= 1} onClick={() => update(current.id, { rows: current.rows!.map(r => r.slice(0, -1)), widths: null })}>{t('editor.removeColumn')}</button>{current.rows![0].map((_, i) => <label key={i}>{t('editor.columnWidth', { number: i + 1 })}<input type="number" min={5} max={100} value={current.widths?.[i] ?? 100 / current.rows![0].length} onChange={e => { const widths = current.widths ? [...current.widths] : current.rows![0].map(() => 100 / current.rows![0].length); widths[i] = Number(e.target.value); update(current.id, { widths }) }} /></label>)}</div>}
          {current.type === 'dynamic_table' && <div className="editor-table-controls"><label>{t('editor.source')}<select aria-label={t('editor.source')} value={current.source} onChange={e => { const source = e.target.value, keys = source === 'EQUIPMENT_CHECKLIST' ? ['component', 'condition'] : source === 'REPAIR_PARTICIPANTS' ? ['name', 'duration'] : source === 'REPAIR_ATTACHMENTS' ? ['filename', 'description'] : source === 'REPAIR_EVENTS' ? ['date', 'event_type', 'description'] : ['description', 'quantity']; update(current.id, { source, columns: keys.map(key => ({ key, label: t(labelKey(`column.${key}`)), width_percent: 100 / keys.length })) }) }}>{(documentType.startsWith('TRANSFER_') ? ['EQUIPMENT_CHECKLIST'] : documentType === 'PART_REQUEST' ? ['REQUEST_LINES'] : ['PARTS_USED', 'REPAIR_EVENTS', 'REPAIR_PARTICIPANTS', 'REPAIR_ATTACHMENTS']).map(s => <option value={s} key={s}>{t(labelKey(s))}</option>)}</select></label>{current.columns?.map((column, i) => <div className="editor-column" key={i}><label>{t('editor.column')}<select aria-label={t('editor.column')} value={column.key} onChange={e => update(current.id, { columns: current.columns!.map((c, j) => j === i ? { ...c, key: e.target.value } : c) })}>{tableKeys(current.source).filter(k => k === column.key || !current.columns!.some(c => c.key === k)).map(k => <option key={k} value={k}>{t(labelKey(`column.${k}`))}</option>)}</select></label><label>{t('editor.label')}<input maxLength={100} value={column.label} onChange={e => update(current.id, { columns: current.columns!.map((c, j) => j === i ? { ...c, label: e.target.value } : c) })} /></label><label>{t('editor.widthPercent')}<input type="number" min={5} max={100} value={column.width_percent} onChange={e => update(current.id, { columns: current.columns!.map((c, j) => j === i ? { ...c, width_percent: Number(e.target.value) } : c) })} /></label><button disabled={current.columns!.length <= 1} onClick={() => { const cols = current.columns!.filter((_, j) => j !== i); update(current.id, { columns: cols.map(c => ({ ...c, width_percent: 100 / cols.length })) }) }}>{t('editor.removeColumn')}</button></div>)}<button disabled={current.columns!.length >= tableKeys(current.source).length} onClick={() => { const key = tableKeys(current.source).find(key => !current.columns!.some(c => c.key === key))!; const cols = [...current.columns!, { key, label: t(labelKey(`column.${key}`)), width_percent: 1 }]; update(current.id, { columns: cols.map(c => ({ ...c, width_percent: 100 / cols.length })) }) }}>{t('editor.addColumn')}</button></div>}
          {current.type === 'dynamic_table' && <label className="editor-check"><input type="checkbox" checked={!!current.keep_rows_together} onChange={e => update(current.id, { keep_rows_together: e.target.checked })} />{t('editor.keepRowsTogether')}</label>}
          {['table', 'dynamic_table'].includes(current.type) && <label className="editor-check"><input type="checkbox" checked={current.repeat_header !== false} disabled={current.type === 'dynamic_table'} onChange={e => update(current.id, { repeat_header: e.target.checked })} />{t('editor.repeatHeader')}</label>}
          {!['image', 'logo', 'qr', 'page_break'].includes(current.type) && <><label>{t('editor.font')}<select aria-label={t('editor.font')} value={style.font} onChange={e => changeStyle({ font: e.target.value })}>{['Arial', 'Liberation Sans', 'DejaVu Sans'].map(f => <option key={f}>{f}</option>)}</select></label><label>{t('editor.fontSize')}<input type="number" min={6} max={48} value={style.size_pt} onChange={e => changeStyle({ size_pt: Number(e.target.value) })} /></label>
          <div className="editor-checks"><label><input type="checkbox" checked={style.bold} onChange={e => changeStyle({ bold: e.target.checked })} />{t('editor.bold')}</label><label><input type="checkbox" checked={style.italic} onChange={e => changeStyle({ italic: e.target.checked })} />{t('editor.italic')}</label></div></>}
          <label>{t('editor.align')}<select aria-label={t('editor.align')} value={style.align} onChange={e => changeStyle({ align: e.target.value as Style['align'] })}>{(['left', 'center', 'right'] as const).map(a => <option key={a} value={a}>{t(labelKey(a))}</option>)}</select></label>
          <label>{t('editor.color')}<input type="color" value={style.color} onChange={e => changeStyle({ color: e.target.value })} /></label><label>{t('editor.background')}<input type="color" value={style.background} onChange={e => changeStyle({ background: e.target.value })} /></label>
          <label>{t('editor.spacing')}<input type="number" min={0} max={30} step={.5} value={style.spacing_mm} onChange={e => changeStyle({ spacing_mm: Number(e.target.value) })} /></label><label>{t('editor.border')}<input type="number" min={0} max={3} step={.25} value={style.border_pt} onChange={e => changeStyle({ border_pt: Number(e.target.value) })} /></label>{!['frame', 'line'].includes(current.type) && <label>{t('editor.widthPercent')}<input type="number" min={10} max={100} value={style.width_percent} onChange={e => changeStyle({ width_percent: Number(e.target.value) })} /></label>}
        </fieldset> : <p className="muted">{t('editor.selectBlock')}</p>}</aside>
      </div>
    </>}
    {editable && <div className="editor-publish"><label>{t('studio.note')}<textarea maxLength={2000} minLength={3} value={note} disabled={busy} onChange={e => setNote(e.target.value)} /></label><p>{t('editor.publishHint')}</p><button className="primary" disabled={busy || dirty || conflict || !preview || note.trim().length < 3} onClick={() => void publish()}>{t('editor.publish')}</button>{preview && !showPdf && <button className="secondary" onClick={() => setShowPdf(true)}>{t('editor.actualPdf')}</button>}</div>}
  </section>
}
