import { useEffect, useState } from 'react'
import { createApiObjectUrl } from '../../api'
import { useI18n } from '../../i18n'
import { ingestBg } from './ingestTranslations'
import type { Candidate, Location } from './ingestTypes'
import { builderBase } from './wizardTypes'

export default function CandidateSource({ candidate, location, onClose }: {
  candidate: Candidate; location?: Location; onClose: () => void
}) {
  const { t } = useI18n()
  const roleName = (role: string) => {
    const key = `ingest.field.${role}`
    return key in ingestBg ? t(key as keyof typeof ingestBg) : t('ingest.schema.unknown')
  }
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
    {candidate.evidence.tables?.map((table, index) => <section key={index} aria-label={t('ingest.schema.title')}>
      <h4>{t('ingest.schema.title')}</h4>
      <p>{t(table.schema.state === 'RESOLVED' ? 'ingest.schema.resolved' : 'ingest.schema.ambiguous')}</p>
      {table.schema.state === 'NEEDS_REVIEW' && <p role="status">{t('ingest.schema.help')}</p>}
      {table.geometry?.state === 'NEEDS_REVIEW' && <p role="status">{t('ingest.warning.GEOMETRY_AMBIGUOUS')}</p>}
      <div className="builder-parts-table"><table><thead><tr>
        {table.headers.map((header, col) => <th key={col}>{header}<small>{roleName(table.schema.mapping[String(col)] || 'unknown')}</small></th>)}
      </tr></thead><tbody>{table.sample_cells.slice(0, 5).map((cells, row) => <tr key={row}>
        {table.headers.map((_, col) => <td key={col}>{cells[col] || ''}</td>)}
      </tr>)}</tbody></table></div>
      <details><summary>{t('ingest.schema.alternatives')}</summary>
        {table.schema.alternatives.map((alternative, option) => <p key={option}>
          {t('ingest.schema.score', { score: alternative.score })} · {table.headers.map((header, col) => `${header}: ${roleName(alternative.mapping[String(col)] || 'unknown')}`).join(' · ')}
        </p>)}
      </details>
      {table.geometry?.alternatives && table.geometry.alternatives.length > 1 && <details>
        <summary>{t('ingest.geometry.alternatives')}</summary>
        {table.geometry.alternatives.map((alternative, option) => <div key={option}>
          <p>{t('ingest.schema.score', { score: alternative.score })}</p>
          <div className="builder-parts-table"><table><thead><tr>{table.headers.map((header, col) => <th key={col}>{header}</th>)}</tr></thead>
            <tbody>{alternative.sample_cells.slice(0, 5).map((cells, row) => <tr key={row}>{table.headers.map((_, col) => <td key={col}>{cells[col] || ''}</td>)}</tr>)}</tbody>
          </table></div>
        </div>)}
      </details>}
    </section>)}
    <details><summary>{t('ingest.evidence')}</summary><p>SHA-256: {candidate.sha256}</p>
      <pre>{JSON.stringify(candidate.evidence, null, 2)}</pre></details>
  </aside>
}
