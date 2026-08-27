import { describe, expect, it } from 'vitest'
import { buildIssuePayload, buildReturnPayload, CHECKLIST_ITEMS, EMPTY_ISSUE_FORM, serializeChecklist, type ReturnDraft } from '../transferState'

describe('UI serialization without new business authority', () => {
  it('preserves checklist codes, conditions and note whitespace, converts lengths, and never mutates drafts', () => {
    const items = [
      Object.freeze({ ...CHECKLIST_ITEMS[0], note: '', length_m: '' }),
      Object.freeze({ ...CHECKLIST_ITEMS[1], note: ' note ', length_m: '0' }),
      Object.freeze({ ...CHECKLIST_ITEMS[2], condition: 'MISSING' as const, note: ' ', length_m: '25.5' }),
    ]
    const before = JSON.stringify(items)
    expect(serializeChecklist(items)).toEqual([
      { code: 'pump', condition: 'GOOD', note: null, length_m: null },
      { code: 'supply_hose', condition: 'GOOD', note: ' note ', length_m: 0 },
      { code: 'hp_hose', condition: 'MISSING', note: ' ', length_m: 25.5 },
    ])
    expect(JSON.stringify(items)).toBe(before)
  })

  it('keeps issue selection insertion order and only the existing trim/null conversions', () => {
    const selected = new Set([2, 1])
    const form = Object.freeze({ ...EMPTY_ISSUE_FORM, usage_text: ' task ', condition_text: ' condition ', location_id: '7', remarks: ' note ', recipient_first_name: ' first ', recipient_middle_name: '', recipient_last_name: ' last ', recipient_is_foreign_person: true, recipient_name_exception_reason: ' reason ' })
    const payload = buildIssuePayload(form, selected)
    expect(payload).toEqual({ machine_ids: [2, 1], document_language: 'bg', usage_text: 'task', location_id: 7, condition_text: 'condition', remarks: 'note', checklist: serializeChecklist(CHECKLIST_ITEMS), recipient: { first_name: ' first ', middle_name: null, last_name: ' last ', is_foreign_person: true, name_exception_reason: ' reason ' } })
    expect([...selected]).toEqual([2, 1])
    expect(form.remarks).toBe(' note ')
    expect(payload.checklist[0]).not.toBe(form.checklist[0])
  })

  it('serializes only supplied return drafts without filling missing machines or changing outcome/notes', () => {
    const draft: ReturnDraft = Object.freeze({ transfer_id: 102, machine_id: 2, condition_text: ' condition ', result_text: ' result ', notes: '', missing_equipment: '', damage: '', contamination: '', next_status: 'REPAIR', checklist: CHECKLIST_ITEMS })
    const result = buildReturnPayload({ 2: draft })
    expect(result).toEqual({ document_language: 'bg', items: [{ ...draft, checklist: serializeChecklist(CHECKLIST_ITEMS) }] })
    expect(result.items[0]).not.toBe(draft)
    // The serializer is not a second validator or source of machine availability.
    expect(buildReturnPayload({})).toEqual({ document_language: 'bg', items: [] })
  })
})
