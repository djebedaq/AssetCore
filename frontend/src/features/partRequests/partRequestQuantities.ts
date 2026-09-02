export function isRequestedPartQuantity(value: number): boolean {
  return Number.isInteger(value) && value >= 1
}

export function isDeliveredPartQuantity(value: number): boolean {
  return Number.isInteger(value) && value >= 0
}

export function formatTransactionalPartQuantity(value: number): string {
  return Number.isInteger(value) ? value.toFixed(0) : String(value)
}

export function formatCatalogSourceQuantity(
  quantity: number | null | undefined,
  quantityRaw: string,
): string {
  if (typeof quantity === 'number' && Number.isFinite(quantity) && Number.isInteger(quantity)) {
    return quantity.toFixed(0)
  }
  return quantityRaw
}
