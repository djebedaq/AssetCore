import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { I18nProvider } from '../../i18n'
import type { Locale } from '../../locale'
import OfficialDocuments from './OfficialDocuments'
import type {
  OfficialRegistryCategory,
  OfficialRegistryItem,
  OfficialRegistryPage,
} from './types'

function json(value: unknown, status = 200): Response {
  return new Response(JSON.stringify(value), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

function registryItem(
  registryKey: string,
  documentNumber: string,
  documentType: 'TRANSFER_ISSUE' | 'TRANSFER_RETURN' | 'REPAIR_PROTOCOL' | 'PART_REQUEST',
  overrides: Partial<OfficialRegistryItem> = {},
): OfficialRegistryItem {
  return {
    registry_key: registryKey,
    domain_id: Number(registryKey.replace(/\D/g, '')) || 1,
    machine_number: String(Number(registryKey.replace(/\D/g, '')) || 1),
    status: documentType === 'TRANSFER_ISSUE' || documentType === 'TRANSFER_RETURN' ? 'INCOMPLETE' : 'COMPLETED',
    signature_status: 'SIGNED',
    created_at: '2026-08-24T12:00:00Z',
    documents: [{
      document_type: documentType,
      document_number: documentNumber,
      official_document_id: Number(registryKey.replace(/\D/g, '')) || 1,
      version: 1,
      version_status: 'SIGNED',
      files: [
        { format: 'docx', download_endpoint: `/${registryKey}.docx` },
        { format: 'pdf', download_endpoint: `/${registryKey}.pdf`, preview_endpoint: `/${registryKey}-preview.pdf` },
      ],
    }],
    ...overrides,
  }
}

function registryPage(
  category: OfficialRegistryCategory,
  items: OfficialRegistryItem[],
  overrides: Partial<OfficialRegistryPage> = {},
): OfficialRegistryPage {
  return {
    category,
    total: items.length,
    count: items.length,
    page: 1,
    page_size: 25,
    total_pages: items.length ? 1 : 0,
    has_previous: false,
    has_next: false,
    items,
    ...overrides,
  }
}

function renderOfficialDocuments(locale: Locale = 'bg') {
  return render(<I18nProvider initialLocale={locale}><OfficialDocuments /></I18nProvider>)
}

function urls(fetchMock: ReturnType<typeof vi.fn>): string[] {
  return fetchMock.mock.calls.map((call) => String(call[0]))
}

function expectNoMassRegistryRequest(fetchMock: ReturnType<typeof vi.fn>) {
  expect(urls(fetchMock)).not.toContain('/api/official-documents/registry')
}

function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((promiseResolve) => { resolve = promiseResolve })
  return { promise, resolve }
}

describe('OfficialDocuments category registry screen', () => {
  beforeEach(() => {
    class TestURL extends URL {
      static createObjectURL = vi.fn(() => 'blob:authenticated-official-preview')
      static revokeObjectURL = vi.fn()
    }
    vi.stubGlobal('URL', TestURL)
  })

  afterEach(() => {
    cleanup()
    vi.unstubAllGlobals()
  })

  it('loads counts only and renders exactly three truthful keyboard-accessible category cards', async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => String(input).endsWith('/registry/counts')
      ? json({ transfers: 84, repairs: 0, parts: 12 })
      : json(registryPage('transfers', [])))
    vi.stubGlobal('fetch', fetchMock)
    const user = userEvent.setup()
    const { container } = renderOfficialDocuments()

    const transfer = await screen.findByRole('button', { name: 'Отвори Приемане / предаване — документи: 84' })
    expect(screen.getByRole('button', { name: 'Отвори Ремонти — документи: 0' })).toBeVisible()
    expect(screen.getByRole('button', { name: 'Отвори Заявени части — документи: 12' })).toBeVisible()
    expect(container.querySelectorAll('.official-category-card')).toHaveLength(3)
    expect(container.querySelector('.official-registry-table')).toBeNull()
    expect(urls(fetchMock)).toEqual(['/api/official-documents/registry/counts'])
    expectNoMassRegistryRequest(fetchMock)

    transfer.focus()
    await user.keyboard('{Enter}')
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2))
    expect(urls(fetchMock)[1]).toBe('/api/official-documents/registry/items?category=transfers&page=1&page_size=25')
    expect(await screen.findByText('Няма създадени протоколи за приемане / предаване.')).toBeVisible()
  })

  it.each([
    ['transfers', 'Приемане / предаване', 'TR-QA-001', 'TRANSFER_ISSUE'],
    ['repairs', 'Ремонти', 'REP-QA-001', 'REPAIR_PROTOCOL'],
    ['parts', 'Заявени части', 'PR-QA-001', 'PART_REQUEST'],
  ] as const)('enters only the %s category with the exact first-page request', async (category, title, number, documentType) => {
    const item = registryItem(`${category}:1`, number, documentType)
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input)
      if (url.endsWith('/registry/counts')) return json({ transfers: 1, repairs: 1, parts: 1 })
      return json(registryPage(category, [item]))
    })
    vi.stubGlobal('fetch', fetchMock)
    renderOfficialDocuments()

    await userEvent.click(await screen.findByRole('button', { name: new RegExp(`^Отвори ${title}`) }))
    expect(await screen.findByText(number)).toBeVisible()
    expect(screen.getByRole('heading', { name: title })).toBeVisible()
    expect(urls(fetchMock)[1]).toBe(`/api/official-documents/registry/items?category=${category}&page=1&page_size=25`)
    expect(screen.queryByText(category === 'transfers' ? 'REP-QA-001' : 'TR-QA-001')).not.toBeInTheDocument()
    expectNoMassRegistryRequest(fetchMock)
  })

  it('returns to cached landing counts and clears selected category state without a mass request', async () => {
    const item = registryItem('repair:7', 'REP-QA-007', 'REPAIR_PROTOCOL')
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => String(input).endsWith('/registry/counts')
      ? json({ transfers: 2, repairs: 1, parts: 3 })
      : json(registryPage('repairs', [item])))
    vi.stubGlobal('fetch', fetchMock)
    renderOfficialDocuments()

    await userEvent.click(await screen.findByRole('button', { name: /^Отвори Ремонти/ }))
    expect(await screen.findByText('REP-QA-007')).toBeVisible()
    await userEvent.click(screen.getByRole('button', { name: 'Всички категории' }))

    expect(screen.queryByText('REP-QA-007')).not.toBeInTheDocument()
    expect(screen.getAllByRole('button', { name: /^Отвори / })).toHaveLength(3)
    expect(fetchMock).toHaveBeenCalledTimes(2)
    expectNoMassRegistryRequest(fetchMock)
  })

  it('runs a category-scoped, encoded search only on submit and clears back to unfiltered page one', async () => {
    const initial = registryItem('transfer:1', 'TR-INITIAL', 'TRANSFER_ISSUE')
    const filtered = registryItem('transfer:2', 'TR-FILTERED', 'TRANSFER_ISSUE')
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input)
      if (url.endsWith('/registry/counts')) return json({ transfers: 2, repairs: 0, parts: 0 })
      const query = new URL(url, 'http://assetcore.local').searchParams.get('q')
      return json(registryPage('transfers', query ? [filtered] : [initial], { total: query ? 1 : 2 }))
    })
    vi.stubGlobal('fetch', fetchMock)
    renderOfficialDocuments()

    await userEvent.click(await screen.findByRole('button', { name: /^Отвори Приемане/ }))
    expect(await screen.findByText('TR-INITIAL')).toBeVisible()
    const search = screen.getByLabelText('Търсене в избраната категория')
    await userEvent.type(search, 'QA 17/+')
    expect(fetchMock).toHaveBeenCalledTimes(2)
    fireEvent.submit(screen.getByRole('search'))

    expect(await screen.findByText('TR-FILTERED')).toBeVisible()
    expect(screen.queryByText('TR-INITIAL')).not.toBeInTheDocument()
    expect(urls(fetchMock)[2]).toContain('category=transfers&page=1&page_size=25&q=QA+17%2F%2B')

    await userEvent.click(screen.getByRole('button', { name: 'Изчисти търсенето' }))
    expect(await screen.findByText('TR-INITIAL')).toBeVisible()
    expect(search).toHaveValue('')
    expect(urls(fetchMock)[3]).toBe('/api/official-documents/registry/items?category=transfers&page=1&page_size=25')
    expectNoMassRegistryRequest(fetchMock)
  })

  it('treats whitespace-only search as an unfiltered page-one request', async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => String(input).endsWith('/registry/counts')
      ? json({ transfers: 0, repairs: 1, parts: 0 })
      : json(registryPage('repairs', [])))
    vi.stubGlobal('fetch', fetchMock)
    renderOfficialDocuments()

    await userEvent.click(await screen.findByRole('button', { name: /^Отвори Ремонти/ }))
    await screen.findByText('Няма създадени ремонтни протоколи.')
    await userEvent.type(screen.getByLabelText('Търсене в избраната категория'), '   {Enter}')
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(3))
    expect(urls(fetchMock)[2]).toBe('/api/official-documents/registry/items?category=repairs&page=1&page_size=25')
    expect(screen.queryByRole('button', { name: 'Изчисти търсенето' })).not.toBeInTheDocument()
  })

  it('distinguishes an empty category from an empty search result and offers search clearing', async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => String(input).endsWith('/registry/counts')
      ? json({ transfers: 0, repairs: 4, parts: 0 })
      : json(registryPage('repairs', [])))
    vi.stubGlobal('fetch', fetchMock)
    renderOfficialDocuments()

    await userEvent.click(await screen.findByRole('button', { name: /^Отвори Ремонти/ }))
    expect(await screen.findByText('Няма създадени ремонтни протоколи.')).toBeVisible()
    await userEvent.type(screen.getByLabelText('Търсене в избраната категория'), 'REP-NONE{Enter}')
    expect(await screen.findByText('Няма документи, отговарящи на търсенето.')).toBeVisible()
    expect(screen.queryByText('Няма създадени ремонтни протоколи.')).not.toBeInTheDocument()
    expect(screen.getAllByRole('button', { name: 'Изчисти търсенето' }).length).toBeGreaterThan(0)
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })

  it('appends the next page with the same query, deduplicates registry keys, and stops at the end', async () => {
    const first = registryItem('part:1', 'PR-QA-001', 'PART_REQUEST')
    const second = registryItem('part:2', 'PR-QA-002', 'PART_REQUEST')
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input)
      if (url.endsWith('/registry/counts')) return json({ transfers: 0, repairs: 0, parts: 2 })
      const params = new URL(url, 'http://assetcore.local').searchParams
      if (!params.get('q')) return json(registryPage('parts', [first]))
      if (params.get('page') === '1') return json(registryPage('parts', [first], { total: 2, has_next: true, total_pages: 2 }))
      return json(registryPage('parts', [first, second], { total: 2, count: 2, page: 2, has_previous: true }))
    })
    vi.stubGlobal('fetch', fetchMock)
    renderOfficialDocuments()

    await userEvent.click(await screen.findByRole('button', { name: /^Отвори Заявени части/ }))
    await screen.findByText('PR-QA-001')
    await userEvent.type(screen.getByLabelText('Търсене в избраната категория'), 'PR QA{Enter}')
    await screen.findByText('Показани 1 от 2')
    await userEvent.click(screen.getByRole('button', { name: 'Покажи още' }))

    expect(await screen.findByText('PR-QA-002')).toBeVisible()
    expect(screen.getAllByText('PR-QA-001')).toHaveLength(1)
    expect(screen.getByText('Показани 2 от 2')).toBeVisible()
    expect(screen.queryByRole('button', { name: 'Покажи още' })).not.toBeInTheDocument()
    expect(urls(fetchMock).at(-1)).toContain('category=parts&page=2&page_size=25&q=PR+QA')
  })

  it('keeps loaded rows after a load-more failure and retries only the failed page', async () => {
    const first = registryItem('transfer:1', 'TR-QA-001', 'TRANSFER_ISSUE')
    const second = registryItem('transfer:2', 'TR-QA-002', 'TRANSFER_ISSUE')
    let secondPageAttempts = 0
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input)
      if (url.endsWith('/registry/counts')) return json({ transfers: 2, repairs: 0, parts: 0 })
      const pageNumber = new URL(url, 'http://assetcore.local').searchParams.get('page')
      if (pageNumber === '1') return json(registryPage('transfers', [first], { total: 2, has_next: true, total_pages: 2 }))
      secondPageAttempts += 1
      if (secondPageAttempts === 1) throw new Error('temporary paging failure')
      return json(registryPage('transfers', [second], { total: 2, page: 2, has_previous: true }))
    })
    vi.stubGlobal('fetch', fetchMock)
    renderOfficialDocuments()

    await userEvent.click(await screen.findByRole('button', { name: /^Отвори Приемане/ }))
    await screen.findByText('TR-QA-001')
    await userEvent.click(screen.getByRole('button', { name: 'Покажи още' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Следващата страница не може да бъде заредена.')
    expect(screen.getByText('TR-QA-001')).toBeVisible()

    await userEvent.click(screen.getByRole('button', { name: 'Опитай отново' }))
    expect(await screen.findByText('TR-QA-002')).toBeVisible()
    expect(screen.getByText('TR-QA-001')).toBeVisible()
    expect(secondPageAttempts).toBe(2)
  })

  it('does not show fake zero counts on failure and can retry the landing request', async () => {
    let attempts = 0
    const fetchMock = vi.fn(async () => {
      attempts += 1
      if (attempts === 1) throw new Error('counts unavailable')
      return json({ transfers: 5, repairs: 6, parts: 7 })
    })
    vi.stubGlobal('fetch', fetchMock)
    renderOfficialDocuments()

    expect(await screen.findByRole('alert')).toHaveTextContent('Броят на официалните документи не може да бъде зареден.')
    expect(screen.queryByRole('button', { name: /^Отвори / })).not.toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Опитай отново' }))
    expect(await screen.findByRole('button', { name: 'Отвори Ремонти — документи: 6' })).toBeVisible()
  })

  it('keeps a failed category selected with retry and reachable back navigation', async () => {
    let itemAttempts = 0
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      if (String(input).endsWith('/registry/counts')) return json({ transfers: 0, repairs: 1, parts: 0 })
      itemAttempts += 1
      if (itemAttempts === 1) throw new Error('category unavailable')
      return json(registryPage('repairs', [registryItem('repair:1', 'REP-QA-001', 'REPAIR_PROTOCOL')]))
    })
    vi.stubGlobal('fetch', fetchMock)
    renderOfficialDocuments()

    await userEvent.click(await screen.findByRole('button', { name: /^Отвори Ремонти/ }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Документите в избраната категория не могат да бъдат заредени.')
    expect(screen.getByRole('button', { name: 'Всички категории' })).toBeVisible()
    await userEvent.click(screen.getByRole('button', { name: 'Опитай отново' }))
    expect(await screen.findByText('REP-QA-001')).toBeVisible()
  })

  it('invalidates an in-flight category response when the user returns to the landing', async () => {
    const pending = deferred<Response>()
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      if (String(input).endsWith('/registry/counts')) return json({ transfers: 0, repairs: 1, parts: 0 })
      return pending.promise
    })
    vi.stubGlobal('fetch', fetchMock)
    renderOfficialDocuments()

    await userEvent.click(await screen.findByRole('button', { name: /^Отвори Ремонти/ }))
    await userEvent.click(screen.getByRole('button', { name: 'Всички категории' }))
    pending.resolve(json(registryPage('repairs', [registryItem('repair:9', 'REP-STALE', 'REPAIR_PROTOCOL')])))

    await waitFor(() => expect(screen.getAllByRole('button', { name: /^Отвори / })).toHaveLength(3))
    expect(screen.queryByText('REP-STALE')).not.toBeInTheDocument()
  })

  it('prevents an older search response from overwriting a newer submitted search', async () => {
    const searchA = deferred<Response>()
    const searchB = deferred<Response>()
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input)
      if (url.endsWith('/registry/counts')) return json({ transfers: 0, repairs: 2, parts: 0 })
      const query = new URL(url, 'http://assetcore.local').searchParams.get('q')
      if (query === 'A') return searchA.promise
      if (query === 'B') return searchB.promise
      return json(registryPage('repairs', []))
    })
    vi.stubGlobal('fetch', fetchMock)
    renderOfficialDocuments()

    await userEvent.click(await screen.findByRole('button', { name: /^Отвори Ремонти/ }))
    await screen.findByText('Няма създадени ремонтни протоколи.')
    const input = screen.getByLabelText('Търсене в избраната категория')
    await userEvent.type(input, 'A{Enter}')
    await userEvent.clear(input)
    await userEvent.type(input, 'B{Enter}')
    searchB.resolve(json(registryPage('repairs', [registryItem('repair:2', 'REP-NEW', 'REPAIR_PROTOCOL')])))
    expect(await screen.findByText('REP-NEW')).toBeVisible()
    searchA.resolve(json(registryPage('repairs', [registryItem('repair:1', 'REP-STALE', 'REPAIR_PROTOCOL')])))

    await waitFor(() => expect(screen.queryByText('REP-STALE')).not.toBeInTheDocument())
    expect(screen.getByText('REP-NEW')).toBeVisible()
  })

  it('keeps issue and return in one lifecycle row, in server order, and never invents a missing return', async () => {
    const issue = registryItem('transfer:17', 'TR-QA-017', 'TRANSFER_ISSUE', {
      status: 'COMPLETE',
      signature_status: 'PARTIALLY_SIGNED',
      documents: [
        {
          document_type: 'TRANSFER_ISSUE', document_number: 'TR-QA-017', official_document_id: 17, version: 1, version_status: 'SIGNED',
          files: [{ format: 'docx', download_endpoint: '/issue.docx' }, { format: 'pdf', download_endpoint: '/issue.pdf', preview_endpoint: '/issue-preview.pdf' }],
        },
        {
          document_type: 'TRANSFER_RETURN', document_number: 'TR-QA-017-R', official_document_id: 18, version: 1, version_status: 'PARTIALLY_SIGNED',
          files: [{ format: 'pdf', download_endpoint: '/return.pdf', preview_endpoint: '/return-preview.pdf' }],
        },
      ],
    })
    const issueOnly = registryItem('transfer:18', 'TR-QA-018', 'TRANSFER_ISSUE')
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => String(input).endsWith('/registry/counts')
      ? json({ transfers: 2, repairs: 0, parts: 0 })
      : json(registryPage('transfers', [issue, issueOnly])))
    vi.stubGlobal('fetch', fetchMock)
    renderOfficialDocuments()

    await userEvent.click(await screen.findByRole('button', { name: /^Отвори Приемане/ }))
    const returnNumber = await screen.findByText('TR-QA-017-R')
    const lifecycleRow = returnNumber.closest('tr')
    expect(lifecycleRow).not.toBeNull()
    expect(within(lifecycleRow!).getAllByText('Протокол предаване')).toHaveLength(2)
    expect(within(lifecycleRow!).getAllByText('Протокол приемане')).toHaveLength(2)
    expect([...lifecycleRow!.querySelectorAll('.official-number strong')].map((node) => node.textContent)).toEqual(['TR-QA-017', 'TR-QA-017-R'])
    expect(within(lifecycleRow!).getByText('Завършен')).toBeVisible()
    expect(within(lifecycleRow!).getByText('Частично подписан')).toBeVisible()

    const issueOnlyRow = screen.getByText('TR-QA-018').closest('tr')
    expect(issueOnlyRow).not.toBeNull()
    expect(within(issueOnlyRow!).queryByText('Протокол приемане')).not.toBeInTheDocument()
    expect(within(issueOnlyRow!).getByRole('button', { name: 'Word' })).toBeVisible()
    expect(within(issueOnlyRow!).getByRole('button', { name: 'PDF' })).toBeVisible()
    expect(within(issueOnlyRow!).getByRole('button', { name: 'Преглед' })).toBeVisible()
  })

  it('reuses authenticated shared PDF preview and keeps its recovery controls', async () => {
    const item = registryItem('repair:3', 'REP/QA:003', 'REPAIR_PROTOCOL')
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input)
      if (url.endsWith('/registry/counts')) return json({ transfers: 0, repairs: 1, parts: 0 })
      if (url.includes('/registry/items?')) return json(registryPage('repairs', [item]))
      return new Response(new Blob(['official-pdf'], { type: 'application/pdf' }), {
        status: 200,
        headers: { 'Content-Type': 'application/pdf' },
      })
    })
    vi.stubGlobal('fetch', fetchMock)
    renderOfficialDocuments()

    await userEvent.click(await screen.findByRole('button', { name: /^Отвори Ремонти/ }))
    await screen.findByText('REP/QA:003')
    await userEvent.click(screen.getByRole('button', { name: 'Преглед' }))

    const dialog = await screen.findByRole('dialog', { name: 'REP_QA_003-v1.pdf' })
    expect(dialog.querySelector('object.generated-document-preview')).toHaveAttribute('data', 'blob:authenticated-official-preview')
    expect(within(dialog).getByRole('link', { name: 'Отвори PDF отделно' })).toHaveAttribute('href', 'blob:authenticated-official-preview')
    expect(fetchMock).toHaveBeenCalledWith('/api/repair:3-preview.pdf', expect.objectContaining({ credentials: 'same-origin' }))
  })

  it.each([
    ['bg', 'Отвори Ремонти — документи: 1', 'Търсене в избраната категория', 'Търси'],
    ['en', 'Open Repairs — documents: 1', 'Search in the selected category', 'Search'],
    ['ru', 'Открыть Ремонты — документы: 1', 'Поиск в выбранной категории', 'Искать'],
  ] as const)('renders complete category navigation and search controls in %s', async (locale, cardName, searchLabel, searchAction) => {
    const item = registryItem('repair:1', 'REP-I18N', 'REPAIR_PROTOCOL', { status: 'WAITING_PARTS', signature_status: 'NOT_REQUIRED' })
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => String(input).endsWith('/registry/counts')
      ? json({ transfers: 0, repairs: 1, parts: 0 })
      : json(registryPage('repairs', [item])))
    vi.stubGlobal('fetch', fetchMock)
    renderOfficialDocuments(locale)

    await userEvent.click(await screen.findByRole('button', { name: cardName }))
    expect(await screen.findByLabelText(searchLabel)).toBeVisible()
    expect(screen.getByRole('button', { name: searchAction })).toBeVisible()
    expect(document.body.textContent).not.toContain('official.')
  })

  it.each([
    ['repairs', 'Ремонти', 'REPAIR_PROTOCOL', 'WAITING_PARTS', 'Чака части'],
    ['parts', 'Заявени части', 'PART_REQUEST', 'APPROVED', 'Одобрена'],
  ] as const)('localizes %s domain and signature states instead of exposing enum codes', async (category, title, documentType, status, statusLabel) => {
    const item = registryItem(`${category}:8`, `${category.toUpperCase()}-I18N`, documentType, {
      status,
      signature_status: 'NOT_REQUIRED',
    })
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => String(input).endsWith('/registry/counts')
      ? json({ transfers: 0, repairs: category === 'repairs' ? 1 : 0, parts: category === 'parts' ? 1 : 0 })
      : json(registryPage(category, [item])))
    vi.stubGlobal('fetch', fetchMock)
    renderOfficialDocuments()

    await userEvent.click(await screen.findByRole('button', { name: new RegExp(`^Отвори ${title}`) }))
    expect(await screen.findByText(statusLabel)).toBeVisible()
    expect(screen.getByText('Не се изисква')).toBeVisible()
    expect(screen.queryByText(status)).not.toBeInTheDocument()
    expect(screen.queryByText('NOT_REQUIRED')).not.toBeInTheDocument()
  })

  it('refreshes landing counts and refreshes selected search from page one without duplicated rows', async () => {
    let countsCalls = 0
    let queryCalls = 0
    const first = registryItem('part:1', 'PR-REFRESH-OLD', 'PART_REQUEST')
    const fresh = registryItem('part:2', 'PR-REFRESH-NEW', 'PART_REQUEST')
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input)
      if (url.endsWith('/registry/counts')) {
        countsCalls += 1
        return json({ transfers: 0, repairs: 0, parts: countsCalls === 1 ? 2 : 3 })
      }
      const params = new URL(url, 'http://assetcore.local').searchParams
      if (!params.get('q')) return json(registryPage('parts', [first], { total: 2 }))
      queryCalls += 1
      return json(registryPage('parts', queryCalls === 1 ? [first] : [fresh], { total: 1 }))
    })
    vi.stubGlobal('fetch', fetchMock)
    renderOfficialDocuments()

    await userEvent.click(await screen.findByRole('button', { name: /^Отвори Заявени части/ }))
    await screen.findByText('PR-REFRESH-OLD')
    await userEvent.type(screen.getByLabelText('Търсене в избраната категория'), 'PR-REFRESH{Enter}')
    await screen.findByText('Показани 1 от 1')
    await userEvent.click(screen.getByRole('button', { name: 'Обнови' }))

    expect(await screen.findByText('PR-REFRESH-NEW')).toBeVisible()
    expect(screen.queryByText('PR-REFRESH-OLD')).not.toBeInTheDocument()
    expect(urls(fetchMock).at(-1)).toContain('category=parts&page=1&page_size=25&q=PR-REFRESH')
    expect(countsCalls).toBe(2)
    expectNoMassRegistryRequest(fetchMock)

    await userEvent.click(screen.getByRole('button', { name: 'Всички категории' }))
    expect(screen.getByRole('button', { name: 'Отвори Заявени части — документи: 3' })).toBeVisible()
    await userEvent.click(screen.getByRole('button', { name: 'Обнови' }))
    await waitFor(() => expect(countsCalls).toBe(3))
  })

  it('never uses the legacy mass endpoint through landing, navigation, search, paging, refresh, or back', async () => {
    const first = registryItem('transfer:1', 'TR-SCALE-001', 'TRANSFER_ISSUE')
    const second = registryItem('transfer:2', 'TR-SCALE-002', 'TRANSFER_ISSUE')
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input)
      if (url.endsWith('/registry/counts')) return json({ transfers: 2, repairs: 0, parts: 0 })
      const params = new URL(url, 'http://assetcore.local').searchParams
      if (params.get('page') === '2') return json(registryPage('transfers', [second], { total: 2, page: 2, has_previous: true }))
      return json(registryPage('transfers', [first], { total: 2, has_next: true, total_pages: 2 }))
    })
    vi.stubGlobal('fetch', fetchMock)
    renderOfficialDocuments()

    await userEvent.click(await screen.findByRole('button', { name: /^Отвори Приемане/ }))
    await screen.findByText('TR-SCALE-001')
    await userEvent.type(screen.getByLabelText('Търсене в избраната категория'), 'TR{Enter}')
    await screen.findByRole('button', { name: 'Покажи още' })
    await userEvent.click(screen.getByRole('button', { name: 'Покажи още' }))
    await screen.findByText('TR-SCALE-002')
    await userEvent.click(screen.getByRole('button', { name: 'Обнови' }))
    await waitFor(() => expect(urls(fetchMock).filter((url) => url.endsWith('/registry/counts'))).toHaveLength(2))
    await userEvent.click(screen.getByRole('button', { name: 'Всички категории' }))

    expectNoMassRegistryRequest(fetchMock)
    expect(urls(fetchMock).filter((url) => url.includes('/registry/items?')).every((url) => url.includes('category=transfers'))).toBe(true)
  })
})
