import { describe, expect, it } from 'vitest'

import {
  exceedsTapMovementThreshold,
  resolveHotspotActivation,
  resolveHotspotHit,
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

describe('deterministic authoritative hotspot hit resolution', () => {
  // Deliberately overlapping synthetic positions 1/9; never persisted.
  const one = Object.freeze({ id: 101, position: '1', x: 0.25, y: 0.25, width: 0.25, height: 0.25 })
  const nine = Object.freeze({ id: 109, position: '9', x: 0.375, y: 0.25, width: 0.25, height: 0.25 })
  const bounds = { left: 15, top: 100, width: 360, height: 480 }
  const point = (x: number, y = 0.375, size = bounds) => ({ clientX: size.left + x * size.width, clientY: size.top + y * size.height })

  it.each([
    { name: 'H1 overlap nearest 1', x: 0.4, expected: one },
    { name: 'H2 overlap nearest 9', x: 0.475, expected: nine },
    { name: 'H4 only position 1', x: 0.3, expected: one },
    { name: 'H5 only position 9', x: 0.6, expected: nine },
    { name: 'H6 exact distance/area tie uses stable ID', x: 0.4375, expected: one },
  ])('$name, including H3 reversed input order', ({ x, expected }) => {
    for (const items of [Object.freeze([one, nine]), Object.freeze([nine, one])]) {
      expect(resolveHotspotHit(items, point(x), bounds)).toBe(expected)
    }
  })

  it('breaks a tied center distance by smaller area before considering the ID', () => {
    const large = { ...one, id: 1, x: 0.125, y: 0.125, width: 0.5, height: 0.5 }
    const small = { ...one, id: 9 }
    for (const items of [[large, small], [small, large]]) {
      expect(resolveHotspotHit(items, point(0.375), bounds)).toBe(small)
    }
  })

  it.each([1, 1.4, 3])('keeps the same normalized hit under scale %s and a scrolled canvas offset', scale => {
    const size = { left: -80, top: -120, width: bounds.width * scale, height: bounds.height * scale }
    expect(resolveHotspotHit([one, nine], point(0.4, 0.375, size), size, nine.id)).toBe(one)
    expect(resolveHotspotHit([nine, one], point(0.475, 0.375, size), size, one.id)).toBe(nine)
  })

  it('measures physical center proximity with the rendered canvas aspect ratio', () => {
    const horizontal = { id: 1, x: 0.375, y: 0.25, width: 0.5, height: 0.5 }
    const vertical = { id: 9, x: 0.25, y: 0.5, width: 0.5, height: 0.5 }
    const wide = { left: 0, top: 0, width: 800, height: 200 }
    // 100 px horizontally versus 50 px vertically, although normalized x is smaller.
    expect(resolveHotspotHit([horizontal, vertical], point(0.5, 0.5, wide), wide)).toBe(vertical)
  })

  it('includes rectangle edges but never chooses a non-containing nearest neighbor', () => {
    expect(resolveHotspotHit([nine, one], point(0.25, 0.25), bounds)).toBe(one)
    expect(resolveHotspotHit([one, nine], point(0.625, 0.5), bounds)).toBe(nine)
    expect(resolveHotspotHit([one, nine], point(0.9), bounds)).toBeNull()
    expect(resolveHotspotHit([], point(0.4), bounds)).toBeNull()
  })

  it('uses only a visible event-target fallback when no authoritative rectangle contains the point', () => {
    const outside = point(0.625 + Number.EPSILON)
    expect(resolveHotspotHit([one, nine], outside, bounds, nine.id)).toBe(nine)
    expect(resolveHotspotHit([one], outside, bounds, nine.id)).toBeNull()
    expect(resolveHotspotHit([one, nine], point(0.4), bounds, nine.id)).toBe(one)
  })

  it('retains target fallback for an unmeasured canvas, but rejects invalid pointer coordinates', () => {
    expect(resolveHotspotHit([one, nine], point(0.4), null, nine.id)).toBe(nine)
    expect(resolveHotspotHit([one, nine], point(0.4), { ...bounds, width: 0 }, one.id)).toBe(one)
    expect(resolveHotspotHit([one, nine], { clientX: NaN, clientY: 0 }, bounds, one.id)).toBeNull()
  })

  it('keeps duplicate callouts as distinct occurrences and does not mutate inputs', () => {
    const duplicate = Object.freeze({ ...nine, position: '1' })
    const items = Object.freeze([duplicate, one])
    expect(resolveHotspotHit(items, point(0.475), bounds)).toBe(duplicate)
    expect(items).toEqual([duplicate, one])
  })
})
