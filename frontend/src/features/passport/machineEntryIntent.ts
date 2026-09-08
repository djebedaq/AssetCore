// Transient navigation only. The receiving workflow revalidates its own current
// data; these IDs never authorize or submit an operation.
export type TransferEntryIntent = { action: 'issue' | 'return'; machineId: number }
export type RepairEntryIntent =
  | { action: 'repair-create'; machineId: number }
  | { action: 'repair-open'; machineId: number; repairId: number }
export type MachineEntryIntent = TransferEntryIntent | RepairEntryIntent
