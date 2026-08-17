import { describe, expect, it } from 'vitest'

import type { RepairCase } from '../../types'
import {
  canonicalRepairStage,
  repairFormFrom,
  repairStagePayload,
} from './workflow'

function repair(overrides: Partial<RepairCase> = {}): RepairCase {
  return {
    id: 41,
    repair_reference: 'REP-2026-000041',
    machine_id: 4,
    machine_number: '4',
    machine_name: 'Machine 4',
    reported_problem: 'Проверка',
    status: 'REPAIRING',
    total_work_minutes: 0,
    participant_total_minutes: 0,
    cleaning_required: false,
    test_required: true,
    participants: [],
    parts_used: [],
    attachments: [],
    generated_documents: [],
    events: [],
    opened_at: '2026-01-01T00:00:00Z',
    ...overrides,
  }
}

describe('repair workflow contract', () => {
  it('keeps historical statuses readable without restoring them as active stages', () => {
    expect(canonicalRepairStage(repair({ status: 'WAITING_APPROVAL' }))).toBe(1)
    expect(canonicalRepairStage(repair({ status: 'WAITING_PARTS' }))).toBe(1)
    expect(canonicalRepairStage(repair({ status: 'TESTING' }))).toBe(3)
  })

  it('builds the same canonical completion payload used by the API', () => {
    const form = repairFormFrom(repair({
      work_performed: 'Извършена работа',
      repair_minutes: 45,
      test_method: 'Функционален тест',
      testing_minutes: 15,
      test_passed: true,
      test_details: 'Успешен тест',
      condition_after: 'Изправна',
      result: 'Възстановена работа',
    }))

    expect(repairStagePayload(form, 3, true)).toEqual({
      test_method: 'Функционален тест',
      test_pressure_bar: null,
      testing_minutes: 15,
      leaks_detected: null,
      electrical_test_result: null,
      functional_test_result: null,
      test_details: 'Успешен тест',
      test_passed: true,
      condition_after: 'Изправна',
      result: 'Възстановена работа',
      status: 'COMPLETED',
    })
  })
})
