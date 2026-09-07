import { useEffect, useRef, useState } from 'react'

import { api } from '../../api'
import type { MachineTimelinePage, TimelineCategory } from '../../types'

export const TIMELINE_PAGE_SIZE = 25

// Owned by the keyed passport, not the tab: one cached view survives tab switches,
// never another machine or a closed passport. No browser storage or background polling.
export function usePassportTimeline(machineId: number, active: boolean) {
  const [category, setCategory] = useState<TimelineCategory>('all')
  const [page, setPage] = useState(1)
  const [attempt, setAttempt] = useState(0)
  const [data, setData] = useState<MachineTimelinePage | null>(null)
  const [error, setError] = useState(false)
  const [loading, setLoading] = useState(false)
  const settled = useRef<string | null>(null)
  const generation = useRef(0)

  useEffect(() => {
    const key = `${machineId}:${category}:${page}:${attempt}`
    if (!active || settled.current === key) return
    const controller = new AbortController()
    const request = ++generation.current
    setData(null)
    setError(false)
    setLoading(true)
    void api<MachineTimelinePage>(
      `/machines/${machineId}/timeline?category=${category}&page=${page}&page_size=${TIMELINE_PAGE_SIZE}`,
      { signal: controller.signal },
    ).then((result) => {
      if (controller.signal.aborted || request !== generation.current) return
      // Reject a response for another context; do not silently filter/deduplicate it.
      if (result.machine_id !== machineId || result.category !== category || result.page !== page) {
        throw new Error('Timeline response context mismatch')
      }
      setData(result)
      settled.current = key
    }).catch((caught: unknown) => {
      if (controller.signal.aborted || request !== generation.current) return
      if (caught instanceof Error && caught.name === 'AbortError') return
      setError(true)
      settled.current = key
    }).finally(() => {
      if (!controller.signal.aborted && request === generation.current) setLoading(false)
    })
    return () => {
      ++generation.current
      controller.abort()
    }
  }, [active, machineId, category, page, attempt])

  function clearView() {
    ++generation.current
    setData(null)
    setError(false)
    setLoading(true)
    settled.current = null
  }

  return {
    category, data, error, loading,
    selectCategory(next: TimelineCategory) {
      if (next === category) return
      clearView()
      setCategory(next)
      setPage(1)
    },
    selectPage(next: number) {
      if (next === page) return
      clearView()
      setPage(next)
    },
    retry() {
      clearView()
      setAttempt((value) => value + 1)
    },
  }
}
