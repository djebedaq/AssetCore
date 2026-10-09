import { useCallback, useEffect, useRef, useState } from 'react'
import { ArrowLeft, RefreshCw } from 'lucide-react'

import { api } from '../../api'
import { statusText, useI18n, type TranslationKey } from '../../i18n'
import { DateFilters, FilterToolbar, useDebounced } from '../../ui/workspace'
import { Select } from '../../ui/Select'
import OfficialDocumentCategoryCards from './OfficialDocumentCategoryCards'
import OfficialDocumentSection from './OfficialDocumentSection'
import type {
  OfficialRegistryCategory,
  OfficialRegistryCounts,
  OfficialRegistryItem,
  OfficialRegistryPage,
} from './types'

const PAGE_SIZE = 25
type RegistryFilters = { query: string; status: string; signature_status: string; date_from: string; date_to: string }
const EMPTY_FILTERS: RegistryFilters = { query: '', status: '', signature_status: '', date_from: '', date_to: '' }
const STATUS_OPTIONS = {
  transfers: ['COMPLETE', 'INCOMPLETE'],
  repairs: ['ACCEPTED', 'DIAGNOSIS', 'WAITING_APPROVAL', 'WAITING_PARTS', 'REPAIRING', 'TESTING', 'COMPLETED'],
  parts: ['DRAFT', 'SUBMITTED', 'WAITING_APPROVAL', 'APPROVED', 'REJECTED', 'ORDERED', 'PARTIALLY_DELIVERED', 'DELIVERED', 'CANCELLED'],
}

const CATEGORY_PRESENTATION: Record<OfficialRegistryCategory, {
  titleKey: TranslationKey
  emptyKey: TranslationKey
  searchPlaceholderKey: TranslationKey
  statusDomain: 'transfer' | 'repair' | 'part'
}> = {
  transfers: {
    titleKey: 'official.sectionTransfers',
    emptyKey: 'official.emptyTransfers',
    searchPlaceholderKey: 'official.searchPlaceholderTransfers',
    statusDomain: 'transfer',
  },
  repairs: {
    titleKey: 'official.sectionRepairs',
    emptyKey: 'official.emptyRepairs',
    searchPlaceholderKey: 'official.searchPlaceholderRepairs',
    statusDomain: 'repair',
  },
  parts: {
    titleKey: 'official.sectionParts',
    emptyKey: 'official.emptyParts',
    searchPlaceholderKey: 'official.searchPlaceholderParts',
    statusDomain: 'part',
  },
}

function registryPagePath(category: OfficialRegistryCategory, page: number, filters: RegistryFilters): string {
  const params = new URLSearchParams({
    category,
    page: String(page),
    page_size: String(PAGE_SIZE),
  })
  for (const [key, value] of Object.entries(filters)) if (value.trim()) params.set(key === 'query' ? 'q' : key, value.trim())
  return `/official-documents/registry/items?${params.toString()}`
}

function mergeUniqueItems(current: OfficialRegistryItem[], incoming: OfficialRegistryItem[]): OfficialRegistryItem[] {
  const items = new Map(current.map((item) => [item.registry_key, item]))
  for (const item of incoming) items.set(item.registry_key, item)
  return [...items.values()]
}

export default function OfficialDocuments() {
  const { t } = useI18n()
  const [counts, setCounts] = useState<OfficialRegistryCounts | null>(null)
  const [countsLoading, setCountsLoading] = useState(true)
  const [countsError, setCountsError] = useState('')
  const [selectedCategory, setSelectedCategory] = useState<OfficialRegistryCategory | null>(null)
  const [filtersByCategory, setFiltersByCategory] = useState<Record<OfficialRegistryCategory, RegistryFilters>>({ transfers: EMPTY_FILTERS, repairs: EMPTY_FILTERS, parts: EMPTY_FILTERS })
  const filters = selectedCategory ? filtersByCategory[selectedCategory] : EMPTY_FILTERS
  const debouncedFilters = useDebounced(filters)
  const appliedSearch = debouncedFilters.query.trim()
  function changeFilter(key: keyof RegistryFilters, value: string) {
    if (selectedCategory) setFiltersByCategory(current => ({ ...current, [selectedCategory]: { ...current[selectedCategory], [key]: value } }))
  }
  const [items, setItems] = useState<OfficialRegistryItem[]>([])
  const [page, setPage] = useState(0)
  const [total, setTotal] = useState(0)
  const [hasNext, setHasNext] = useState(false)
  const [categoryLoading, setCategoryLoading] = useState(false)
  const [categoryError, setCategoryError] = useState('')
  const [loadingMore, setLoadingMore] = useState(false)
  const [loadMoreError, setLoadMoreError] = useState('')
  const countsRequestGeneration = useRef(0)
  const resultsRequestGeneration = useRef(0)

  const loadCounts = useCallback(async () => {
    const generation = ++countsRequestGeneration.current
    setCountsLoading(true)
    setCountsError('')
    try {
      const response = await api<OfficialRegistryCounts>('/official-documents/registry/counts')
      if (generation === countsRequestGeneration.current) setCounts(response)
    } catch {
      if (generation === countsRequestGeneration.current) setCountsError(t('official.countsLoadError'))
    } finally {
      if (generation === countsRequestGeneration.current) setCountsLoading(false)
    }
  }, [t])

  const loadCategoryPage = useCallback(async (
    category: OfficialRegistryCategory,
    requestedPage: number,
    query: RegistryFilters,
    append = false,
  ) => {
    const generation = ++resultsRequestGeneration.current
    if (append) {
      setLoadingMore(true)
      setLoadMoreError('')
    } else {
      setItems([])
      setPage(0)
      setTotal(0)
      setHasNext(false)
      setCategoryLoading(true)
      setCategoryError('')
      setLoadMoreError('')
    }

    try {
      const response = await api<OfficialRegistryPage>(registryPagePath(category, requestedPage, query))
      if (generation !== resultsRequestGeneration.current) return
      setItems((current) => append ? mergeUniqueItems(current, response.items) : response.items)
      setPage(response.page)
      setTotal(response.total)
      setHasNext(response.has_next)
    } catch {
      if (generation !== resultsRequestGeneration.current) return
      if (append) setLoadMoreError(t('official.loadMoreError'))
      else setCategoryError(t('official.categoryLoadError'))
    } finally {
      if (generation === resultsRequestGeneration.current) {
        setCategoryLoading(false)
        setLoadingMore(false)
      }
    }
  }, [t])

  useEffect(() => {
    void loadCounts()
    return () => {
      countsRequestGeneration.current += 1
      resultsRequestGeneration.current += 1
    }
  }, [loadCounts])

  useEffect(() => {
    if (selectedCategory && debouncedFilters === filters) void loadCategoryPage(selectedCategory, 1, debouncedFilters)
  }, [selectedCategory, debouncedFilters, filters, loadCategoryPage])

  function openCategory(category: OfficialRegistryCategory) {
    resultsRequestGeneration.current += 1
    setSelectedCategory(category)
    setItems([])
    setPage(0)
    setTotal(0)
    setHasNext(false)
    setCategoryError('')
    setLoadMoreError('')
  }

  function showAllCategories() {
    resultsRequestGeneration.current += 1
    setSelectedCategory(null)
    setItems([])
    setPage(0)
    setTotal(0)
    setHasNext(false)
    setCategoryLoading(false)
    setLoadingMore(false)
    setCategoryError('')
    setLoadMoreError('')
  }

  function clearSearch() {
    if (selectedCategory) setFiltersByCategory(current => ({ ...current, [selectedCategory]: EMPTY_FILTERS }))
  }

  function refresh() {
    void loadCounts()
    if (selectedCategory) void loadCategoryPage(selectedCategory, 1, debouncedFilters)
  }

  if (!selectedCategory) {
    return (
      <>
        <div className="toolbar official-registry-toolbar">
          <div>
            <h3>{t('official.title')}</h3>
            <p className="muted">{t('official.registrySubtitle')}</p>
          </div>
          <button className="secondary" disabled={countsLoading} onClick={() => { void loadCounts() }}>
            <RefreshCw size={16} aria-hidden="true" />
            {t('official.refresh')}
          </button>
        </div>
        {countsError && (
          <div className="error official-registry-error" role="alert">
            <span>{countsError}</span>
            <button className="secondary compact" onClick={() => { void loadCounts() }}>{t('official.retry')}</button>
          </div>
        )}
        {countsLoading && !counts
          ? <div className="loading" role="status">{t('common.loading')}</div>
          : counts && <OfficialDocumentCategoryCards counts={counts} onSelect={openCategory} />}
      </>
    )
  }

  const presentation = CATEGORY_PRESENTATION[selectedCategory]
  const selectedSection = { count: total, items }

  return (
    <>
      <div className="official-category-toolbar">
        <button className="secondary official-category-back" onClick={showAllCategories}>
          <ArrowLeft size={17} aria-hidden="true" />
          {t('official.allCategories')}
        </button>
        <button className="secondary" disabled={categoryLoading || loadingMore || countsLoading} onClick={refresh}>
          <RefreshCw size={16} aria-hidden="true" />
          {t('official.refresh')}
        </button>
      </div>

      <p className="muted">{t(presentation.searchPlaceholderKey)}</p>
      <FilterToolbar searchLabel={t('official.searchLabel')} searchPlaceholder={t(presentation.searchPlaceholderKey)} query={filters.query} onQuery={value => changeFilter('query', value)} onReset={clearSearch}>
        <label className="ac-filter"><span>{t('common.status')}</span><Select label={t('common.status')} value={filters.status} onChange={value => changeFilter('status', value)} searchable={false}
          options={[{ value: '', label: t('ux.allStatuses') }, ...STATUS_OPTIONS[selectedCategory].map(value => ({ value, label: selectedCategory === 'transfers' ? t(value === 'COMPLETE' ? 'official.lifecycleComplete' : 'official.lifecycleIncomplete') : statusText(t, value, selectedCategory === 'repairs' ? 'repair' : 'part') }))]} /></label>
        <label className="ac-filter"><span>{t('registry.signatures')}</span><Select label={t('registry.signatures')} value={filters.signature_status} onChange={value => changeFilter('signature_status', value)} searchable={false}
          options={[{ value: '', label: t('ux.allStatuses') }, ...([
            ['SIGNED', 'official.signatureSigned'], ['PARTIALLY_SIGNED', 'official.signaturePartial'], ['UNSIGNED', 'official.signatureUnsigned'], ['NOT_REQUIRED', 'official.signatureNotRequired'], ['UNKNOWN', 'official.signatureUnknown'],
          ] as const).map(([value, key]) => ({ value, label: t(key) }))]} /></label>
        <DateFilters from={filters.date_from} to={filters.date_to} onFrom={value => changeFilter('date_from', value)} onTo={value => changeFilter('date_to', value)} />
      </FilterToolbar>

      {categoryError && (
        <div className="error official-registry-error" role="alert">
          <span>{categoryError}</span>
          <button className="secondary compact" onClick={() => { void loadCategoryPage(selectedCategory, 1, debouncedFilters) }}>
            {t('official.retry')}
          </button>
        </div>
      )}

      {categoryLoading
        ? <div className="loading" role="status">{t('common.loading')}</div>
        : (
          <>
            <OfficialDocumentSection
              emptyKey={appliedSearch ? 'official.emptySearch' : presentation.emptyKey}
              section={selectedSection}
              statusDomain={presentation.statusDomain}
              titleKey={presentation.titleKey}
            />
            {appliedSearch && total === 0 && (
              <div className="official-empty-clear">
                <button className="secondary" onClick={clearSearch}>{t('official.clearSearch')}</button>
              </div>
            )}
            {total > 0 && (
              <div className="official-registry-pagination" aria-live="polite">
                <span>{t('official.loadedProgress', { loaded: items.length, total })}</span>
                {loadMoreError && <span className="error inline" role="alert">{loadMoreError}</span>}
                {hasNext && (
                  <button
                    className="secondary"
                    disabled={loadingMore}
                    onClick={() => { void loadCategoryPage(selectedCategory, page + 1, debouncedFilters, true) }}
                  >
                    {loadingMore ? t('official.loadingMore') : loadMoreError ? t('official.retry') : t('official.showMore')}
                  </button>
                )}
              </div>
            )}
          </>
        )}
    </>
  )
}
