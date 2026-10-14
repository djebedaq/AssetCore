import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { I18nProvider } from '../../i18n'
import WizardReview from './WizardReview'
import { ux05Bg, ux05En, ux05Ru } from './ux05Translations'
import type { Workflow } from './wizardTypes'

afterEach(cleanup)
const workflow: Workflow = { ready: true, publication_digest: 'qa', current_published_revision_id: null,
  errors: [], warnings: [{ code: 'catalog_publication_source_review_required' },
    { code: 'catalog_publication_hotspot_coverage', missing_positions: 14 }],
  summary: { part_count: 59, reviewed_source_count: 1, spare_list_page_count: 4 },
  progress: { position_count: 59, completed_positions: 45 }, resume_step: 'review' }

it.each(['bg', 'en', 'ru'] as const)('keeps publication enabled with optional warnings in %s', locale => {
  render(<I18nProvider initialLocale={locale}><WizardReview workflow={workflow} editable busy={false}
    onFix={vi.fn()} onPublish={vi.fn()} /></I18nProvider>)
  const buttons = screen.getAllByRole('button')
  expect(buttons.at(-1)).toBeEnabled()
  expect(screen.getByText(/14/)).toBeVisible()
  expect(screen.queryByText('builder.error.generic')).not.toBeInTheDocument()
})

it('retains genuine error blockers and complete translations', () => {
  render(<I18nProvider><WizardReview workflow={{ ...workflow, ready: false,
    errors: [{ code: 'catalog_publication_candidate_conflict' }] }} editable busy={false}
    onFix={vi.fn()} onPublish={vi.fn()} /></I18nProvider>)
  expect(screen.getAllByRole('button').at(-1)).toBeDisabled()
  expect(Object.keys(ux05Bg).sort()).toEqual(Object.keys(ux05En).sort())
  expect(Object.keys(ux05Bg).sort()).toEqual(Object.keys(ux05Ru).sort())
})
