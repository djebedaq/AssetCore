// Isolated test-only payload, never a seed or production business record.
import type { MachinePassport } from '../../types'

export const passport: MachinePassport = {
  limited_view: false,
  machine: {
    id: 13, inventory_number: '13', name: 'Test-only machine', brand: 'Falch', model: 'Test model', pressure_bar: 500,
    serial_number: 'TEST-SERIAL', status: 'REPAIR', location_id: 1, location: { id: 1, name: 'Test workshop', is_active: true },
    category: 'HPWJ', category_definition: { id: 1, code: 'HPWJ', name_bg: 'Водоструйни машини', name_en: 'Water-jet machines', name_ru: 'Водоструйные машины', is_active: true, created_at: '2026-09-01T00:00:00Z', fields: [] },
    notes: null, asset_type: 'Test asset', subtype: 'Test subtype', manufacturer: 'Test manufacturer', manufacture_year: 2024,
    commissioning_date: '2025-01-02T00:00:00Z', ownership: 'Test ownership', department: 'Test department', responsible_person: 'Test owner',
    capacity: 'Test capacity', dimensions: 'Test dimensions', is_active: true, created_at: '2026-09-01T00:00:00Z', updated_at: '2026-09-01T00:00:00Z',
  },
  custom_fields: [{ id: 1, category_id: 1, code: 'test_field', label_bg: 'Тестово поле', label_en: 'Test field', label_ru: 'Тестовое поле', field_type: 'TEXT', is_required: true, sort_order: 1, is_active: true, field_id: 1, value: 'Test value' }],
  attachments: [{ id: 1, filename: 'test-photo.jpg', media_type: 'image/jpeg', sha256: 'a'.repeat(64), created_at: '2026-09-03T09:00:00Z', download_endpoint: '/machine-attachments/1/download' }],
  history: [{ id: 1, event_type: 'TRANSFER_ISSUED', reference: 'TEST-EVENT', previous_status: 'READY', new_status: 'ISSUED', created_at: '2026-09-01T08:00:00Z' }],
  repairs: [{ id: 3, repair_reference: 'TEST-REPAIR-ACTIVE-LONG-REFERENCE-123456789', status: 'DIAGNOSIS', reported_problem: 'Test-only reported problem', opened_at: '2026-09-03T08:00:00Z' }],
  transfers: [{ id: 2, protocol_number: 'TEST-TRANSFER-LONG-REFERENCE-123456789', batch_reference: 'TEST-BATCH', is_active: true, issued_at: '2026-09-03T07:00:00Z', location_text: 'Test location', accepted_by: 'Test recipient' }],
  part_requests: [{ id: 4, request_reference: 'TEST-REQUEST-001', status: 'ORDERED', priority: 'URGENT', created_at: '2026-09-03T06:00:00Z' }],
  parts_used: [{ id: 5, repair_id: 2, repair_reference: 'TEST-REPAIR-COMPLETE', part_number: 'TEST-PART', description: 'Test used part', quantity: 4, unit: 'бр.', source: 'Test source', created_at: '2026-09-02T06:00:00Z' }],
  generated_documents: [{ id: 6, document_number: 'TEST-LEGACY-OTHER', document_type: 'OTHER', format: 'pdf', filename: 'test-other.pdf', created_at: '2026-09-02T05:00:00Z', download_endpoint: '/generated-documents/6/download', display_separately: true }],
  official_documents: [{
    category: 'transfers', registry_key: 'transfer:2', domain_id: 2, machine_id: 13, machine_number: '13', status: 'INCOMPLETE', signature_status: 'SIGNED', started_at: '2026-09-03T07:00:00Z',
    documents: [{ document_type: 'TRANSFER_ISSUE', document_number: 'TEST-OFFICIAL-ISSUE', official_document_id: 7, version: 1, version_status: 'FINALIZED', files: [
      { format: 'docx', download_endpoint: '/official-documents/7/versions/1/download/docx' },
      { format: 'pdf', download_endpoint: '/official-documents/7/versions/1/download/pdf', preview_endpoint: '/official-documents/7/preview/pdf' },
    ] }],
  }],
  technical_documents: [{ id: 8, brand: 'Test', category: 'HPWJ', title: 'Test manual', document_type: 'TECHNICAL', language: 'bg', revision: 'R1', sha256: 'b'.repeat(64), created_at: '2026-09-01T00:00:00Z', source_label: 'Test source', document_date: '2026-09-01', linked_machine_numbers: ['13'], download_endpoint: '/technical-library/8/download', revisions: [{ id: 9, version: 2, revision_label: 'R2', filename: 'test-manual-r2.pdf', sha256: 'c'.repeat(64), created_at: '2026-09-02T00:00:00Z', download_endpoint: '/technical-library/revisions/9/download' }] }],
  current_state: {
    available: false,
    active_transfer: { id: 2, protocol_number: 'TEST-TRANSFER-LONG-REFERENCE-123456789', batch_reference: 'TEST-BATCH', issued_at: '2026-09-03T07:00:00Z', company_unit: 'Test unit', department: 'Test department', vessel: 'Test vessel', dock: 'Test dock', location_text: 'Test location' },
    active_repair: { id: 3, repair_reference: 'TEST-REPAIR-ACTIVE-LONG-REFERENCE-123456789', status: 'DIAGNOSIS', reported_problem: 'Test-only reported problem', opened_at: '2026-09-03T08:00:00Z' },
    last_completed_repair: { id: 2, repair_reference: 'TEST-REPAIR-COMPLETE', status: 'COMPLETED', opened_at: '2026-08-30T08:00:00Z', closed_at: '2026-09-02T08:00:00Z', test_passed: true },
    last_transfer: { id: 2, protocol_number: 'TEST-TRANSFER-LONG-REFERENCE-123456789', batch_reference: 'TEST-BATCH', is_active: true, issued_at: '2026-09-03T07:00:00Z', location_text: 'Test location' },
    pending_part_requests: { count: 1, latest_request_reference: 'TEST-REQUEST-001' },
    last_movement: { event_type: 'TRANSFER_ISSUED', reference: 'TEST-EVENT', created_at: '2026-09-03T07:00:00Z' },
    last_inspection: { repair_reference: 'TEST-REPAIR-COMPLETE', completed_at: '2026-09-02T07:00:00Z' },
    last_test: { repair_reference: 'TEST-REPAIR-COMPLETE', passed: true, completed_at: '2026-09-02T08:00:00Z' },
    allowed_actions: { issue: false, return: true, repair: false, edit: true },
  },
  audit_visible: true,
  audit: [{ id: 10, entity_type: 'machine', entity_id: 13, action: 'TEST_AUDIT', user_name: 'Test user', created_at: '2026-09-03T10:00:00Z' }],
  qr_endpoint: '/machines/13/qr',
}
