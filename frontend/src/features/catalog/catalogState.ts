import type {
  CatalogCartLine,
  CatalogPart,
  CatalogRepairKit,
} from './catalogTypes'

export function partToCartLine(part: CatalogPart, quantity = 1): CatalogCartLine {
  return {
    catalog_part_id: part.id,
    source_record_key: part.source_record_key,
    position: part.position,
    part_number: part.order_part_number,
    source_part_number: part.part_number,
    description: part.description,
    quantity,
    source_quantity_raw: part.quantity_raw,
    assembly: part.assembly,
    source_document: part.source_document,
    source_page: part.source_page,
    replacement_applied: Boolean(part.replaced_by_part_number),
  }
}

export function mergeCartLine(
  current: CatalogCartLine[],
  incoming: CatalogCartLine,
): CatalogCartLine[] {
  const existing = current.find(
    (line) => line.source_record_key === incoming.source_record_key,
  )
  if (!existing) return [...current, incoming]
  return current.map((line) => (
    line.source_record_key === incoming.source_record_key
      ? { ...line, quantity: line.quantity + incoming.quantity }
      : line
  ))
}

export function addPart(current: CatalogCartLine[], part: CatalogPart): CatalogCartLine[] {
  return mergeCartLine(current, partToCartLine(part, 1))
}

export function addRepairKit(
  current: CatalogCartLine[],
  kit: CatalogRepairKit,
  parts: CatalogPart[],
): CatalogCartLine[] {
  return kit.components.reduce((cart, component) => {
    const part = parts.find((candidate) => candidate.id === component.part_id)
    if (!part) return cart
    return mergeCartLine(cart, partToCartLine(part, component.quantity))
  }, current)
}

export function updateCartQuantity(
  current: CatalogCartLine[],
  sourceRecordKey: string,
  quantity: number,
): CatalogCartLine[] {
  if (!Number.isFinite(quantity) || quantity <= 0) return current
  return current.map((line) => (
    line.source_record_key === sourceRecordKey ? { ...line, quantity } : line
  ))
}
