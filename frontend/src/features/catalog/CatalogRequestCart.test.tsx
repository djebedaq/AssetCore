import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { I18nProvider } from '../../i18n'
import { setSessionUser } from '../../permissions'
import { CatalogRequestCart } from './CatalogRequestCart'
import type { CatalogCartLine } from './catalogTypes'
import type { UserSession } from '../../types'

const line: CatalogCartLine = {
  catalog_part_id: 31,
  source_record_key: 'verified-source-row',
  assembly: 'PUMP',
  position: '8',
  part_number: 'SOURCE-PART',
  source_part_number: 'SOURCE-PART',
  description: 'Verified source description',
  quantity: 1,
  source_quantity_raw: '2',
  source_document: 'controlled-source.pdf',
  source_page: 4,
  replacement_applied: false,
}

describe('catalog canonical request submit', () => {
  beforeEach(() => {
    localStorage.clear()
    setSessionUser({ permissions: ['requests.create'] } as UserSession)
  })
  afterEach(() => {
    cleanup()
    vi.unstubAllGlobals()
  })

  it('creates and submits in one API request', async () => {
    const fetchMock = vi.fn(async (_input: RequestInfo | URL, _init?: RequestInit) => new Response(JSON.stringify({
      id: 12,
      request_reference: 'PR-2026-000012',
      status: 'WAITING_APPROVAL',
    }), { status: 201, headers: { 'Content-Type': 'application/json' } }))
    vi.stubGlobal('fetch', fetchMock)
    const onChange = vi.fn()
    render(<I18nProvider initialLocale="bg"><CatalogRequestCart machineId={9} cartMachineId={9} lines={[line]} onChange={onChange} undoAvailable={false} onUndo={vi.fn()} /></I18nProvider>)
    await userEvent.click(screen.getByRole('button', { name: 'Създай заявка' }))
    await userEvent.click(screen.getByRole('button', { name: 'Подай заявката' }))
    await waitFor(() => expect(screen.getByText('PR-2026-000012')).toBeInTheDocument())
    expect(fetchMock).toHaveBeenCalledTimes(1)
    const body = JSON.parse(String(fetchMock.mock.calls[0][1]?.body))
    expect(body.submit_for_approval).toBe(true)
    expect(body.machine_id).toBe(9)
    expect(body.lines).toEqual([expect.objectContaining({ catalog_part_id: 31, quantity: 1 })])
    expect(onChange).toHaveBeenCalledWith([])
  })
})
