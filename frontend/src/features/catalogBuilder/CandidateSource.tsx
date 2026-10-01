import { useEffect, useState } from 'react'
import { createApiObjectUrl } from '../../api'
import { useI18n } from '../../i18n'
import type { Candidate, Location } from './ingestTypes'
import { builderBase } from './wizardTypes'

export default function CandidateSource({ candidate, location, onClose }: {
  candidate: Candidate; location?: Location; onClose: () => void
}) {
  const { t } = useI18n()
  const [url, setUrl] = useState('')
  const [error, setError] = useState(false)
  const number = location?.page_number || candidate.page_number
  const geometry = location || candidate.evidence.geometry
  useEffect(() => {
    let active = true
    let objectUrl = ''
    setUrl(''); setError(false)
    if (number) void createApiObjectUrl(candidate.run_id
      ? `${builderBase}/analyses/${candidate.run_id}/pages/${number}/preview`
      : `${builderBase}/artifacts/${candidate.artifact_id}/pages/${number}/preview`)
      .then(result => {
        if (!active) { URL.revokeObjectURL(result.url); return }
        objectUrl = result.url; setUrl(result.url)
      }).catch(() => { if (active) setError(true) })
    return () => { active = false; if (objectUrl) URL.revokeObjectURL(objectUrl) }
  }, [candidate.artifact_id, number])
  return <aside className="ingest-source" aria-label={t('ingest.source')}>
    <button className="secondary" onClick={onClose}>{t('common.close')}</button>
    <p>{t('wizard.physicalPage', { number: number || '' })}</p>
    {error && <p role="alert">{t('builder.error.generic')}</p>}
    <div className="ingest-source-image">
      {url && <img src={url} alt={t('ingest.source')} />}
      {url && geometry && <span className="ingest-source-bbox" style={{ left: `${geometry.x * 100}%`, top: `${geometry.y * 100}%`,
        width: `${geometry.width * 100}%`, height: `${geometry.height * 100}%` }} />}
    </div>
    <pre>{candidate.evidence.raw_text || candidate.evidence.source_heading}</pre>
    <details><summary>{t('ingest.evidence')}</summary><p>SHA-256: {candidate.sha256}</p>
      <pre>{JSON.stringify(candidate.evidence, null, 2)}</pre></details>
  </aside>
}
