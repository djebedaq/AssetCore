import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { I18nProvider } from '../../i18n'
import { clearSessionUser, setSessionUser } from '../../permissions'
import type { MultiPartRequest, UserSession } from '../../types'
import { RequestDeliveryHistory } from './RequestExecutionModals'

afterEach(() => { cleanup(); clearSessionUser() })

it.each(['PARTIALLY_DELIVERED', 'CANCELLED'])('shows reversal only for an active request: %s', status => {
  setSessionUser({ id: 7, role: 'mechanic', permissions: ['requests.create'] } as UserSession)
  const request: MultiPartRequest = {
    id: 1, status, request_reference: 'QA', priority: 'NORMAL', language: 'bg',
    created_at: '2026-10-16T10:00:00Z', approvals: [], attachments: [], documents: [],
    quantity_compatibility: { status: 'COMPATIBLE', affected_line_ids: [], recovery_action: 'NONE' },
    lines: [{ id: 1, request_id: 1, description: 'QA material', quantity: 2, delivered_quantity: 0 }],
    delivery_events: [{ id: 1, kind: 'RECEIPT', quantities: { '1': '1' }, actor_id: 7, actor_name: 'QA', occurred_at: '2026-10-16T10:00:00Z' }],
  }
  render(<I18nProvider initialLocale="bg"><RequestDeliveryHistory request={request} onSaved={vi.fn()} /></I18nProvider>)
  expect(screen.queryAllByRole('button', { hidden: true })).toHaveLength(status === 'CANCELLED' ? 0 : 1)
  expect(screen.getByText('QA material: 1')).toBeInTheDocument()
})
