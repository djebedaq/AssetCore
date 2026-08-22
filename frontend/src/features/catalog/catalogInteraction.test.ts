import { describe, expect, it } from 'vitest'

import {
  exceedsTapMovementThreshold,
  resolveHotspotActivation,
} from './catalogInteraction'

describe('diagram hotspot interaction state machine', () => {
  it('opens a desktop hotspot with one mouse click', () => {
    expect(resolveHotspotActivation({
      pointerType: 'mouse',
      selectedPosition: null,
      targetPosition: '34',
      moved: false,
      pinched: false,
      cancelled: false,
    })).toBe('open')
  })

  it('selects on the first touch and opens on the next touch of the same position', () => {
    expect(resolveHotspotActivation({
      pointerType: 'touch',
      selectedPosition: null,
      targetPosition: '34',
      moved: false,
      pinched: false,
      cancelled: false,
    })).toBe('select')
    expect(resolveHotspotActivation({
      pointerType: 'touch',
      selectedPosition: '34',
      targetPosition: '34',
      moved: false,
      pinched: false,
      cancelled: false,
    })).toBe('open')
  })

  it('changes selection instead of opening when a different position is touched', () => {
    expect(resolveHotspotActivation({
      pointerType: 'touch',
      selectedPosition: '34',
      targetPosition: '35',
      moved: false,
      pinched: false,
      cancelled: false,
    })).toBe('select')
  })

  it.each([
    { moved: true, pinched: false, cancelled: false, name: 'drag or pan' },
    { moved: false, pinched: true, cancelled: false, name: 'pinch' },
    { moved: false, pinched: false, cancelled: true, name: 'cancelled gesture' },
  ])('ignores $name instead of opening details', ({ moved, pinched, cancelled }) => {
    expect(resolveHotspotActivation({
      pointerType: 'touch',
      selectedPosition: '34',
      targetPosition: '34',
      moved,
      pinched,
      cancelled,
    })).toBe('ignore')
  })

  it('uses an eight-pixel movement threshold', () => {
    expect(exceedsTapMovementThreshold(10, 10, 17, 10)).toBe(false)
    expect(exceedsTapMovementThreshold(10, 10, 18, 10)).toBe(true)
  })
})
