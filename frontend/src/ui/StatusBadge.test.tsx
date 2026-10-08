import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, expect, it } from 'vitest'
import { I18nProvider } from '../i18n'
import { StatusBadge } from './StatusBadge'

afterEach(cleanup)

it.each([
  ['machine', 'READY', 'success', 'Готова'],
  ['machine', 'ISSUED', 'info', 'Издадена'],
  ['repair', 'WAITING_PARTS', 'neutral', 'Чака части'],
  ['repair', 'COMPLETED', 'success', 'Завършена'],
  ['part', 'REJECTED', 'neutral', 'Отхвърлена'],
  ['batch', 'CANCELLED', 'neutral', 'Отказана'],
] as const)('uses the domain semantics for %s/%s', (domain, status, tone, label) => {
  render(<I18nProvider><StatusBadge domain={domain} status={status} /></I18nProvider>)
  const badge = screen.getByText(label).closest('.ac-status')
  expect(badge).toHaveClass(`ac-status-${tone}`)
  expect(badge?.querySelector('svg')).toHaveAttribute('aria-hidden', 'true')
  expect(badge).not.toHaveClass('ac-status-error')
})

it('preserves an unknown historical code with a neutral accessible label', () => {
  render(<I18nProvider><StatusBadge domain="repair" status="QA_LEGACY_UNKNOWN" /></I18nProvider>)
  expect(screen.getByText('QA_LEGACY_UNKNOWN').closest('.ac-status')).toHaveClass('ac-status-neutral')
})
