import { Component, Suspense, type ReactNode } from 'react'
import { useI18n } from '../i18n'

export function PageLoading() {
  const { t } = useI18n()
  return <div className="loading" role="status" aria-live="polite">{t('common.loading')}</div>
}

export function PageLoadError() {
  const { t } = useI18n()
  return <div className="panel"><p className="error" role="alert">{t('errors.generic')}</p><button className="secondary" onClick={() => window.location.reload()}>{t('official.refresh')}</button></div>
}

class PageErrorBoundary extends Component<{ children: ReactNode; fallback: ReactNode }, { failed: boolean }> {
  state = { failed: false }

  static getDerivedStateFromError() {
    return { failed: true }
  }

  render() {
    return this.state.failed ? this.props.fallback : this.props.children
  }
}

// Keep navigation outside this boundary. A failed/pending page must not trap
// the user; App keys the boundary by the existing page selection.
export function PageBoundary({ children, fallback = <PageLoading />, errorFallback = <PageLoadError /> }: {
  children: ReactNode; fallback?: ReactNode; errorFallback?: ReactNode
}) {
  return <PageErrorBoundary fallback={errorFallback}><Suspense fallback={fallback}>{children}</Suspense></PageErrorBoundary>
}
