import { DOCUMENT_KEYS } from '../../industrialUi'
import { statusText, type TranslationKey } from '../../i18n'
import type { MachineTimelineItem, TimelineCategory } from '../../types'

type Translator = (key: TranslationKey) => string
export const TIMELINE_CATEGORIES: TimelineCategory[] = ['all', 'asset', 'transfer', 'repair', 'parts', 'document']
export const CATEGORY_KEYS: Record<TimelineCategory, TranslationKey> = {
  all: 'timeline.all', asset: 'timeline.asset', transfer: 'timeline.transfer',
  repair: 'timeline.repair', parts: 'timeline.parts', document: 'timeline.document',
}
const SOURCE_KEYS: Record<string, TranslationKey> = {
  machine_event: 'timeline.sourceMachine', transfer: 'timeline.transfer', repair: 'timeline.repair',
  repair_event: 'timeline.sourceRepairEvent', repair_part: 'timeline.sourceRepairPart',
  part_request: 'passport.partRequests', part_request_approval: 'timeline.sourceApproval',
  part_request_transition: 'timeline.sourceTransition', protocol_document: 'timeline.sourceProtocol',
  generated_document: 'timeline.sourceGenerated', official_document: 'timeline.sourceOfficial',
}
const VERSION_KEYS: Record<string, TranslationKey> = {
  DRAFT: 'official.statusDraft', READY_FOR_SIGNATURE: 'official.statusReady',
  PARTIALLY_SIGNED: 'official.statusPartial', SIGNED: 'official.statusSigned',
  FINALIZED: 'timeline.finalized', SUPERSEDED: 'official.statusSuperseded',
  CANCELLED: 'official.statusCancelled',
}
export function timelineSource(t: Translator, source: string) {
  return t(SOURCE_KEYS[source] || 'timeline.sourceOther')
}
export function timelineStatus(t: Translator, item: MachineTimelineItem, value: string) {
  // A repair_event can belong to parts; machine_event fallbacks still carry machine statuses.
  if (item.source_type === 'machine_event' || item.source_type === 'transfer') return statusText(t, value)
  if (['repair', 'repair_event'].includes(item.source_type)) return statusText(t, value, 'repair')
  if (item.source_type.startsWith('part_request')) {
    return value === 'RETURNED_FOR_CHANGES' ? t('timeline.returnedForChanges') : statusText(t, value, 'part')
  }
  if (item.category === 'document') return VERSION_KEYS[value] ? t(VERSION_KEYS[value]) : value
  return value
}

type Detail = readonly [field: string, label: TranslationKey, format?: 'boolean' | 'number' | 'document' | 'version' | 'registry']
const TRANSFER_DETAILS: Detail[] = [
  ['location_text', 'common.location'], ['accepted_by', 'bulk.acceptedBy'],
  ['condition', 'timeline.condition'], ['result', 'timeline.result'],
]
const PART_DETAILS: Detail[] = [
  ['part_number', 'parts.part'], ['quantity', 'common.quantity', 'number'],
  ['unit', 'requests.unit'], ['source', 'catalog.source'],
]
const REPAIR_DETAILS: Detail[] = [
  ['condition_before', 'repairCase.conditionBefore'], ['reported_problem', 'repairs.reportedProblem'],
  ['condition', 'timeline.condition'], ['result', 'timeline.result'],
  ['missing_equipment', 'bulk.missingEquipment'], ['damage', 'bulk.damage'],
  ['contamination', 'bulk.contamination'], ['notes', 'common.notes'],
  ['test_passed', 'repairCase.testPassed', 'boolean'], ['test_pressure_bar', 'repairCase.testPressure', 'number'],
  ['leaks_detected', 'repairCase.leaksDetected', 'boolean'],
  ['diagnosis_minutes', 'repairCase.diagnosisMinutes', 'number'],
  ['repair_minutes', 'repairCase.repairMinutes', 'number'],
  ['testing_minutes', 'repairCase.testingMinutes', 'number'],
  ['role_in_repair', 'repairCase.participantContribution'],
  ['minutes_worked', 'repairCase.participantMinutes', 'number'],
]
const DOCUMENT_DETAILS: Detail[] = [
  ['document_type', 'official.type', 'document'], ['version', 'signature.version', 'number'],
  ['version_status', 'common.status', 'version'], ['registry_category', 'passport.category', 'registry'],
]
const ASSET_DETAILS: Detail[] = [
  ['inventory_number', 'machines.inventoryNumber'], ['filename', 'library.file'], ['source', 'catalog.source'],
]
const REGISTRY_KEYS: Record<string, TranslationKey> = {
  transfers: 'official.sectionTransfers', repairs: 'official.sectionRepairs', parts: 'official.sectionParts',
}

// Presentation only: explicitly selected scalars, never raw details/related JSON or internal IDs.
export function timelineDetails(t: Translator, number: (value: number) => string, item: MachineTimelineItem) {
  const fields = item.category === 'document' ? DOCUMENT_DETAILS
    : item.source_type === 'repair_event' || item.source_type === 'repair' ? [...REPAIR_DETAILS, ...PART_DETAILS]
      : item.source_type === 'repair_part' ? PART_DETAILS
        : item.category === 'transfer' ? TRANSFER_DETAILS
          : item.category === 'asset' ? ASSET_DETAILS : []
  return fields.flatMap(([field, label, format]) => {
    const value: unknown = item.details?.[field]
    if (value === null || value === undefined || value === '') return []
    let text: string
    if (format === 'boolean') {
      if (typeof value !== 'boolean') return []
      text = t(value ? 'common.yes' : 'common.no')
    } else if (format === 'number') {
      if (typeof value !== 'number' || !Number.isFinite(value)) return []
      text = number(value)
    } else {
      if (typeof value !== 'string') return []
      const keys = format === 'document' ? DOCUMENT_KEYS : format === 'version' ? VERSION_KEYS : format === 'registry' ? REGISTRY_KEYS : {}
      text = keys[value] ? t(keys[value]) : value
    }
    return [{ field, label: t(label), text }]
  })
}
