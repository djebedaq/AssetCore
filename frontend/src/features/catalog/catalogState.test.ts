import { describe, expect, it } from 'vitest'

import { addPart, addRepairKit, partToCartLine, updateCartQuantity } from './catalogState'
import type { CatalogPart, CatalogRepairKit } from './catalogTypes'

function part(overrides: Partial<CatalogPart> = {}): CatalogPart {
  return {
    id: 34,
    source_record_key: 'hydwin-plunger-34',
    source_id: 'HYDWIN_FUSSEN_500_PLUNGER_PUMP',
    source_row_index: 34,
    family: 'HYDWIN_FUSSEN_500',
    brand: 'HYDWIN/Fussen',
    model: 'FCE15/50',
    assembly: 'PLUNGER_PUMP',
    position: '34',
    part_number: '7.906-007.11',
    order_part_number: '7.906-007.11',
    description: 'Main water seal',
    original_name: 'Main water seal',
    description_2: '15*24*9.3',
    quantity: 3,
    quantity_raw: '3',
    source_document: 'ONLY_PLUNGER_PUMP.pdf',
    source_page: 22,
    source_version: 'PARTS_CATALOG_V2',
    source_document_sha256: '5b5d89b5ebcd71dc8f203d7a6ef419e9f131eaf7f95a1cbe3221992d5c6b7056',
    verification_status: 'VERIFIED',
    source_anomaly_codes: [],
    is_verified: true,
    ...overrides,
  }
}

function repairKit(components: CatalogRepairKit['components']): CatalogRepairKit {
  return {
    id: 1,
    code: 'E1800023',
    name: 'E1800023',
    family: 'FALCH_500',
    source_id: 'FALCH_500_VALVE_500BAR',
    brand: 'Falch',
    model: 'Wheel Jet 15-e',
    assembly: 'VALVE_500BAR',
    source_document: 'VALVE_500BAR_PARTLIST.pdf',
    source_page: 3,
    source_document_sha256: 'ff4a643c60109636e6ebc619551d46ab57b05542fca32a46e3390dec130d14af',
    source_version: 'PARTS_CATALOG_V2',
    is_approved: true,
    is_active: true,
    components,
  }
}

describe('authoritative catalog cart', () => {
  it('keeps the source BOM quantity separate and defaults one selected position to order quantity 1', () => {
    const line = partToCartLine(part())

    expect(line.quantity).toBe(1)
    expect(line.source_quantity_raw).toBe('3')
    expect(line.part_number).toBe('7.906-007.11')
  })

  it('uses the official replacement number for ordering while retaining source identity', () => {
    const line = partToCartLine(part({
      part_number: 'OLD-001',
      order_part_number: 'NEW-002',
      replaced_by_part_number: 'NEW-002',
    }))

    expect(line.part_number).toBe('NEW-002')
    expect(line.source_part_number).toBe('OLD-001')
    expect(line.replacement_applied).toBe(true)
  })

  it('merges repeated clicks deterministically by source row without merging applicability variants', () => {
    const first = part({ source_record_key: 'pump-pos-0-a', valid_for_raw: 'variant A' })
    const second = part({ id: 35, source_record_key: 'pump-pos-0-b', valid_for_raw: 'variant B' })
    const cart = addPart(addPart(addPart([], first), first), second)

    expect(cart).toHaveLength(2)
    expect(cart.find((line) => line.source_record_key === first.source_record_key)?.quantity).toBe(2)
    expect(cart.find((line) => line.source_record_key === second.source_record_key)?.quantity).toBe(1)
  })

  it('adds only source-linked repair-kit members with their source-backed quantities', () => {
    const seat = part({ id: 3, source_record_key: 'valve-pos-3', position: '3', part_number: 'E1230058', order_part_number: 'E1230058', description: 'valve seat', quantity_raw: '1' })
    const holder = part({ id: 4, source_record_key: 'valve-pos-4', position: '4', part_number: 'E1230059', order_part_number: 'E1230059', description: 'holder', quantity_raw: '2' })
    const unrelated = part({ id: 99, source_record_key: 'unrelated', position: '99' })
    const kit = repairKit([
      { id: 1, part_id: 3, source_record_key: seat.source_record_key, position: '3', part_number: seat.part_number, description: seat.description, quantity: 1, quantity_raw: '1', source_document: seat.source_document, source_page: seat.source_page },
      { id: 2, part_id: 4, source_record_key: holder.source_record_key, position: '4', part_number: holder.part_number, description: holder.description, quantity: 2, quantity_raw: '2', source_document: holder.source_document, source_page: holder.source_page },
    ])

    const cart = addRepairKit([], kit, [seat, holder, unrelated])

    expect(cart.map((line) => [line.part_number, line.quantity])).toEqual([
      ['E1230058', 1],
      ['E1230059', 2],
    ])
    expect(cart.some((line) => line.source_record_key === unrelated.source_record_key)).toBe(false)
  })

  it('rejects invalid order quantities without corrupting the cart', () => {
    const cart = addPart([], part())
    expect(updateCartQuantity(cart, cart[0].source_record_key, 0)).toEqual(cart)
    expect(updateCartQuantity(cart, cart[0].source_record_key, Number.NaN)).toEqual(cart)
  })
})
