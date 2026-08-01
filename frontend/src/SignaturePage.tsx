import { type PointerEvent as ReactPointerEvent, useEffect, useRef, useState } from 'react'
import { CheckCircle2, Eraser, FileSignature, XCircle } from 'lucide-react'
import { api } from './api'
import { useI18n } from './i18n'
import type { SigningSummary } from './types'

type Point = { x: number; y: number; t: number; pressure?: number }

export default function SignaturePage({ token }: { token: string }) {
  const { t } = useI18n()
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const activeStroke = useRef<Point[] | null>(null)
  const [strokes, setStrokes] = useState<Point[][]>([])
  const [summary, setSummary] = useState<SigningSummary | null>(null)
  const [consent, setConsent] = useState(false)
  const [preview, setPreview] = useState('')
  const [step, setStep] = useState<'SIGN' | 'REVIEW' | 'DONE' | 'REJECTED'>('SIGN')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    void api<SigningSummary>(`/signing/${encodeURIComponent(token)}`)
      .then(setSummary)
      .catch(() => setError(t('signature.sessionUnavailable')))
  }, [t, token])

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas || step !== 'SIGN') return
    const resize = () => {
      const rect = canvas.getBoundingClientRect()
      const ratio = Math.min(window.devicePixelRatio || 1, 2)
      canvas.width = Math.max(300, Math.floor(rect.width * ratio))
      canvas.height = Math.max(180, Math.floor(rect.height * ratio))
      redraw(canvas, strokes, ratio)
    }
    resize()
    window.addEventListener('resize', resize)
    return () => window.removeEventListener('resize', resize)
  }, [step, strokes])

  function canvasPoint(event: ReactPointerEvent<HTMLCanvasElement>): Point {
    const canvas = event.currentTarget
    const rect = canvas.getBoundingClientRect()
    return {
      x: Math.max(0, Math.min(rect.width, event.clientX - rect.left)),
      y: Math.max(0, Math.min(rect.height, event.clientY - rect.top)),
      t: performance.now(),
      pressure: event.pressure || undefined,
    }
  }

  function start(event: ReactPointerEvent<HTMLCanvasElement>) {
    event.currentTarget.setPointerCapture(event.pointerId)
    activeStroke.current = [canvasPoint(event)]
  }

  function move(event: ReactPointerEvent<HTMLCanvasElement>) {
    if (!activeStroke.current) return
    const point = canvasPoint(event)
    activeStroke.current.push(point)
    const canvas = event.currentTarget
    const ratio = canvas.width / canvas.getBoundingClientRect().width
    const context = canvas.getContext('2d')
    const previous = activeStroke.current.at(-2)
    if (!context || !previous) return
    context.strokeStyle = '#12263a'
    context.lineWidth = Math.max(2, 2.5 * ratio)
    context.lineCap = 'round'
    context.lineJoin = 'round'
    context.beginPath()
    context.moveTo(previous.x * ratio, previous.y * ratio)
    context.lineTo(point.x * ratio, point.y * ratio)
    context.stroke()
  }

  function finish() {
    const completedStroke = activeStroke.current
    activeStroke.current = null
    if (completedStroke?.length) setStrokes((current) => [...current, completedStroke])
  }

  function clear() {
    setStrokes([])
    const canvas = canvasRef.current
    if (canvas) redraw(canvas, [], canvas.width / canvas.getBoundingClientRect().width)
  }

  async function submit() {
    const canvas = canvasRef.current
    const points = strokes.reduce((total, stroke) => total + stroke.length, 0)
    if (!canvas || points < 8) return setError(t('signature.tooShort'))
    if (!consent || !summary) return setError(t('signature.consentRequired'))
    setBusy(true)
    setError('')
    try {
      await api(`/signing/${encodeURIComponent(token)}`, {
        method: 'POST',
        body: JSON.stringify({
          consent_accepted: true,
          consent_text: summary.consent_notice,
          strokes,
          image_base64: canvas.toDataURL('image/png'),
          canvas_width: Math.round(canvas.getBoundingClientRect().width),
          canvas_height: Math.round(canvas.getBoundingClientRect().height),
        }),
      })
      setPreview(canvas.toDataURL('image/png'))
      setStep('REVIEW')
    } catch {
      setError(t('signature.submitError'))
    } finally {
      setBusy(false)
    }
  }

  async function confirm() {
    setBusy(true)
    setError('')
    try {
      await api(`/signing/${encodeURIComponent(token)}/confirm`, { method: 'POST' })
      setStep('DONE')
    } catch {
      setError(t('signature.confirmError'))
    } finally {
      setBusy(false)
    }
  }

  async function reject() {
    setBusy(true)
    setError('')
    try {
      await api(`/signing/${encodeURIComponent(token)}/reject`, { method: 'POST' })
      setStep('REJECTED')
    } catch {
      setError(t('signature.rejectError'))
    } finally {
      setBusy(false)
    }
  }

  const name = summary?.participant.display_name
  const job = summary?.participant.job_title

  if (step === 'DONE' || step === 'REJECTED') {
    return <main className="signature-page signature-finished">{step === 'DONE' ? <CheckCircle2 size={54} /> : <XCircle size={54} />}<h1>{step === 'DONE' ? t('signature.done') : t('signature.rejected')}</h1><p>{t('signature.closeHint')}</p></main>
  }

  return (
    <main className="signature-page">
      <header className="signature-header"><FileSignature /><div><strong>AssetCore</strong><span>{t('signature.manualGraphic')}</span></div></header>
      {summary && <section className="signature-summary"><h1>{t('signature.title')}</h1><dl><div><dt>{t('signature.document')}</dt><dd>{summary.document_number}</dd></div><div><dt>{t('signature.version')}</dt><dd>{summary.document_version}</dd></div><div><dt>{t('signature.signer')}</dt><dd>{String(name || '')}</dd></div><div><dt>{t('signature.jobTitle')}</dt><dd>{String(job || '')}</dd></div><div><dt>{t('signature.role')}</dt><dd>{summary.operation_role}</dd></div></dl><small>{summary.document_sha256}</small></section>}
      {step === 'SIGN' ? <section className="signature-workspace"><p>{t('signature.drawHint')}</p><canvas ref={canvasRef} className="signature-canvas" aria-label={t('signature.canvas')} onPointerDown={start} onPointerMove={move} onPointerUp={finish} onPointerCancel={finish} /><button className="secondary" type="button" onClick={clear}><Eraser size={17} />{t('signature.clear')}</button><label className="signature-consent"><input type="checkbox" checked={consent} onChange={(event) => setConsent(event.target.checked)} /><span>{summary?.consent_notice || t('signature.consent')}</span></label>{error && <div className="error" role="alert">{error}</div>}<div className="signature-actions"><button className="secondary danger" onClick={reject} disabled={busy}>{t('signature.reject')}</button><button className="primary" onClick={submit} disabled={busy || !summary}>{busy ? t('common.loading') : t('signature.review')}</button></div></section> : <section className="signature-review"><h2>{t('signature.reviewTitle')}</h2><p>{t('signature.reviewHint')}</p>{preview && <img src={preview} alt={t('signature.preview')} />}{error && <div className="error" role="alert">{error}</div>}<div className="signature-actions"><button className="secondary danger" onClick={reject} disabled={busy}>{t('signature.reject')}</button><button className="primary" onClick={confirm} disabled={busy}>{busy ? t('common.loading') : t('signature.confirm')}</button></div></section>}
      <footer>{t('app.copyright')}</footer>
    </main>
  )
}

function redraw(canvas: HTMLCanvasElement, strokes: Point[][], ratio: number) {
  const context = canvas.getContext('2d')
  if (!context) return
  context.fillStyle = '#fff'
  context.fillRect(0, 0, canvas.width, canvas.height)
  context.strokeStyle = '#12263a'
  context.lineWidth = Math.max(2, 2.5 * ratio)
  context.lineCap = 'round'
  context.lineJoin = 'round'
  for (const stroke of strokes) {
    context.beginPath()
    stroke.forEach((point, index) => index ? context.lineTo(point.x * ratio, point.y * ratio) : context.moveTo(point.x * ratio, point.y * ratio))
    context.stroke()
  }
}
