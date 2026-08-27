import { Languages } from 'lucide-react'
import { useI18n } from '../i18n'
import { SUPPORTED_LOCALES, type Locale } from '../locale'

export function LanguageSwitcher({ compact = false }: { compact?: boolean }) {
  const { locale, setLocale, t } = useI18n()
  return (
    <label className={compact ? 'language-switch compact-language' : 'language-switch'}>
      <Languages size={17} aria-hidden="true" />
      <span className="sr-only">{t('language.label')}</span>
      <select
        aria-label={t('language.label')}
        value={locale}
        onChange={(event) => setLocale(event.target.value as Locale)}
      >
        {SUPPORTED_LOCALES.map((language) => (
          <option key={language} value={language}>{t(`language.${language}`)}</option>
        ))}
      </select>
    </label>
  )
}
