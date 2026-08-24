import { useCallback, useEffect, useState } from 'react'

import { api } from '../../api'
import { useI18n } from '../../i18n'
import { PART_REQUESTS_CHANGED_EVENT } from './partRequestEvents'

type Props = {
  canApprove: boolean
  revalidationKey: string
}

type PendingActionCount = { pending_action_count: number }

export function PendingPartsBadge({ canApprove, revalidationKey }: Props) {
  const { t } = useI18n()
  const [count, setCount] = useState(0)

  const load = useCallback(() => {
    if (!canApprove) {
      setCount(0)
      return
    }
    void api<PendingActionCount>('/part-requests/pending-action-count')
      .then((result) => setCount(result.pending_action_count))
      .catch(() => setCount(0))
  }, [canApprove])

  useEffect(() => {
    load()
  }, [load, revalidationKey])

  useEffect(() => {
    if (!canApprove) return
    const onVisibilityChange = () => {
      if (document.visibilityState === 'visible') load()
    }
    window.addEventListener('focus', load)
    window.addEventListener(PART_REQUESTS_CHANGED_EVENT, load)
    document.addEventListener('visibilitychange', onVisibilityChange)
    return () => {
      window.removeEventListener('focus', load)
      window.removeEventListener(PART_REQUESTS_CHANGED_EVENT, load)
      document.removeEventListener('visibilitychange', onVisibilityChange)
    }
  }, [canApprove, load])

  if (!canApprove || count < 1) return null
  return <span className="nav-action-badge" aria-label={t('parts.pendingActionBadge', { count })}>{count}</span>
}
