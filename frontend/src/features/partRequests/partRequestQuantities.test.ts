import { describe, expect, it } from 'vitest'

import {
  formatCatalogSourceQuantity,
  formatTransactionalPartQuantity,
  isDeliveredPartQuantity,
  isRequestedPartQuantity,
} from './partRequestQuantities'

describe('part-request quantity rules', () => {
  it('accepts only positive whole requested quantities', () => {
    expect(isRequestedPartQuantity(1)).toBe(true)
    expect(isRequestedPartQuantity(20)).toBe(true)
    expect(isRequestedPartQuantity(0)).toBe(false)
    expect(isRequestedPartQuantity(1.04)).toBe(false)
  })

  it('accepts zero and positive whole delivered quantities only', () => {
    expect(isDeliveredPartQuantity(0)).toBe(true)
    expect(isDeliveredPartQuantity(3)).toBe(true)
    expect(isDeliveredPartQuantity(-1)).toBe(false)
    expect(isDeliveredPartQuantity(0.06)).toBe(false)
  })

  it('formats integral transactions without suffixes while retaining legacy fractions', () => {
    expect(formatTransactionalPartQuantity(4)).toBe('4')
    expect(formatTransactionalPartQuantity(1.5)).toBe('1.5')
  })

  it('uses parsed integral source quantities but preserves ambiguous raw source text', () => {
    expect(formatCatalogSourceQuantity(1, '1,00')).toBe('1')
    expect(formatCatalogSourceQuantity(2, '2.00')).toBe('2')
    expect(formatCatalogSourceQuantity(null, '1 each')).toBe('1 each')
    expect(formatCatalogSourceQuantity(1.5, '1,50')).toBe('1,50')
  })
})
