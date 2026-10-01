import { useEffect, useState } from 'react'
import { api, ApiError } from '../../api'
import { useI18n } from '../../i18n'
import { builderBase } from './wizardTypes'
import type { Analysis } from './ingestTypes'

export default function AnalysisProgress({ revisionId, refreshKey, onCompleted }: {
  revisionId: number; refreshKey: number; onCompleted: () => Promise<void>
}) {
  const { t } = useI18n()
  const [runs, setRuns] = useState<Analysis[]>([])
  const [error, setError] = useState('')
  const [retrying, setRetrying] = useState(false)
  useEffect(() => {
    let active = true
    const abort = new AbortController()
    let timer: ReturnType<typeof setTimeout>
    async function drive() {
      try {
        const rows = await api<Analysis[]>(`${builderBase}/revisions/${revisionId}/analyses`, { signal: abort.signal })
        if (!active) return
        setError('')
        setRuns(rows)
        const running = rows.find(run => run.status === 'RUNNING')
        if (!running) return
        const next = await api<Analysis>(`${builderBase}/analyses/${running.id}/advance`, { method: 'POST', signal: abort.signal })
        if (!active) return
        setRuns(rows.map(run => run.id === next.id ? next : run))
        if (next.status === 'COMPLETED') await onCompleted()
        timer = setTimeout(() => void drive(), next.processed_pages === running.processed_pages ? 1500 : 150)
      } catch (caught) {
        if (active) {
          setError(t(caught instanceof ApiError && caught.code?.startsWith('catalog_ingest_') ? 'ingest.failed' : 'builder.error.generic'))
          timer = setTimeout(() => void drive(), 5000)
        }
      }
    }
    void drive()
    return () => { active = false; abort.abort(); clearTimeout(timer) }
  }, [revisionId, refreshKey, retrying])
  async function retry(run: Analysis) {
    try {
      await api(`${builderBase}/analyses/${run.id}/retry`, { method: 'POST' })
      setError(''); setRetrying(value => !value)
    } catch { setError(t('ingest.failed')) }
  }
  async function dismiss(run: Analysis) {
    try {
      await api(`${builderBase}/analyses/${run.id}/dismiss`, { method: 'POST' })
      setError(''); setRetrying(value => !value); await onCompleted()
    } catch { setError(t('ingest.failed')) }
  }
  return <section aria-label={t('ingest.analysis')}>
    {error && <p role="alert">{error}</p>}
    {runs.map(run => <article key={run.id}>
      <p role="status">{t(`ingest.run.${run.status}`, { page: run.processed_pages, count: run.page_count })}</p>
      <progress aria-label={t('ingest.analysis')} value={run.processed_pages} max={run.page_count} />
      {run.status === 'COMPLETED' && <p>{t('ingest.summary', { groups: run.counts.GROUP || 0,
        parts: run.counts.PART || 0, hotspots: run.counts.HOTSPOT || 0,
        review: (run.states.NEEDS_REVIEW || 0) + (run.states.PROPOSED || 0), ocr: run.ocr_pages })}</p>}
      {run.status === 'COMPLETED' && run.roles && <p>{t('ingest.pageSummary', {
        schemes: (run.roles.EXPLODED_SCHEME || 0) + (run.roles.BOTH || 0),
        lists: (run.roles.SPARE_PARTS_LIST || 0) + (run.roles.BOTH || 0),
        ambiguous: run.matches?.MULTIPLE_CANDIDATES || 0, missing: run.matches?.NOT_FOUND || 0 })}</p>}
      {run.status === 'FAILED' && <button className="secondary" onClick={() => void retry(run)}>{t('ingest.retry')}</button>}
      {run.status === 'FAILED' && <button className="secondary" onClick={() => void dismiss(run)}>{t('ingest.dismiss')}</button>}
    </article>)}
  </section>
}
