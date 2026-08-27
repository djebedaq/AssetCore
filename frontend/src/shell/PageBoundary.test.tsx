import { act, render, screen } from '@testing-library/react'
import { lazy } from 'react'
import { afterEach, expect, it, vi } from 'vitest'
import { I18nProvider } from '../i18n'
import { PageBoundary } from './PageBoundary'

afterEach(() => vi.restoreAllMocks())

it('announces a pending page accessibly and replaces only its content when loaded', async () => {
  let resolve!: (value: { default: () => React.JSX.Element }) => void
  const Page = lazy(() => new Promise<{ default: () => React.JSX.Element }>((done) => { resolve = done }))
  render(<I18nProvider initialLocale="bg"><button>Shell</button><PageBoundary><Page /></PageBoundary></I18nProvider>)
  expect(screen.getByRole('status')).toHaveAttribute('aria-live', 'polite')
  expect(screen.getByRole('button', { name: 'Shell' })).toBeVisible()
  await act(async () => resolve({ default: () => <h3>Loaded page</h3> }))
  expect(screen.queryByRole('status')).not.toBeInTheDocument()
  expect(screen.getByRole('heading', { name: 'Loaded page' })).toBeVisible()
})

it('contains failed imports without exposing raw errors and recovers on navigation', async () => {
  vi.spyOn(console, 'error').mockImplementation(() => undefined)
  const Broken = lazy(() => Promise.reject(new Error('INTERNAL_CHUNK_FAILURE')))
  const { rerender } = render(<I18nProvider initialLocale="bg"><button>Shell</button><PageBoundary key="broken"><Broken /></PageBoundary></I18nProvider>)
  expect(await screen.findByRole('alert')).not.toHaveTextContent('INTERNAL_CHUNK_FAILURE')
  expect(screen.getByRole('button', { name: 'Обнови' })).toBeEnabled()
  expect(screen.getByRole('button', { name: 'Shell' })).toBeVisible()
  rerender(<I18nProvider initialLocale="bg"><PageBoundary key="next"><h3>Next page</h3></PageBoundary></I18nProvider>)
  expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  expect(screen.getByRole('heading', { name: 'Next page' })).toBeVisible()
})
