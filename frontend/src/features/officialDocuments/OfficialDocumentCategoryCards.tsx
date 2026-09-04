import { ArrowRight, ArrowRightLeft, PackageSearch, Wrench, type LucideIcon } from 'lucide-react'

import { useI18n, type TranslationKey } from '../../i18n'
import type { OfficialRegistryCategory, OfficialRegistryCounts } from './types'

type CategoryDefinition = {
  category: OfficialRegistryCategory
  titleKey: TranslationKey
  subtitleKey: TranslationKey
  icon: LucideIcon
}

const CATEGORIES: CategoryDefinition[] = [
  {
    category: 'transfers',
    titleKey: 'official.sectionTransfers',
    subtitleKey: 'official.categoryTransfersSubtitle',
    icon: ArrowRightLeft,
  },
  {
    category: 'repairs',
    titleKey: 'official.sectionRepairs',
    subtitleKey: 'official.categoryRepairsSubtitle',
    icon: Wrench,
  },
  {
    category: 'parts',
    titleKey: 'official.sectionParts',
    subtitleKey: 'official.categoryPartsSubtitle',
    icon: PackageSearch,
  },
]

export default function OfficialDocumentCategoryCards({
  counts,
  onSelect,
}: {
  counts: OfficialRegistryCounts
  onSelect: (category: OfficialRegistryCategory) => void
}) {
  const { number, t } = useI18n()

  return (
    <div className="official-category-grid">
      {CATEGORIES.map(({ category, icon: Icon, subtitleKey, titleKey }) => {
        const title = t(titleKey)
        const count = counts[category]
        return (
          <button
            className="official-category-card"
            key={category}
            onClick={() => onSelect(category)}
            type="button"
            aria-label={t('official.openCategory', { category: title, count })}
          >
            <span className="official-category-card-icon" aria-hidden="true"><Icon size={24} /></span>
            <span className="official-category-card-copy">
              <strong>{title}</strong>
              <small>{t(subtitleKey)}</small>
            </span>
            <span className="official-category-card-footer">
              <span><span>{t('official.categoryDocuments')}:</span><b>{number(count)}</b></span>
              <ArrowRight size={19} aria-hidden="true" />
            </span>
          </button>
        )
      })}
    </div>
  )
}
