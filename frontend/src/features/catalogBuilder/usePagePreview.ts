import { useEffect, useState } from 'react'
import { ApiError, createApiObjectUrl } from '../../api'
import { builderBase } from './wizardTypes'

// The backend bounds native PDF workers. Serialize previews rather than making
// a thumbnail grid compete for all worker slots. Only mounted pages request one.
let previewQueue: Promise<unknown> = Promise.resolve()

export function requestPdfPreview(path: string, active: () => boolean) {
  const request = previewQueue.catch(() => {}).then(async () => {
    for (let attempt = 0; active(); attempt++) {
      try { return await createApiObjectUrl(path) }
      catch (caught) {
        if (!(caught instanceof ApiError) || caught.code !== 'catalog_extraction_busy' || attempt >= 3) throw caught
        await new Promise(resolve => setTimeout(resolve, 300 * (attempt + 1)))
      }
    }
    return null
  })
  previewQueue = request
  return request
}

export default function usePagePreview(artifactId?: number, pageNumber?: number) {
  const [url, setUrl] = useState('')
  const [error, setError] = useState(false)
  const [attempt, setAttempt] = useState(0)
  useEffect(() => {
    let active = true
    let objectUrl = ''
    setUrl(''); setError(false)
    if (artifactId && pageNumber) {
      void requestPdfPreview(`${builderBase}/artifacts/${artifactId}/pages/${pageNumber}/preview`, () => active).then(result => {
        if (!result) return
        if (!active || !result.mediaType.startsWith('image/')) {
          URL.revokeObjectURL(result.url)
          if (active) setError(true)
          return
        }
        objectUrl = result.url; setUrl(result.url)
      }).catch(() => { if (active) setError(true) })
    }
    return () => { active = false; if (objectUrl) URL.revokeObjectURL(objectUrl) }
  }, [artifactId, pageNumber, attempt])
  return { url, error, failed: () => setError(true), retry: () => setAttempt(value => value + 1) }
}
