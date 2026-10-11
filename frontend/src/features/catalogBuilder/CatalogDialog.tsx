import { useEffect, useRef, type ReactNode, type RefObject } from 'react'
import { Modal } from '../../industrialUi'

export function useDialogFocus(root: RefObject<HTMLElement | null>, open: boolean, onClose: () => void) {
  const close = useRef(onClose)
  close.current = onClose
  useEffect(() => {
    if (!open || !root.current) return
    const previous = document.activeElement as HTMLElement | null
    const dialog = () => root.current?.querySelector<HTMLElement>('[role=dialog]') || root.current
    const initial = dialog()
    initial?.setAttribute('tabindex', '-1'); initial?.focus()
    function key(event: KeyboardEvent) {
      const dialogs = [...document.querySelectorAll<HTMLElement>('[role=dialog][aria-modal=true]')]
      const active = dialogs.at(-1)
      if (!active || dialog() !== active) return
      if (event.key === 'Escape') { event.preventDefault(); close.current(); return }
      if (event.key !== 'Tab') return
      const targets = [...active.querySelectorAll<HTMLElement>('button:not(:disabled), input:not(:disabled), select:not(:disabled), textarea:not(:disabled), a[href], summary, [tabindex="0"]')]
        .filter(node => node.getClientRects().length && node.getAttribute('tabindex') !== '-1')
      const first = targets[0], last = targets.at(-1)
      if (!first) { event.preventDefault(); active.focus() }
      else if (event.shiftKey && (document.activeElement === first || document.activeElement === active || !active.contains(document.activeElement))) { event.preventDefault(); last?.focus() }
      else if (!event.shiftKey && (document.activeElement === last || document.activeElement === active || !active.contains(document.activeElement))) { event.preventDefault(); first.focus() }
    }
    document.addEventListener('keydown', key)
    return () => { document.removeEventListener('keydown', key); if (previous?.isConnected) previous.focus() }
  }, [open, root])
}

export default function CatalogDialog({ title, onClose, children, wide = false }: { title: string; onClose: () => void; children: ReactNode; wide?: boolean }) {
  const root = useRef<HTMLDivElement>(null)
  useDialogFocus(root, true, onClose)
  return <div ref={root}><Modal title={title} onClose={onClose} wide={wide}>{children}</Modal></div>
}
