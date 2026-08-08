import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it } from 'vitest'
import { LanguageSwitcher } from './App'
import { BatchProgressCard } from './BulkTransfers'
import {
  bg,
  catalogs,
  en,
  formatDate,
  formatNumber,
  I18nProvider,
  ru,
  translate,
} from './i18n'
import { getStoredLocale, LANGUAGE_STORAGE_KEY } from './locale'

describe('многоезична архитектура', () => {
  beforeEach(() => localStorage.clear())

  it('поддържа точно еднакви translation keys за bg, en и ru', () => {
    const expected = Object.keys(bg).sort()
    expect(Object.keys(en).sort()).toEqual(expected)
    expect(Object.keys(ru).sort()).toEqual(expected)
    expect(Object.keys(catalogs)).toEqual(['bg', 'en', 'ru'])
  })

  it('използва български fallback при невалидно запазено предпочитание', () => {
    localStorage.setItem(LANGUAGE_STORAGE_KEY, 'de')
    expect(getStoredLocale()).toBe('bg')
    expect(translate('bg', 'bulk.issue')).toBe('Издай')
  })

  it('превключва езика и запазва избора локално', async () => {
    render(<I18nProvider initialLocale="bg"><LanguageSwitcher /></I18nProvider>)
    const select = screen.getByLabelText('Език')
    await userEvent.selectOptions(select, 'en')
    expect(screen.getByLabelText('Language')).toHaveValue('en')
    expect(localStorage.getItem(LANGUAGE_STORAGE_KEY)).toBe('en')
    expect(document.documentElement.lang).toBe('en')
  })

  it('не смесва български текст в английския изглед на партида', () => {
    render(<I18nProvider initialLocale="en"><BatchProgressCard batch={{
      batch_id: 1,
      batch_reference: 'HPWJ-B-1',
      status: 'PARTIALLY_RETURNED',
      total_machines: 3,
      returned_machines: 1,
      still_issued_machines: 2,
      awaiting_signature_machines: 0,
      machine_numbers: ['4', '7', '10'],
    }} /></I18nProvider>)
    expect(screen.getByText('Partially returned batch')).toBeVisible()
    expect(screen.getByText(/Returned: 1 · Still issued: 2 · Total: 3/)).toBeVisible()
    expect(screen.queryByText('Частично върната партида')).not.toBeInTheDocument()
  })

  it('форматира дати и числа според избрания locale', () => {
    const value = new Date('2026-07-31T12:30:00Z')
    expect(formatDate('bg', value)).not.toEqual(formatDate('en', value))
    expect(formatNumber('bg', 1234.5)).not.toEqual(formatNumber('en', 1234.5))
  })

  it('съдържа професионални основни термини и на трите езика', () => {
    expect(translate('bg', 'nav.transfers')).toBe('Приемане / предаване')
    expect(translate('en', 'nav.transfers')).toBe('Issue / return')
    expect(translate('ru', 'nav.transfers')).toBe('Выдача / возврат')
  })
})
