import { cleanup, render, screen, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { translatedEventCode } from '../../industrialUi'
import { catalogs, formatDate, I18nProvider, translate, type TranslationKey } from '../../i18n'
import { clearSessionUser } from '../../permissions'
import { PassportTimelineTab } from './PassportTimelineTab'
import { timelineDetails, timelineSource, timelineStatus } from './timelinePresentation'
import { timelineItem, timelinePage } from './timelineTestFixtures'

// Complete ASSET-03A emitted set: ASSET_DETAILS, REPAIR_DETAILS, transfer/request
// milestones, exact fallback codes and canonical/legacy document entries.
export const TIMELINE_EVENT_CODES = [
  'MACHINE_CREATED', 'MACHINE_UPDATED', 'CUSTOM_FIELDS_UPDATED', 'ATTACHMENT_ADDED', 'IMPORTED', 'LOCATION_CHANGED', 'MACHINE_LOCATION_CHANGED',
  'TRANSFER_ISSUED', 'TRANSFER_RETURN_REQUESTED', 'TRANSFER_RETURNED',
  'ACCEPTED', 'RETURN_DIRECTED_TO_REPAIR', 'INSPECTION', 'CLEANING', 'DIAGNOSIS', 'APPROVAL', 'PARTS', 'REPAIR_ACTION', 'TEST', 'STATUS_CHANGE', 'COMPLETED',
  'PARTICIPANT_ADDED', 'PARTICIPANT_REMOVED', 'PART_ADDED', 'DOCUMENT_GENERATED', 'NOTE',
  'REPAIR_OPENED', 'REPAIR_COMPLETED', 'REPAIR_ACCEPTED', 'REPAIR_STATUS_CHANGED', 'REPAIR_EVENT',
  'PART_USED', 'PART_REQUEST_CREATED', 'PART_REQUEST_SUBMITTED', 'PART_REQUEST_APPROVED', 'PART_REQUEST_REJECTED',
  'PART_REQUEST_RETURNED_FOR_CHANGES', 'PART_REQUEST_ORDERED', 'PART_REQUEST_PARTIALLY_DELIVERED', 'PART_REQUEST_DELIVERED', 'PART_REQUEST_CANCELLED',
  'OFFICIAL_DOCUMENT_CREATED', 'OFFICIAL_DOCUMENT_FINALIZED', 'LEGACY_DOCUMENT_CREATED',
] as const

afterEach(() => { cleanup(); clearSessionUser(); localStorage.clear() })
describe.each(['bg', 'en', 'ru'] as const)('ASSET-03A translations in %s', (locale) => {
  const t = (key: TranslationKey) => translate(locale, key)
  it.each(TIMELINE_EVENT_CODES)('explicitly translates emitted %s without event.other or raw fallback', (code) => {
    const label = translatedEventCode(t, code)
    expect(label).not.toBe(t('event.other'))
    expect(label).not.toBe(code)
    expect(label.trim().length).toBeGreaterThan(0)
    if (locale === 'en') expect(label).not.toMatch(/[А-Яа-я]/)
  })
  it('renders all event titles in the selected locale, plus localized date/time and safe unknown fallback', () => {
    clearSessionUser()
    const items = TIMELINE_EVENT_CODES.map((code, index) => timelineItem({ event_key: `qa:${index}`, event_type: code }))
    render(<I18nProvider initialLocale={locale}><PassportTimelineTab timeline={{
      data: timelinePage({ items, total: items.length, count: items.length }), category: 'all',
      loading: false, error: false, selectCategory: vi.fn(), selectPage: vi.fn(), retry: vi.fn(),
    }} /></I18nProvider>)
    const cards = screen.getAllByRole('article')
    expect(cards).toHaveLength(44)
    items.forEach((item, index) => {
      expect(within(cards[index]).getByRole('heading')).toHaveTextContent(translatedEventCode(t, item.event_type))
    })
    expect(screen.getAllByText(formatDate(locale, items[0].occurred_at))).toHaveLength(44)
    expect(translatedEventCode(t, 'NEW_UNRECOGNIZED_EVENT')).toBe(t('event.other'))
  })
  it('keeps part/repair/machine/document status domains distinct including FINALIZED and SUPERSEDED', () => {
    const cases = [
      [{ source_type: 'machine_event' }, 'ISSUED', 'status.issued'],
      [{ category: 'parts', source_type: 'repair_event' }, 'REPAIRING', 'status.repairing'],
      [{ category: 'parts', source_type: 'part_request_approval' }, 'RETURNED_FOR_CHANGES', 'timeline.returnedForChanges'],
      [{ category: 'parts', source_type: 'part_request_transition' }, 'PARTIALLY_DELIVERED', 'status.partiallyDelivered'],
      [{ category: 'document', source_type: 'official_document' }, 'FINALIZED', 'timeline.finalized'],
      [{ category: 'document', source_type: 'official_document' }, 'SUPERSEDED', 'official.statusSuperseded'],
    ] as const
    for (const [properties, status, key] of cases) expect(timelineStatus(t, timelineItem(properties), status)).toBe(t(key))
    expect(timelineStatus(t, timelineItem({ source_type: 'future_source' }), 'Human readable future status')).toBe('Human readable future status')
  })
  it('translates every canonical source instead of exposing source codes', () => {
    for (const code of ['machine_event', 'transfer', 'repair', 'repair_event', 'repair_part', 'part_request', 'part_request_approval', 'part_request_transition', 'protocol_document', 'generated_document', 'official_document']) {
      expect(timelineSource(t, code)).not.toBe(t('timeline.sourceOther'))
      expect(timelineSource(t, code)).not.toBe(code)
    }
  })
  it('keeps safe detail scalars and does not recurse into objects or arrays', () => {
    const item = timelineItem({ source_type: 'repair_event', category: 'parts', details: {
      part_number: 'QA part', quantity: 1.04, source: 'QA provenance', test_passed: false,
      arbitrary: 'HIDDEN', notes: ['HIDDEN'], related: null,
    } })
    const rows = timelineDetails(t, String, item)
    expect(rows.map((row) => row.text)).toEqual([t('common.no'), 'QA part', '1.04', 'QA provenance'])
    expect(JSON.stringify(rows)).not.toContain('HIDDEN')
  })
})

it('keeps timeline translation key parity and explicit non-BG values in EN/RU', () => {
  const keys = Object.keys(catalogs.bg).filter((key) => key.startsWith('timeline.')) as TranslationKey[]
  for (const key of keys) {
    expect(catalogs.en[key]).toBeTruthy()
    expect(catalogs.ru[key]).toBeTruthy()
    expect(catalogs.en[key]).not.toBe(catalogs.bg[key])
  }
})
