import type { TranslationKey } from '../../i18n'
import type { RepairCase } from '../../types'

export const repairStageOrder = ['ACCEPTED', 'DIAGNOSIS', 'REPAIRING', 'COMPLETED'] as const
export type RepairStage = typeof repairStageOrder[number]

export const repairStageTitleKeys: Record<RepairStage, TranslationKey> = {
  ACCEPTED: 'repairCase.stage.accepted',
  DIAGNOSIS: 'repairCase.stage.diagnosis',
  REPAIRING: 'repairCase.stage.repairing',
  COMPLETED: 'repairCase.stage.completed',
}

export type RepairFormState = {
  reported_problem: string; condition_before: string; removed_parts_text: string;
  diagnostic_cleaning: string; diagnosis: string; required_work: string;
  required_parts_text: string; diagnosis_minutes: string; work_performed: string;
  repair_minutes: string; test_method: string; test_pressure_bar: string;
  testing_minutes: string; leaks_detected: string; electrical_test_result: string;
  functional_test_result: string; test_details: string; test_passed: string;
  condition_after: string; result: string;
}

export function repairFormFrom(data: RepairCase): RepairFormState {
  return {
    reported_problem: data.reported_problem || '', condition_before: data.condition_before || '',
    removed_parts_text: data.removed_parts_text || '', diagnostic_cleaning: data.diagnostic_cleaning || '',
    diagnosis: data.diagnosis || '', required_work: data.required_work || '', required_parts_text: data.required_parts_text || '',
    diagnosis_minutes: data.diagnosis_minutes != null ? String(data.diagnosis_minutes) : '',
    work_performed: data.work_performed || '', repair_minutes: data.repair_minutes != null ? String(data.repair_minutes) : '',
    test_method: data.test_method || '', test_pressure_bar: data.test_pressure_bar != null ? String(data.test_pressure_bar) : '',
    testing_minutes: data.testing_minutes != null ? String(data.testing_minutes) : '',
    leaks_detected: data.leaks_detected == null ? '' : data.leaks_detected ? 'yes' : 'no',
    electrical_test_result: data.electrical_test_result || '', functional_test_result: data.functional_test_result || '',
    test_details: data.test_details || '', test_passed: data.test_passed == null ? '' : data.test_passed ? 'yes' : 'no',
    condition_after: data.condition_after || '', result: data.result || '',
  }
}

export function canonicalRepairStage(repair: RepairCase): number {
  if (repair.status === 'COMPLETED') return 3
  if (repair.status === 'ACCEPTED') return 0
  if (repair.status === 'DIAGNOSIS' || repair.status === 'WAITING_APPROVAL') return 1
  if (repair.status === 'TESTING') return 3
  if (repair.status === 'WAITING_PARTS' && !repair.work_performed && !repair.repair_minutes) return 1
  const finalizationStarted = repair.events.some((event) =>
    event.status_after === 'TESTING'
    || event.event_type === 'TEST'
    || event.structured_data?.wizard_stage === 'COMPLETION'
  )
  return finalizationStarted || repair.test_method || repair.test_details || repair.testing_minutes ? 3 : 2
}

export function durationText(
  minutes: number | null | undefined,
  t: (key: TranslationKey, params?: Record<string, string | number>) => string,
): string {
  if (!minutes) return t('common.noValue')
  const hours = Math.floor(minutes / 60)
  const remainder = minutes % 60
  return [
    hours ? t('repairCase.durationHours', { count: hours }) : '',
    remainder ? t('repairCase.durationMinutes', { count: remainder }) : '',
  ].filter(Boolean).join(' ')
}

export function repairStagePayload(
  form: RepairFormState,
  stage: number,
  advance: boolean,
): Record<string, unknown> {
  const stagePayloads: Record<number, Record<string, unknown>> = {
    0: { reported_problem: form.reported_problem, condition_before: form.condition_before },
    1: { removed_parts_text: form.removed_parts_text || null, diagnostic_cleaning: form.diagnostic_cleaning || null, diagnosis: form.diagnosis, required_work: form.required_work, required_parts_text: form.required_parts_text || null, diagnosis_minutes: form.diagnosis_minutes ? Number(form.diagnosis_minutes) : null },
    2: { work_performed: form.work_performed, repair_minutes: form.repair_minutes ? Number(form.repair_minutes) : null },
    3: { test_method: form.test_method, test_pressure_bar: form.test_pressure_bar ? Number(form.test_pressure_bar) : null, testing_minutes: form.testing_minutes ? Number(form.testing_minutes) : null, leaks_detected: form.leaks_detected ? form.leaks_detected === 'yes' : null, electrical_test_result: form.electrical_test_result || null, functional_test_result: form.functional_test_result || null, test_details: form.test_details, test_passed: form.test_passed ? form.test_passed === 'yes' : null, condition_after: form.condition_after, result: form.result },
  }
  const payload = stagePayloads[stage]
  if (!payload) throw new Error(`Unknown repair stage: ${stage}`)
  if (advance && stage === 0) payload.status = 'DIAGNOSIS'
  if (advance && stage === 1) payload.status = 'REPAIRING'
  if (advance && stage === 2) payload.advance_to_final = true
  if (advance && stage === 3) payload.status = 'COMPLETED'
  return payload
}
