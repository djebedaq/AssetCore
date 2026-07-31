export type Location = { id: number; name: string; description?: string | null }
export type Machine = {
  id: number; inventory_number: string; name: string; category: string; brand: string;
  model?: string | null; pressure_bar: number; serial_number?: string | null; status: string;
  location_id?: number | null; location?: Location | null; notes?: string | null;
  created_at: string; updated_at: string
}
export type Repair = {
  id: number; machine_id: number; machine: Machine; reported_problem: string; diagnosis?: string | null;
  work_performed?: string | null; result?: string | null; status: string; opened_at: string; closed_at?: string | null
}
export type PartRequest = {
  id: number; machine_id?: number | null; machine?: Machine | null; part_name: string; part_number?: string | null;
  quantity: number; reason?: string | null; priority: string; status: string; created_at: string
}

export type ProtocolDocument = {
  id: number; format: 'docx' | 'pdf' | string; filename: string; download_endpoint: string
}

export type TransferAvailability = {
  machine_id: number; machine_number: string; brand: string; pressure_bar: number; status: string;
  location?: string | null; available: boolean; unavailable_reason?: string | null;
  active_transfer_id?: number | null; protocol_number?: string | null; batch_reference?: string | null;
  issued_at?: string | null; current_recipient_or_location?: string | null
}

export type BulkIssueResult = {
  message: string; batch_id: number; batch_reference: string;
  transfers: Array<{
    transfer_id: number; protocol_number: string; machine_id: number; machine_number: string;
    documents: ProtocolDocument[]
  }>;
  zip_download_endpoint: string
}

export type BatchProgress = {
  batch_id: number; batch_reference: string; status: string; total_machines: number;
  returned_machines: number; still_issued_machines: number; created_at?: string
}

export type BatchDetails = BatchProgress & {
  created_at: string; zip_download_endpoint: string;
  transfers: Array<{
    transfer_id: number; machine_id: number; machine_number: string; machine_name: string; brand: string;
    pressure_bar: number; protocol_number: string; is_active: boolean; issued_at?: string | null;
    returned_at?: string | null; current_status: string; location?: string | null;
    documents: ProtocolDocument[]
  }>
}

export type BulkReturnResult = {
  message: string;
  returned: Array<{ transfer_id: number; machine_id: number; machine_number: string; new_status: string; returned_at: string }>;
  batches: BatchProgress[]
}
