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
