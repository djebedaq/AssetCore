import { useEffect, useState } from 'react'
import { createApiObjectUrl } from '../../api'
import { builderBase } from './wizardTypes'

// The backend bounds native PDF workers. Serialize previews rather than making
// a thumbnail grid compete for all worker slots. Only mounted pages request one.
let previewQueue: Promise<unknown> = Promise.resolve()

export default function usePagePreview(artifactId?: number, pageNumber?: number) {
  const [url, setUrl] = useState('')
  const [error, setError] = useState(false)
  const [attempt, setAttempt] = useState(0)
  useEffect(() => {
    let active = true
    let objectUrl = ''
    setUrl(''); setError(false)
    if (artifactId && pageNumber) {
      const request = previewQueue.catch(() => {}).then(async () => {
        if (!active) return
        const result = await createApiObjectUrl(`${builderBase}/artifacts/${artifactId}/pages/${pageNumber}/preview`)
        if (!active || !result.mediaType.startsWith('image/')) {
          URL.revokeObjectURL(result.url)
          if (active) setError(true)
          return
        }
        objectUrl = result.url; setUrl(result.url)
      }).catch(() => { if (active) setError(true) })
      previewQueue = request
    }
    return () => { active = false; if (objectUrl) URL.revokeObjectURL(objectUrl) }
  }, [artifactId, pageNumber, attempt])
  return { url, error, failed: () => setError(true), retry: () => setAttempt(value => value + 1) }
}
