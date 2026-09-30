import { expect, it } from 'vitest'
import { catalogDisplayName } from './catalogNames'

it('presents verified Builder names in all three UI languages without V2 enrichment', () => {
  const part = { description: 'Canonical QA name', description_bg: 'Тестова част',
    description_en: 'Test part', description_ru: 'Тестовая деталь', translation_version: 'BUILDER' }
  expect(catalogDisplayName(part, 'bg')).toBe('Тестова част')
  expect(catalogDisplayName(part, 'en')).toBe('Test part')
  expect(catalogDisplayName(part, 'ru')).toBe('Тестовая деталь')
  expect(catalogDisplayName({ ...part, description_ru: null }, 'ru')).toBe('Canonical QA name')
  expect(catalogDisplayName({ ...part, translation_version: 'V2' }, 'ru')).toBe('Test part / Тестова част')
})
