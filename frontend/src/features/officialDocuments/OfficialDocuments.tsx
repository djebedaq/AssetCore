import { type FormEvent, useCallback, useEffect, useRef, useState } from 'react'
import { ArrowLeft, RefreshCw, Search, X } from 'lucide-react'

import { api } from '../../api'
import { useI18n, type TranslationKey } from '../../i18n'
import OfficialDocumentCategoryCards from './OfficialDocumentCategoryCards'
import OfficialDocumentSection from './OfficialDocumentSection'
import type {
  OfficialRegistryCategory,
  OfficialRegistryCounts,
  OfficialRegistryItem,
  OfficialRegistryPage,
} from './types'

const PAGE_SIZE = 25

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

function registryPagePath(category: OfficialRegistryCategory, page: number, query: string): string {
  const params = new URLSearchParams({
    category,
    page: String(page),
    page_size: String(PAGE_SIZE),
  })
  if (query) params.set('q', query)
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
  const [searchInput, setSearchInput] = useState('')
  const [appliedSearch, setAppliedSearch] = useState('')
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
    query: string,
    append = false,
  ) => {
    const generation = ++resultsRequestGeneration.current
    if (append) {
      setLoadingMore(true)
      setLoadMoreError('')
    } else {
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

  function openCategory(category: OfficialRegistryCategory) {
    resultsRequestGeneration.current += 1
    setSelectedCategory(category)
    setSearchInput('')
    setAppliedSearch('')
    setItems([])
    setPage(0)
    setTotal(0)
    setHasNext(false)
    setCategoryError('')
    setLoadMoreError('')
    void loadCategoryPage(category, 1, '')
  }

  function showAllCategories() {
    resultsRequestGeneration.current += 1
    setSelectedCategory(null)
    setSearchInput('')
    setAppliedSearch('')
    setItems([])
    setPage(0)
    setTotal(0)
    setHasNext(false)
    setCategoryLoading(false)
    setLoadingMore(false)
    setCategoryError('')
    setLoadMoreError('')
  }

  function submitSearch(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!selectedCategory) return
    const query = searchInput.trim()
    setAppliedSearch(query)
    void loadCategoryPage(selectedCategory, 1, query)
  }

  function clearSearch() {
    if (!selectedCategory) return
    setSearchInput('')
    setAppliedSearch('')
    void loadCategoryPage(selectedCategory, 1, '')
  }

  function refresh() {
    void loadCounts()
    if (selectedCategory) void loadCategoryPage(selectedCategory, 1, appliedSearch)
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

      <form className="official-category-search" role="search" onSubmit={submitSearch}>
        <label htmlFor="official-category-query">{t('official.searchLabel')}</label>
        <div className="official-category-search-field">
          <Search size={17} aria-hidden="true" />
          <input
            id="official-category-query"
            value={searchInput}
            onChange={(event) => setSearchInput(event.target.value)}
            placeholder={t(presentation.searchPlaceholderKey)}
            type="search"
          />
        </div>
        <button className="primary" disabled={loadingMore} type="submit">
          <Search size={16} aria-hidden="true" />
          {t('official.searchAction')}
        </button>
        {appliedSearch && (
          <button className="secondary" disabled={loadingMore} onClick={clearSearch} type="button">
            <X size={16} aria-hidden="true" />
            {t('official.clearSearch')}
          </button>
        )}
      </form>

      {categoryError && (
        <div className="error official-registry-error" role="alert">
          <span>{categoryError}</span>
          <button className="secondary compact" onClick={() => { void loadCategoryPage(selectedCategory, 1, appliedSearch) }}>
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
                    onClick={() => { void loadCategoryPage(selectedCategory, page + 1, appliedSearch, true) }}
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
