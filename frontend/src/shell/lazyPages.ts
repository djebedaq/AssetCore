import { lazy } from 'react'

// Page-level boundaries only. Shared shell controls stay eager.
export const Dashboard = lazy(() => import('../features/dashboard/Dashboard'))
export const Machines = lazy(() => import('../features/machines/Machines'))
export const Transfers = lazy(() => import('../features/transfers/Transfers'))
export const IndustrialRepairs = lazy(() => import('../features/repairs/IndustrialRepairs').then((module) => ({ default: module.IndustrialRepairs })))
export const IndustrialCatalog = lazy(() => import('../features/catalog/IndustrialCatalog').then((module) => ({ default: module.IndustrialCatalog })))
export const IndustrialPartRequests = lazy(() => import('../features/partRequests/PartRequestsTracking').then((module) => ({ default: module.PartRequestsTracking })))
export const TechnicalLibrary = lazy(() => import('../features/technicalLibrary/TechnicalLibrary').then((module) => ({ default: module.TechnicalLibrary })))
export const OfficialDocuments = lazy(() => import('../features/officialDocuments/OfficialDocuments'))
export const Reports = lazy(() => import('../features/reports/Reports'))
export const Audit = lazy(() => import('../features/audit/Audit'))
export const QrCodes = lazy(() => import('../features/qr/QrCodes'))
export const UserAdministration = lazy(() => import('../features/administration/UserAdministration'))
export const SettingsPage = lazy(() => import('../features/administration/SettingsPage'))
export const SignaturePage = lazy(() => import('../SignaturePage'))
