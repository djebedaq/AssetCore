import type { ReactNode } from 'react'
import { X } from 'lucide-react'
import { useI18n } from '../../i18n'
import { useModalFocus } from '../../ui/useModalFocus'

export function ModalShell({ title, onClose, children, wide = false }: {
  title: string
  onClose: () => void
  children: ReactNode
  wide?: boolean
}) {
  const { t } = useI18n()
  const dialog = useModalFocus(onClose)
  return (
    <div className="modal-bg" role="presentation">
      <section ref={dialog} tabIndex={-1} className={`modal bulk-modal ${wide ? 'bulk-modal-wide' : ''}`} role="dialog" aria-modal="true" aria-label={title}>
        <div className="modal-head"><h3>{title}</h3><button type="button" onClick={onClose} aria-label={t('common.close')}><X /></button></div>
        {children}
      </section>
    </div>
  )
}
