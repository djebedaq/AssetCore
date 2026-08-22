export const DIAGRAM_TAP_MOVEMENT_THRESHOLD_PX = 8

export type DiagramPointerKind = 'mouse' | 'pen' | 'touch' | ''

export type HotspotActivation = 'ignore' | 'select' | 'open'

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
