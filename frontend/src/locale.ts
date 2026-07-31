export type Locale = 'bg' | 'en' | 'ru'

export const DEFAULT_LOCALE: Locale = 'bg'
export const SUPPORTED_LOCALES: readonly Locale[] = ['bg', 'en', 'ru']
export const LANGUAGE_STORAGE_KEY = 'assetcore_language'

export function isLocale(value: unknown): value is Locale {
  return typeof value === 'string' && SUPPORTED_LOCALES.includes(value as Locale)
}

export function getStoredLocale(): Locale {
  if (typeof window === 'undefined') return DEFAULT_LOCALE
  const stored = window.localStorage.getItem(LANGUAGE_STORAGE_KEY)
  return isLocale(stored) ? stored : DEFAULT_LOCALE
}

export function storeLocale(locale: Locale): void {
  if (typeof window !== 'undefined') window.localStorage.setItem(LANGUAGE_STORAGE_KEY, locale)
}
