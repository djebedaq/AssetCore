import { lazy, type ComponentProps } from 'react'
import { useI18n } from '../../i18n'
import { Modal } from '../../industrialUi'
import { PageBoundary, PageLoadError, PageLoading } from '../../shell/PageBoundary'
import type { MachinePassportModal as Passport } from './MachinePassportModal'

const MachinePassportModal = lazy(() => import('./MachinePassportModal').then((module) => ({ default: module.MachinePassportModal })))

export function LazyMachinePassportModal(props: ComponentProps<typeof Passport>) {
  const { t } = useI18n()
  return <PageBoundary key={props.machineId}
    fallback={<Modal title={t('passport.loadingTitle')} onClose={props.onClose} wide><PageLoading /></Modal>}
    errorFallback={<Modal title={t('passport.loadingTitle')} onClose={props.onClose} wide><PageLoadError /></Modal>}
  ><MachinePassportModal {...props} /></PageBoundary>
}
