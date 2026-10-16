import { useEffect, useRef } from 'react'

let openDialogs = 0
let previousOverflow = ''

export function useModalFocus(onClose: () => void) {
  const ref = useRef<HTMLElement>(null)
  const close = useRef(onClose)
  useEffect(() => { close.current = onClose }, [onClose])
  useEffect(() => {
    const dialog = ref.current
    if (!dialog) return
    const previous = document.activeElement instanceof HTMLElement ? document.activeElement : null
    if (openDialogs++ === 0) {
      previousOverflow = document.body.style.overflow
      document.body.style.overflow = 'hidden'
    }
    const focusable = () => Array.from(dialog.querySelectorAll<HTMLElement>('button:not(:disabled), a[href], input:not(:disabled), select:not(:disabled), textarea:not(:disabled), [tabindex="0"]'))
      .filter(element => !element.closest('[hidden], [aria-hidden="true"]'))
    ;(focusable()[0] || dialog).focus()
    const keydown = (event: KeyboardEvent) => {
      const dialogs = document.querySelectorAll('[role="dialog"]')
      if (dialogs[dialogs.length - 1] !== dialog) return
      if (event.key === 'Escape') {
        event.preventDefault(); event.stopImmediatePropagation(); close.current()
      } else if (event.key === 'Tab') {
        const controls = focusable()
        const first = controls[0] || dialog
        const last = controls[controls.length - 1] || dialog
        if (event.shiftKey && (document.activeElement === first || !dialog.contains(document.activeElement))) {
          event.preventDefault(); last.focus()
        } else if (!event.shiftKey && (document.activeElement === last || !dialog.contains(document.activeElement))) {
          event.preventDefault(); first.focus()
        }
      }
    }
    document.addEventListener('keydown', keydown)
    return () => {
      document.removeEventListener('keydown', keydown)
      if (--openDialogs === 0) document.body.style.overflow = previousOverflow
      if (previous?.isConnected && previous !== document.body) previous.focus()
      else document.querySelector<HTMLElement>('[role=tab][aria-selected=true]')?.focus()
    }
  }, [])
  return ref
}
