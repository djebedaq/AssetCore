import { useEffect, useRef, useState } from 'react'

const ENTRY = 'assetcoreMachineEntry'
let routeOwner = 0

export function machineIdFromPath(path: string): number | null {
  const match = /^\/machine\/(\d+)\/?$/.exec(path)
  const id = match ? Number(match[1]) : NaN
  return Number.isSafeInteger(id) && id > 0 ? id : null
}

// Navigation metadata only; never a credential or a workflow intent. A reload
// deliberately forgets ownership, so closing a direct QR cannot leave the app.
export function useMachineEntryRoute() {
  const [machineId, setMachineId] = useState(() => machineIdFromPath(window.location.pathname))
  const [owner] = useState(() => ++routeOwner)
  const entries = useRef(new Set<number>())
  const sequence = useRef(0)

  function ownedDepth(): number {
    const entry = window.history.state?.[ENTRY]
    return entry?.owner === owner && entries.current.has(entry.sequence) ? entry.depth : 0
  }

  useEffect(() => {
    function synchronize() {
      const id = machineIdFromPath(window.location.pathname)
      if (/^\/machine(?:\/|$)/.test(window.location.pathname)) {
        const path = id === null ? '/' : `/machine/${id}`
        if (window.location.pathname !== path) window.history.replaceState(window.history.state, '', path)
      }
      setMachineId(id)
    }
    synchronize()
    window.addEventListener('popstate', synchronize)
    return () => window.removeEventListener('popstate', synchronize)
  }, [])

  function leave() {
    const state = { ...window.history.state }
    delete state[ENTRY]
    if (machineIdFromPath(window.location.pathname) !== null) window.history.replaceState(state, '', '/')
    setMachineId(null)
  }

  return {
    machineId,
    open(id: number) {
      if (!Number.isSafeInteger(id) || id <= 0) return
      if (machineIdFromPath(window.location.pathname) === id) { setMachineId(id); return }
      const depth = machineIdFromPath(window.location.pathname) === null ? 1 : ownedDepth() ? ownedDepth() + 1 : 0
      const next = ++sequence.current
      entries.current.add(next)
      window.history.pushState({ ...window.history.state, [ENTRY]: { owner, sequence: next, depth } }, '', `/machine/${id}`)
      setMachineId(id)
    },
    close() {
      const depth = ownedDepth()
      if (depth > 0) {
        setMachineId(null)
        window.history.go(-depth)
      } else leave()
    },
    // Deliberate handoff replaces the current machine URL; it must not replay
    // browser Back and overwrite the newly selected product workspace.
    leave,
  }
}
