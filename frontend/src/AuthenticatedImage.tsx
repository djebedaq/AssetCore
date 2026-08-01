import { useEffect, useState } from 'react'
import { createApiObjectUrl } from './api'

export default function AuthenticatedImage({ src, alt, className }: {
  src: string; alt: string; className?: string
}) {
  const [objectUrl, setObjectUrl] = useState<string | null>(null)

  useEffect(() => {
    let active = true
    let loadedUrl: string | null = null

    void createApiObjectUrl(src).then(({ url }) => {
      loadedUrl = url
      if (active) setObjectUrl(url)
      else URL.revokeObjectURL(url)
    }).catch(() => {
      if (active) setObjectUrl(null)
    })

    return () => {
      active = false
      if (loadedUrl) URL.revokeObjectURL(loadedUrl)
    }
  }, [src])

  return objectUrl
    ? <img className={className} src={objectUrl} alt={alt} />
    : <span className={className} role="img" aria-label={alt} />
}
