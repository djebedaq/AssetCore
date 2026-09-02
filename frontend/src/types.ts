export type Location = { id: number; name: string; description?: string | null; is_active: boolean }
export type Department = {
  id: number; code: string; name_bg: string; name_en?: string | null; name_ru?: string | null;
  description?: string | null; is_active: boolean; created_at: string
}
export type UserRole = 'administrator' | 'director' | 'mechanic' | 'observer'
export type PermissionCode =
  | 'users.view' | 'users.create' | 'users.edit' | 'users.activate' | 'users.deactivate'
  | 'users.reset_password' | 'users.assign_director' | 'users.assign_administrator'
  | 'assets.view' | 'assets.create' | 'assets.edit' | 'assets.change_location'
  | 'transfers.view' | 'transfers.create' | 'transfers.return'
  | 'repairs.view' | 'repairs.create' | 'repairs.edit' | 'repairs.complete'
  | 'requests.view' | 'requests.create' | 'requests.approve'
  | 'parts.view' | 'parts.manage' | 'documents.view' | 'documents.generate'
  | 'templates.manage' | 'audit.view_operational' | 'audit.view_full' | 'settings.manage'
export type UserSession = {
  id: number; email: string; full_name: string; role: UserRole; preferred_language: 'bg' | 'en' | 'ru';
  is_active: boolean; is_system_owner: boolean; must_change_password: boolean;
  first_name?: string | null; middle_name?: string | null; last_name?: string | null;
  job_title?: string | null; department_id?: number | null;
  profile_status?: 'PROFILE_INCOMPLETE' | 'PROFILE_COMPLETE'; legal_name_exception?: boolean;
  legal_name_exception_reason?: string | null; legal_name_exception_approved_by_id?: number | null;
  legal_name_exception_approved_at?: string | null;
  permissions: PermissionCode[]; created_at: string; updated_at: string;
  last_login_at?: string | null; password_changed_at?: string | null; created_by_id?: number | null
}
export type ManagedUser = UserSession

export type LicenseStatus = {
  state: 'NOT_INSTALLED' | 'INVALID' | 'NOT_YET_VALID' | 'ACTIVE' | 'GRACE_PERIOD' | 'READ_ONLY';
  message: string; read_only: boolean; license_id?: string | null; license_type?: string | null;
  client_name?: string | null; installation_id?: string | null; valid_from?: string | null;
  rightsholder?: string | null; valid_until?: string | null; grace_until?: string | null;
  issued_at?: string | null; activated_at?: string | null; support_until?: string | null; checked_at: string;
  modules: string[]; max_users?: number | null; max_assets?: number | null;
  environment?: string | null; allowed_domains: string[]; max_installations?: number | null; version?: number | null
}

export type OwnerStatus = {
  owner_user_id: number; owner_name: string; owner_email: string; role: UserRole;
  designated_at: string; designation_version: number
}

export type EmergencyAccessStatus = {
  active: boolean; session_id?: number | null; started_at?: string | null;
  expires_at?: string | null; owner_name?: string | null; mfa_verified: boolean; message: string
}

export type SigningSummary = {
  document_number: string; document_type: string; document_version: number; document_status: string;
  document_sha256: string; participant: Record<string, unknown>; operation_role: string;
  machine?: { id: number; number: string; name: string; brand: string } | null;
  machines?: Array<{ id: number; number: string; brand: string; model?: string | null; protocol_number: string }>;
  batch_reference?: string | null; batch_manifest_sha256?: string | null;
  operation_description: string; operation_datetime: string;
  consent_notice: string; requires_confirmation: boolean
}

export type ExternalSigner = {
  id: number; first_name: string; middle_name?: string | null; last_name: string;
  job_title: string; company?: string | null; participant_role: string; note?: string | null;
  is_foreign_person?: boolean; name_exception_reason?: string | null;
  is_active: boolean; created_by_id: number; created_at: string; updated_at: string
}

export type SignatureSlot = {
  id: number; document_type: string; code: string;
  label_bg: string; label_en?: string | null; label_ru?: string | null;
  sequence: number; required: boolean; allowed_participant_kind: string; signing_mode: string; is_active: boolean
}

export type SigningTask = {
  participant_id: number; slot_code: string; operation_role: string; signer_name: string;
  signing_token: string; signing_endpoint: string; expires_at: string
}

export type InternalParticipantCandidate = {
  id: number; display_name: string; job_title?: string | null; role: UserRole
}

export type OfficialDocument = {
  id: number; document_number: string; document_type: string; machine_id?: number | null;
  transfer_id?: number | null; batch_id?: number | null; created_at: string;
  current_version: { id: number; version: number; status: string; language: 'bg' | 'en' | 'ru';
    snapshot_sha256: string; docx_sha256?: string | null; pdf_sha256?: string | null;
    correction_reason?: string | null; created_at: string; finalized_at?: string | null };
  signed_count: number; required_count: number;
  participants: Array<{ id: number; slot_code: string; participant_kind: string;
    operation_role: string; identity_snapshot: Record<string, unknown>; signed: boolean;
    signature_id?: number | null }>
}
export type Machine = {
  id: number; inventory_number: string; name: string; category?: string; brand: string;
  model?: string | null; pressure_bar?: number; serial_number?: string | null; status: string;
  location_id?: number | null; location?: Location | null; notes?: string | null;
  created_at: string; updated_at: string
  category_id?: number | null; asset_type?: string | null; subtype?: string | null;
  manufacturer?: string | null; manufacture_year?: number | null; commissioning_date?: string | null;
  ownership?: string | null; department?: string | null; responsible_person?: string | null;
  capacity?: string | null; dimensions?: string | null; is_active?: boolean
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
  id: number; document_number?: string | null; language?: 'bg' | 'en' | 'ru' | string;
  format: 'docx' | 'pdf' | string; filename: string; download_endpoint: string
}

export type TransferAvailability = {
  machine_id: number; machine_number: string; brand: string; pressure_bar: number; status: string;
  status_label?: string;
  location?: string | null; available: boolean; returnable: boolean; operation_status?: string | null;
  unavailable_reason?: string | null;
  active_transfer_id?: number | null; protocol_number?: string | null; batch_reference?: string | null;
  issued_at?: string | null; current_recipient_or_location?: string | null
}

export type BulkIssueResult = {
  message: string; batch_id: number; batch_reference: string;
  batch_manifest_sha256?: string | null; signing_document_id?: number | null; signing_tasks: SigningTask[];
  transfers: Array<{
    transfer_id: number; protocol_number: string; machine_id: number; machine_number: string;
    workflow_status: string; official_document_id: number; signing_tasks: SigningTask[];
    documents: ProtocolDocument[]
  }>;
  zip_download_endpoint: string
}

export type BatchProgress = {
  batch_id: number; batch_reference: string; status: string; total_machines: number;
  returned_machines: number; still_issued_machines: number; awaiting_signature_machines: number;
  machine_numbers: string[]; created_at?: string
}

export type CancelTransferBatchResponse = {
  batch_id: number; batch_reference: string; status: string; cancelled_transfers: number;
  invalidated_signing_sessions: number; message: string
}

export type BatchDetails = BatchProgress & {
  created_at: string; operation?: 'ISSUE' | 'RETURN' | string;
  batch_manifest_sha256?: string | null; signing_document_id?: number | null;
  zip_download_endpoint: string;
  transfers: Array<{
    transfer_id: number; machine_id: number; machine_number: string; machine_name: string; brand: string;
    pressure_bar: number; protocol_number: string; is_active: boolean; issue_status: string; return_status?: string | null; issued_at?: string | null;
    returned_at?: string | null; current_status: string; location?: string | null;
    documents: ProtocolDocument[]; issue_documents: ProtocolDocument[]; return_documents: ProtocolDocument[]
  }>
}

export type BulkReturnResult = {
  message: string; batch_id: number; batch_reference: string;
  batch_manifest_sha256?: string | null; signing_document_id?: number | null; signing_tasks: SigningTask[];
  returned: Array<{ transfer_id: number; machine_id: number; machine_number: string; new_status: string; returned_at?: string | null; workflow_status: string; official_document_id: number; signing_tasks: SigningTask[]; documents: ProtocolDocument[] }>;
  batches: BatchProgress[]
}

export type AssetCategoryField = {
  id: number; category_id: number; code: string; label_bg: string; label_en?: string | null;
  label_ru?: string | null; field_type: string; is_required: boolean; options?: string[] | null;
  unit?: string | null; validation_rules?: Record<string, unknown> | null; sort_order: number; is_active: boolean
}

export type AssetCategory = {
  id: number; code: string; name_bg: string; name_en?: string | null; name_ru?: string | null;
  description?: string | null; icon?: string | null; validation_rules?: Record<string, unknown> | null;
  document_types?: string[] | null; checklists?: Array<Record<string, unknown>> | null; status_codes?: string[] | null;
  is_active: boolean; created_at: string; fields: AssetCategoryField[]
}

export type StoredAttachment = {
  id: number; filename: string; media_type: string; sha256: string; created_at: string; request_line_id?: number | null;
  description?: string | null; caption?: string | null; kind?: string | null; stage?: string | null;
  download_endpoint: string
}

export type MachinePassport = {
  limited_view?: boolean;
  machine: Machine & { category_definition?: AssetCategory | null };
  custom_fields: Array<AssetCategoryField & { field_id: number; value?: string | null }>;
  attachments: StoredAttachment[];
  history: Array<{ id: number; event_type: string; reference?: string | null; previous_status?: string | null; new_status?: string | null; details?: Record<string, unknown> | null; user_id?: number | null; created_at: string }>;
  repairs: Array<{ id: number; repair_reference?: string | null; status: string; reported_problem: string; opened_at: string; closed_at?: string | null }>;
  transfers: Array<{ id: number; protocol_number: string; batch_reference?: string | null; is_active: boolean; issued_at?: string | null; returned_at?: string | null; location_text?: string | null; accepted_by?: string | null }>;
  part_requests: Array<{ id: number; request_reference?: string | null; status: string; priority: string; created_at: string }>;
  parts_used: Array<{ id: number; repair_id: number; repair_reference?: string | null; catalog_part_id?: number | null; part_number?: string | null; description: string; quantity: number; unit?: string | null; source?: string | null; created_at: string }>;
  generated_documents: Array<{ id: number; document_number: string; document_type: string; format: string; filename: string; created_at: string; download_endpoint: string }>;
  technical_documents: TechnicalLibraryDocument[];
  current_state: {
    available: boolean;
    active_transfer?: { id: number; protocol_number: string; batch_reference?: string | null; issued_at?: string | null;
      company_unit?: string | null; department?: string | null; vessel?: string | null; dock?: string | null;
      pier?: string | null; work_area?: string | null; location_text?: string | null; accepted_by?: string | null } | null;
    active_repair?: { id: number; repair_reference?: string | null; status: string; reported_problem: string; opened_at: string } | null;
    last_movement?: { event_type: string; reference?: string | null; created_at: string } | null;
    last_inspection?: { repair_reference?: string | null; completed_at: string } | null;
    last_test?: { repair_reference?: string | null; passed?: boolean | null; details?: string | null; completed_at?: string | null } | null;
    allowed_actions: { issue: boolean; return: boolean; repair: boolean; edit: boolean };
  };
  audit_visible: boolean;
  audit: Array<{ id: number; entity_type: string; entity_id?: number | null; action: string; details?: string | null; user_name?: string | null; operation_reference?: string | null; created_at: string }>;
  qr_endpoint?: string | null
}

export type RepairEvent = {
  id: number; event_type: string; status_before?: string | null; status_after?: string | null;
  description?: string | null; structured_data?: Record<string, unknown> | null; user_id: number; created_at: string
}

export type RepairPartUsed = {
  id: number; repair_id: number; catalog_part_id?: number | null; part_number?: string | null;
  description: string; quantity: number; unit?: string | null; source?: string | null;
  created_by_id: number; created_at: string
}

export type RepairParticipant = {
  id: number; repair_id: number; user_id?: number | null; full_name: string;
  job_title?: string | null; contribution?: string | null; minutes_worked?: number | null;
  created_by_id: number; created_at: string
}

export type RepairCase = {
  id: number; repair_reference?: string | null; machine_id: number; machine_number: string; machine_name: string;
  reported_problem: string; diagnosis?: string | null; work_performed?: string | null; result?: string | null;
  status: string; repair_type?: string | null; severity?: string | null; condition_before?: string | null;
  condition_after?: string | null; reported_by_name?: string | null; symptoms?: string | null;
  required_work?: string | null; required_parts_text?: string | null; removed_parts_text?: string | null;
  diagnostic_cleaning?: string | null;
  diagnosis_minutes?: number | null; repair_minutes?: number | null; testing_minutes?: number | null; total_work_minutes: number;
  participant_total_minutes: number;
  cleaning_required: boolean; cleaning_completed_at?: string | null;
  inspection_completed_at?: string | null; test_required: boolean; test_passed?: boolean | null;
  test_details?: string | null; test_method?: string | null; test_pressure_bar?: number | null; leaks_detected?: boolean | null;
  electrical_test_result?: string | null; functional_test_result?: string | null; responsible_user_id?: number | null;
  responsible_user?: { id: number; full_name: string; job_title?: string | null } | null; participants: RepairParticipant[];
  document_generation_warning?: { code: string; message: string; document_type?: string; language?: string } | null; accepted_by_id?: number | null;
  accepted_by?: { id: number; full_name: string; job_title?: string | null } | null;
  approved_by_id?: number | null; approved_by?: { id: number; full_name: string; job_title?: string | null } | null;
  approved_at?: string | null; target_date?: string | null;
  opened_at: string; started_at?: string | null; closed_at?: string | null; events: RepairEvent[]; parts_used: RepairPartUsed[];
  attachments: StoredAttachment[];
  generated_documents: Array<{ id: number; document_number: string; document_type: string; format: string; filename: string; created_at: string; download_endpoint: string }>
}

export type MultiPartRequestLine = {
  id: number; request_id: number; catalog_part_id?: number | null; position?: string | null;
  part_number?: string | null; description: string; quantity: number; unit?: string | null;
  reason?: string | null; source_document?: string | null; source_page?: number | null; delivered_quantity: number;
  is_unknown_part?: boolean; assembly?: string | null; note?: string | null;
  linked_catalog_part_id?: number | null; linked_part_number?: string | null; linked_part_description?: string | null;
  linked_by_id?: number | null; linked_at?: string | null; link_note?: string | null
}

export type PartRequestQuantityCompatibility = {
  status: 'COMPATIBLE' | 'LEGACY_FRACTIONAL';
  affected_line_ids: number[];
  recovery_action: 'NONE' | 'CREATE_REPLACEMENT' | 'REJECT_AND_RECREATE' | 'CANCEL_AND_RECREATE' | 'HISTORICAL_ONLY';
  affected_lines?: Array<{ line_id: number; quantity: number; delivered_quantity: number }>
}

export type MultiPartRequest = {
  id: number; request_reference: string; machine_id?: number | null; machine_number?: string | null;
  repair_id?: number | null; repair_reference?: string | null;
  repair_kit_id?: number | null; repair_kit_mode?: 'COMPONENTS' | 'KIT' | null;
  priority: string; status: string; language: 'bg' | 'en' | 'ru'; reason?: string | null;
  department?: string | null; supplier?: string | null; delivery_note?: string | null;
  ordered_at?: string | null; delivered_at?: string | null;
  requested_by_id?: number | null; requested_by_name?: string | null; submitted_at?: string | null; decided_at?: string | null;
  decided_by_name?: string | null;
  decision_note?: string | null; created_at: string; lines: MultiPartRequestLine[];
  quantity_compatibility: PartRequestQuantityCompatibility;
  approvals: Array<{ id: number; decision: string; note?: string | null; decided_by_id: number; decided_by_name?: string | null; decided_at: string }>;
  attachments: StoredAttachment[];
  documents: ProtocolDocument[]
}

export type CatalogPartEnhanced = {
  id: number; brand: string; model?: string | null; manufacturer?: string | null; assembly?: string | null;
  category?: string | null; name_bg?: string | null; name_en?: string | null; name_ru?: string | null; original_name?: string | null;
  position?: string | null; part_number: string; description: string; quantity?: number | null; unit?: string | null;
  technical_specification?: string | null; compatible_models?: string | null; alternative_part_number?: string | null;
  alternative_part_numbers?: string[] | null; replacement_part_ids?: number[] | null;
  compatible_machine_numbers?: string[] | null; technical_notes?: string | null; supplier?: string | null;
  supplier_code?: string | null; estimated_price?: number | null; currency?: string | null; lead_time_days?: number | null;
  revision?: string | null; is_active?: boolean;
  source_document?: string | null; source_page?: number | null; source_figure?: string | null; diagram_page?: number | null;
  source_version?: string | null; source_document_sha256?: string | null; verification_status?: string | null;
  replaced_by_part_number?: string | null; source_excerpt?: string | null;
  provenance_confidence?: number | null; is_verified: boolean; verified_at?: string | null
}

export type PartHotspot = {
  id: number; part_id: number; technical_document_id?: number | null; page_number: number;
  x: number; y: number; width: number; height: number; label?: string | null;
  provenance?: string | null; confidence?: number | null; is_verified: boolean; created_by_id: number; created_at: string
}

export type CatalogPartImage = {
  id: number; filename: string; media_type: string; sha256: string;
  caption?: string | null; created_at: string; download_endpoint: string
}

export type TechnicalLibraryDocument = {
  id: number; brand: string; model?: string | null; category: string; title: string; document_type: string;
  language?: string | null; revision?: string | null; sha256?: string | null; created_at?: string | null;
  source_label?: string | null; document_date?: string | null; tags?: string[] | null; page_count?: number | null;
  notes?: string | null; linked_machine_numbers?: string[] | null; source_key?: string | null;
  download_endpoint: string; page_preview_endpoint?: string | null; revisions: Array<{ id: number; version: number; revision_label?: string | null;
    filename: string; sha256: string; change_note?: string | null; created_at: string; download_endpoint: string }>
}

export type RepairKit = {
  id: number; code: string; name: string; brand?: string | null; model?: string | null; compatible_models?: string | null; revision?: string | null; assembly?: string | null;
  source_document?: string | null; source_page?: number | null; provenance?: string | null; confidence?: number | null;
  is_approved: boolean; approved_by_id?: number | null; approved_at?: string | null; created_at: string;
  components: Array<{ id: number; part_id: number; part_number: string; description: string; quantity: number; is_optional: boolean; note?: string | null; alternative_part_numbers?: string[] | null; replacement_part_ids?: number[] | null }>
}

export type GlobalSearchResults = {
  query: string;
  machines: Array<{ id: number; inventory_number: string; name: string; brand: string; model?: string | null; serial_number?: string | null; status: string }>;
  parts: Array<{ id: number; part_number: string; description: string; brand: string; model?: string | null; assembly?: string | null; is_verified: boolean }>;
  documents: Array<{ id: number; title: string; brand: string; category: string; download_endpoint: string }>;
  repairs: Array<{ id: number; repair_reference?: string | null; machine_number: string; reported_problem: string; status: string }>;
  part_requests: Array<{ id: number; request_reference?: string | null; status: string; part_name: string }>
  transfers: Array<{ id: number; protocol_number: string; batch_reference?: string | null; machine_number: string; company_unit?: string | null; vessel?: string | null; location_text?: string | null; is_active: boolean }>;
  generated_documents: Array<{ id: number; document_number: string; document_type: string; format: string; filename: string; download_endpoint: string }>
}
