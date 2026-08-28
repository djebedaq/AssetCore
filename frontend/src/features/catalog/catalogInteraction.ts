import type { PositionHotspot } from './catalogTypes'

export const DIAGRAM_TAP_MOVEMENT_THRESHOLD_PX = 8

export type DiagramPointerKind = 'mouse' | 'pen' | 'touch' | ''

export type HotspotActivation = 'ignore' | 'select' | 'open'

export function resolveHotspotHit<T extends Pick<PositionHotspot, 'id' | 'x' | 'y' | 'width' | 'height'>>(
  hotspots: readonly T[],
  pointer: { clientX: number; clientY: number },
  bounds: Pick<DOMRect, 'left' | 'top' | 'width' | 'height'> | null,
  eventTargetId?: number,
): T | null {
  if (!Number.isFinite(pointer.clientX) || !Number.isFinite(pointer.clientY)) return null
  const fallback = hotspots.find((item) => item.id === eventTargetId) || null
  if (!bounds || bounds.width <= 0 || bounds.height <= 0) return fallback
  const x = (pointer.clientX - bounds.left) / bounds.width
  const y = (pointer.clientY - bounds.top) / bounds.height
  const candidates = hotspots.filter((item) => (
    x >= item.x && x <= item.x + item.width && y >= item.y && y <= item.y + item.height
  ))
  // Compare distances in rendered pixels, preserving the canvas aspect ratio.
  // Exact ties use area, then the stable occurrence ID, never render/selection order.
  const distanceSquared = (item: T) => (
    ((x - item.x - item.width / 2) * bounds.width) ** 2
    + ((y - item.y - item.height / 2) * bounds.height) ** 2
  )
  candidates.sort((a, b) => (
    distanceSquared(a) - distanceSquared(b)
    || a.width * a.height - b.width * b.height
    || a.id - b.id
  ))
  // Retain the actual target only when geometry found nothing (e.g. rounding
  // or the existing CSS minimum hit area). Never override a geometric hit.
  return candidates[0] || fallback
}

export function exceedsTapMovementThreshold(
  startX: number,
  startY: number,
  currentX: number,
  currentY: number,
  threshold = DIAGRAM_TAP_MOVEMENT_THRESHOLD_PX,
) {
  return Math.hypot(currentX - startX, currentY - startY) >= threshold
}

export function resolveHotspotActivation({
  pointerType,
  selectedPosition,
  targetPosition,
  moved,
  pinched,
  cancelled,
}: {
  pointerType: DiagramPointerKind
  selectedPosition: string | null
  targetPosition: string
  moved: boolean
  pinched: boolean
  cancelled: boolean
}): HotspotActivation {
  if (moved || pinched || cancelled) return 'ignore'
  if (pointerType === 'touch' && selectedPosition !== targetPosition) return 'select'
  return 'open'
}
