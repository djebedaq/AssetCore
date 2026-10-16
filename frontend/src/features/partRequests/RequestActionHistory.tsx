import { useEffect, useState } from 'react'
import { api } from '../../api'
import { useI18n, type TranslationKey } from '../../i18n'

type History = { has_next: boolean; items: Array<{ id: number; action_code: string; actor_name?: string | null; occurred_at: string }> }
export function RequestActionHistory({ requestId, status }: { requestId: number; status: string }) {
  const { t, date } = useI18n()
  const [open, setOpen] = useState(false)
  const [offset, setOffset] = useState(0)
  const [data, setData] = useState<History | null>(null)
  const [error, setError] = useState(false)
  useEffect(() => {
    if (!open) return
    const controller = new AbortController()
    void api<History>(`/part-requests/${requestId}/history?offset=${offset}`, { signal: controller.signal })
      .then(value => { if (!controller.signal.aborted) { setData(value); setError(false) } })
      .catch(() => { if (!controller.signal.aborted) setError(true) })
    return () => controller.abort()
  }, [requestId, status, open, offset])
  return <details onToggle={event => setOpen(event.currentTarget.open)}><summary>{t('requests01.history')}</summary>
    {error && <p role="alert">{t('requests.loadError')}</p>}
    {data?.items.map(event => <div className="request-delivery-event" key={event.id}><b>{t(`requests01.event.${event.action_code}` as TranslationKey)}</b><span>{event.actor_name} · <time dateTime={event.occurred_at} title={event.occurred_at}>{date(event.occurred_at)}</time></span></div>)}
    <div className="actions">{offset > 0 && <button className="secondary" onClick={() => setOffset(value => Math.max(0, value - 100))}>{t('timeline.previous')}</button>}{data?.has_next && <button className="secondary" onClick={() => setOffset(value => value + 100)}>{t('timeline.next')}</button>}</div>
  </details>
}
