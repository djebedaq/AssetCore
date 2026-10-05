import { useEffect, useRef, useState } from 'react'
import { useI18n } from '../../i18n'
import usePagePreview from './usePagePreview'

export default function SourcePageViewer({ artifactId, pageCount, number, onPage }: {
  artifactId: number; pageCount: number; number: number; onPage: (number: number) => void
}) {
  const { t } = useI18n()
  const preview = usePagePreview(artifactId, number)
  const [zoom, setZoom] = useState(100)
  const [fit, setFit] = useState<'width' | 'page' | null>('page')
  const [jump, setJump] = useState(String(number))
  const viewport = useRef<HTMLDivElement>(null)
  const image = useRef<HTMLImageElement>(null)
  const pan = useRef<{ x: number; y: number; left: number; top: number } | null>(null)
  useEffect(() => { viewport.current?.scrollTo?.(0, 0) }, [artifactId, number])
  useEffect(() => { setJump(String(number)) }, [artifactId, number])
  const jumpToPage = () => onPage(Math.max(1, Math.min(pageCount, Number(jump) || number)))
  const resize = () => {
    if (!fit || !image.current || !viewport.current) return
    const view = viewport.current; const img = image.current
    if (!img.naturalWidth || !img.naturalHeight || view.clientWidth <= 24 || view.clientHeight <= 24) return
    const width = fit === 'width' ? view.clientWidth - 24 : Math.min(view.clientWidth - 24, (view.clientHeight - 24) * img.naturalWidth / img.naturalHeight)
    setZoom(Math.max(1, width / Math.max(1, view.clientWidth - 24) * 100))
  }
  useEffect(() => {
    const observer = new ResizeObserver(resize)
    if (viewport.current) observer.observe(viewport.current)
    resize()
    return () => observer.disconnect()
  }, [fit, preview.url])
  function changeZoom(delta: number) { setFit(null); setZoom(value => Math.max(10, Math.min(800, value + delta))) }
  return <div className="source-reader">
    <div className="reader-toolbar" role="toolbar" aria-label={t('workspace.pdfControls')}>
      <button className="secondary" disabled={number <= 1} onClick={() => onPage(number - 1)} aria-label={t('workspace.previousPage')}>‹</button>
      <label>{t('guided.jump')}<input type="number" min={1} max={pageCount} value={jump} onChange={event => setJump(event.target.value)}
        onBlur={jumpToPage} onKeyDown={event => { if (event.key === 'Enter') { event.preventDefault(); jumpToPage() } }} /></label>
      <span>/ {pageCount}</span>
      <button className="secondary" disabled={number >= pageCount} onClick={() => onPage(number + 1)} aria-label={t('workspace.nextPage')}>›</button>
      <button className="secondary" onClick={() => changeZoom(-25)} aria-label={t('builder.mapping.zoomOut')}>−</button>
      <span>{Math.round(zoom)}%</span>
      <button className="secondary" onClick={() => changeZoom(25)} aria-label={t('builder.mapping.zoomIn')}>+</button>
      <button className="secondary" onClick={() => { setFit('page'); resize() }}>{t('workspace.fitPage')}</button>
      <button className="secondary" onClick={() => { setFit('width'); setZoom(100) }}>{t('workspace.fitWidth')}</button>
    </div>
    <div ref={viewport} className="reader-viewport" aria-busy={!preview.url && !preview.error}
      onPointerDown={event => {
        if (event.button !== 0 || !preview.url || !viewport.current) return
        pan.current = { x: event.clientX, y: event.clientY, left: viewport.current.scrollLeft, top: viewport.current.scrollTop }
        event.currentTarget.setPointerCapture(event.pointerId)
      }} onPointerMove={event => {
        if (!pan.current || !viewport.current) return
        viewport.current.scrollLeft = pan.current.left + pan.current.x - event.clientX
        viewport.current.scrollTop = pan.current.top + pan.current.y - event.clientY
      }} onPointerUp={() => { pan.current = null }} onPointerCancel={() => { pan.current = null }}>
      {preview.error ? <div role="alert" className="reader-message"><p>{t('builder.previewError')}</p><button className="secondary" onClick={preview.retry}>{t('wizard.retry')}</button></div>
        : preview.url ? <img ref={image} src={preview.url} draggable={false} onLoad={resize} onError={preview.failed}
          style={{ width: `${zoom}%` }} alt={t('guided.physicalPage', { number })} />
          : <p role="status" className="reader-message">{t('builder.previewPending')}</p>}
    </div>
  </div>
}
