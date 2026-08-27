import { expect, it } from 'vitest'
import { LanguageSwitcher, Documents, PartCatalog, Repairs } from '../App'
import * as compatibility from '../IndustrialPlatform'
import Users from '../UserAdministration'
import Governance from '../GovernancePanel'
import Official from '../OfficialDocuments'
import { MachinePassportModal } from '../features/passport/MachinePassportModal'
import { AdministrationPanel } from '../features/administration/AdministrationPanel'
import { GlobalSearchBox } from '../features/search/GlobalSearchBox'
import { TechnicalLibrary } from '../features/technicalLibrary/TechnicalLibrary'
import { IndustrialCatalog } from '../features/catalog/IndustrialCatalog'
import { IndustrialRepairs } from '../features/repairs/IndustrialRepairs'
import { PartRequestsTracking } from '../features/partRequests/PartRequestsTracking'
import UserAdministration from '../features/administration/UserAdministration'
import GovernancePanel from '../features/administration/GovernancePanel'
import OfficialDocuments from '../features/officialDocuments/OfficialDocuments'
import { LanguageSwitcher as ShellLanguageSwitcher } from './LanguageSwitcher'

it('preserves every pre-extraction public compatibility import', () => {
  expect(compatibility).toMatchObject({ AdministrationPanel, GlobalSearchBox, IndustrialCatalog, IndustrialRepairs,
    IndustrialPartRequests: PartRequestsTracking, MachinePassportModal, TechnicalLibrary })
  expect(Users).toBe(UserAdministration)
  expect(Governance).toBe(GovernancePanel)
  expect(Official).toBe(OfficialDocuments)
  expect(LanguageSwitcher).toBe(ShellLanguageSwitcher)
  for (const screen of [Documents, PartCatalog, Repairs]) expect(screen).toBeTypeOf('function')
})
