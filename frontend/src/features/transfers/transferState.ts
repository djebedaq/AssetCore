export type ChecklistCondition = 'GOOD' | 'SATISFACTORY' | 'REPAIR' | 'FAULTY' | 'MISSING' | 'NA'
export type ChecklistItem = { code: string; condition: ChecklistCondition; note: string; length_m: string }
export const CHECKLIST_ITEMS: ChecklistItem[] = [
  'pump', 'supply_hose', 'hp_hose', 'gun', 'nozzle', 'tips', 'cable', 'plug', 'chassis', 'body',
].map((code) => ({ code, condition: 'GOOD' as ChecklistCondition, note: '', length_m: '' }))
export const LENGTH_CODES = new Set(['supply_hose', 'hp_hose', 'cable'])

export type IssueForm = {
  usage_text: string
  location_id: string
  recipient_first_name: string
  recipient_middle_name: string
  recipient_last_name: string
  recipient_is_foreign_person: boolean
  recipient_name_exception_reason: string
  condition_text: string
  remarks: string
  checklist: ChecklistItem[]
}

export const EMPTY_ISSUE_FORM: IssueForm = {
  usage_text: '',
  location_id: '',
  recipient_first_name: '',
  recipient_middle_name: '',
  recipient_last_name: '',
  recipient_is_foreign_person: false,
  recipient_name_exception_reason: '',
  condition_text: '',
  remarks: '',
  checklist: CHECKLIST_ITEMS.map((item) => ({ ...item })),
}

export type ReturnDraft = {
  transfer_id: number
  machine_id: number
  condition_text: string
  result_text: string
  notes: string
  missing_equipment: string
  damage: string
  contamination: string
  next_status: 'READY' | 'REPAIR'
  checklist: ChecklistItem[]
}

// UI draft serialization only. Availability, validity and atomicity remain server-owned.
export function serializeChecklist(items: ChecklistItem[]) {
  return items.map((item) => ({ ...item, length_m: item.length_m === '' ? null : Number(item.length_m), note: item.note || null }))
}

export function buildIssuePayload(form: IssueForm, selected: Set<number>) {
  const {
    recipient_first_name, recipient_middle_name, recipient_last_name,
    recipient_is_foreign_person, recipient_name_exception_reason,
  } = form
  return {
    machine_ids: [...selected],
    document_language: 'bg',
    usage_text: form.usage_text.trim(),
    location_id: Number(form.location_id),
    condition_text: form.condition_text.trim(),
    remarks: form.remarks.trim() || null,
    checklist: serializeChecklist(form.checklist),
    recipient: {
      first_name: recipient_first_name,
      middle_name: recipient_middle_name || null,
      last_name: recipient_last_name,
      is_foreign_person: recipient_is_foreign_person,
      name_exception_reason: recipient_name_exception_reason || null,
    },
  }
}

export function buildReturnPayload(drafts: Record<number, ReturnDraft>) {
  return {
    document_language: 'bg',
    items: Object.values(drafts).map((draft) => ({
      ...draft,
      checklist: serializeChecklist(draft.checklist),
    })),
  }
}
