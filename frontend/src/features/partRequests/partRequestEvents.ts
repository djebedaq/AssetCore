export const PART_REQUESTS_CHANGED_EVENT = 'assetcore-part-requests-changed'

export function notifyPartRequestsChanged() {
  window.dispatchEvent(new Event(PART_REQUESTS_CHANGED_EVENT))
}
