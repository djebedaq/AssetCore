import { lazy } from 'react'
import { IndustrialRepairs } from './lazyPages'
import { PageBoundary } from './PageBoundary'

// Public App imports retained without pulling retired screens into the shell.
const LegacyPartCatalog = lazy(() => import('../features/catalog/LegacyPartCatalog'))
const LegacyDocuments = lazy(() => import('../features/technicalLibrary/LegacyDocuments'))

export function Repairs() {
  return <PageBoundary><IndustrialRepairs /></PageBoundary>
}

export function PartCatalog() {
  return <PageBoundary><LegacyPartCatalog /></PageBoundary>
}

export function Documents() {
  return <PageBoundary><LegacyDocuments /></PageBoundary>
}
