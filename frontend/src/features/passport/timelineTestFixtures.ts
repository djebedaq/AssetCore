import type { MachineTimelineItem, MachineTimelinePage } from '../../types'

export function timelineItem(overrides: Partial<MachineTimelineItem> = {}): MachineTimelineItem {
  return {
    event_key: 'transfer:2:return_requested', category: 'transfer', event_type: 'TRANSFER_RETURN_REQUESTED',
    occurred_at: '2026-09-01T08:42:00Z', reference: 'QA-TIMELINE-ONLY', source_type: 'transfer', source_id: 2,
    status_before: null, status_after: null, description: null, machine_id: 13,
    related: { transfer_id: 2, repair_id: null, part_request_id: null, official_document_id: null },
    details: {}, ...overrides,
  }
}

export function timelinePage(overrides: Partial<MachineTimelinePage> = {}): MachineTimelinePage {
  return {
    machine_id: 13, limited_view: false, category: 'all', total: 1, count: 1, page: 1,
    page_size: 25, total_pages: 1, has_previous: false, has_next: false,
    items: [timelineItem()], ...overrides,
  }
}
