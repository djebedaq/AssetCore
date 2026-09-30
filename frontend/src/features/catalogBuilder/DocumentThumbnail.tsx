import { useEffect, useRef, useState } from 'react'
import { createApiObjectUrl } from '../../api'
import { useI18n } from '../../i18n'
import { builderBase } from './wizardTypes'

export default function DocumentThumbnail({ artifactId, pageNumber }: { artifactId: number; pageNumber: number }) {
  const { t } = useI18n()
  const element = useRef<HTMLDivElement>(null)
  const [url, setUrl] = useState('')
  const [error, setError] = useState(false)
  useEffect(() => {
    let active = true
    let objectUrl = ''
    const load = () => {
      void createApiObjectUrl(`${builderBase}/artifacts/${artifactId}/pages/${pageNumber}/preview?thumbnail=true`)
        .then(result => {
          if (!active) { URL.revokeObjectURL(result.url); return }
          objectUrl = result.url; setUrl(result.url)
        }).catch(() => { if (active) setError(true) })
    }
    setUrl(''); setError(false)
    const observer = new IntersectionObserver(entries => {
      if (entries.some(entry => entry.isIntersecting)) { observer.disconnect(); load() }
    }, { rootMargin: '160px' })
    if (element.current) observer.observe(element.current)
    return () => { active = false; observer.disconnect(); if (objectUrl) URL.revokeObjectURL(objectUrl) }
  }, [artifactId, pageNumber])
  return <div ref={element} className="builder-thumbnail">
    {url ? <img src={url} loading="lazy" alt={t('wizard.physicalPage', { number: pageNumber })} /> :
      <span>{t(error ? 'builder.previewError' : 'builder.previewPending')}</span>}
  </div>
}
