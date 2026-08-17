import { api } from '../../api'
import type { CatalogPartEnhanced, Machine, RepairCase } from '../../types'

export type RepairCreateInput = {
  machine_id: number
  reported_problem: string
  condition_before: string
}

export type RepairAttachmentInput = {
  filename: string
  media_type: string
  content_base64: string
  stage: string
  description: string
}

export type RepairPartInput = {
  catalog_part_id: number
  part_number: string
  description: string
  quantity: number
  unit?: string | null
  source?: string | null
}

export type RepairParticipantInput = {
  full_name: string
  job_title: string | null
  contribution: string | null
  minutes_worked: number
}

export const repairApi = {
  list: () => api<RepairCase[]>('/repair-cases'),
  machines: () => api<Machine[]>('/machines'),
  get: (repairId: number) => api<RepairCase>(`/repair-cases/${repairId}`),
  verifiedParts: (machineId: number) => api<CatalogPartEnhanced[]>(`/catalog/parts?verified_only=true&machine_id=${machineId}`),
  create: (input: RepairCreateInput) => api<RepairCase>('/repair-cases', { method: 'POST', body: JSON.stringify(input) }),
  update: (repairId: number, input: Record<string, unknown>) => api<RepairCase>(`/repair-cases/${repairId}`, { method: 'PATCH', body: JSON.stringify(input) }),
  upload: (repairId: number, input: RepairAttachmentInput) => api(`/repair-cases/${repairId}/attachments`, { method: 'POST', body: JSON.stringify(input) }),
  generateDocuments: (repairId: number) => api(`/repair-cases/${repairId}/documents`, { method: 'POST' }),
  addPart: (repairId: number, input: RepairPartInput) => api(`/repair-cases/${repairId}/parts`, { method: 'POST', body: JSON.stringify(input) }),
  addParticipant: (repairId: number, input: RepairParticipantInput) => api(`/repair-cases/${repairId}/participants`, { method: 'POST', body: JSON.stringify(input) }),
  removeParticipant: (repairId: number, participantId: number) => api(`/repair-cases/${repairId}/participants/${participantId}`, { method: 'DELETE' }),
}
