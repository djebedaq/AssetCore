import { act, cleanup, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { I18nProvider } from '../../i18n'
import { PendingPartsBadge } from './PendingPartsBadge'
import { notifyPartRequestsChanged } from './partRequestEvents'

function response(count: number) {
  return new Response(JSON.stringify({ pending_action_count: count }), {
    status: 200,
    headers: { 'Content-Type': 'application/json' },
  })
}

describe('permission-aware requested-parts badge', () => {
  afterEach(() => {
    cleanup()
    vi.unstubAllGlobals()
  })

  it('uses the canonical count, does not clear on view, and revalidates after actions', async () => {
    let count = 2
    const fetchMock = vi.fn(async () => response(count))
    vi.stubGlobal('fetch', fetchMock)
    const view = render(<I18nProvider initialLocale="bg"><PendingPartsBadge canApprove revalidationKey="dashboard" /></I18nProvider>)
    expect(await screen.findByText('2')).toHaveAccessibleName('Заявки, изискващи Вашето решение: 2')

    view.rerender(<I18nProvider initialLocale="bg"><PendingPartsBadge canApprove revalidationKey="parts" /></I18nProvider>)
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2))
    expect(screen.getByText('2')).toBeInTheDocument()

    count = 1
    act(() => notifyPartRequestsChanged())
    expect(await screen.findByText('1')).toBeInTheDocument()
    count = 0
    act(() => notifyPartRequestsChanged())
    await waitFor(() => expect(screen.queryByText('1')).not.toBeInTheDocument())
  })

  it('does not fetch or show an action count without approval permission', () => {
    const fetchMock = vi.fn()
    vi.stubGlobal('fetch', fetchMock)
    render(<I18nProvider initialLocale="bg"><PendingPartsBadge canApprove={false} revalidationKey="parts" /></I18nProvider>)
    expect(fetchMock).not.toHaveBeenCalled()
    expect(screen.queryByText(/\d/)).not.toBeInTheDocument()
  })
})
