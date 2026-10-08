import { Languages } from 'lucide-react'
import { useI18n } from '../i18n'
import { SUPPORTED_LOCALES, type Locale } from '../locale'
import { Select } from '../ui/Select'

export function LanguageSwitcher({ compact = false }: { compact?: boolean }) {
  const { locale, setLocale, t } = useI18n()
  return (
    <label className={compact ? 'language-switch compact-language' : 'language-switch'}>
      <Languages size={17} aria-hidden="true" />
      <span className="sr-only">{t('language.label')}</span>
      <Select label={t('language.label')} value={locale} onChange={value => setLocale(value as Locale)} searchable={false}
        options={SUPPORTED_LOCALES.map(language => ({ value: language, label: t(`language.${language}`) }))} />
    </label>
  )
}
