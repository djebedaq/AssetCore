import { useEffect, useId, useRef, useState, type KeyboardEvent } from 'react'
import { createPortal } from 'react-dom'
import { Check, ChevronDown, Search } from 'lucide-react'
import { useI18n } from '../i18n'

export type SelectOption = { value: string; label: string; disabled?: boolean }
type Props = {
  label: string; value: string; options: SelectOption[]; onChange: (value: string) => void
  disabled?: boolean; invalid?: boolean; searchable?: boolean; placeholder?: string
  onSearch?: (query: string) => void; loading?: boolean
}

/** A single-select listbox with a portal, bounded viewport and explicit focus ownership. */
export function Select({ label, value, options, onChange, disabled, invalid, searchable = true, placeholder, onSearch, loading }: Props) {
  const { t } = useI18n()
  const id = useId()
  const trigger = useRef<HTMLButtonElement>(null)
  const menu = useRef<HTMLDivElement>(null)
  const input = useRef<HTMLInputElement>(null)
  const [open, setOpen] = useState(false)
  const [query, setQuery] = useState('')
  const [active, setActive] = useState(-1)
  const [position, setPosition] = useState({ top: 0, left: 0, width: 0, height: 280 })
  const visible = onSearch ? options : options.filter(option => option.label.toLocaleLowerCase().includes(query.toLocaleLowerCase()))
  const selected = options.find(option => option.value === value)

  function close(restore = false) { setOpen(false); if (restore) trigger.current?.focus() }
  function show() {
    if (disabled) return
    setQuery(''); onSearch?.(''); setActive(options.findIndex(option => option.value === value)); setOpen(true)
  }
  function choose(index: number) {
    const option = visible[index]
    if (!option || option.disabled) return
    onChange(option.value); close(true)
  }
  function keys(event: KeyboardEvent) {
    if (event.key === 'Escape') { event.preventDefault(); close(true); return }
    if (event.key === 'Tab') { trigger.current?.focus(); close(); return }
    if (event.key === 'Enter' || event.key === ' ') {
      if (event.key === ' ' && event.target === input.current) return
      event.preventDefault(); if (open) choose(active); else show(); return
    }
    if (['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(event.key)) {
      event.preventDefault()
      if (!open) { show(); return }
      const step = event.key === 'ArrowUp' || event.key === 'End' ? -1 : 1
      let index = event.key === 'Home' ? -1 : event.key === 'End' ? visible.length : active < 0 && step < 0 ? visible.length : active
      for (let count = 0; count < visible.length; count++) {
        index = (index + step + visible.length) % visible.length
        if (!visible[index].disabled) { setActive(index); break }
      }
    } else if (!open && event.key.length === 1 && !event.ctrlKey && !event.metaKey && searchable) {
      event.preventDefault(); show(); setQuery(event.key); onSearch?.(event.key)
    }
  }
  useEffect(() => {
    if (!open) return
    function place() {
      const rect = trigger.current?.getBoundingClientRect()
      if (!rect) return
      const below = window.innerHeight - rect.bottom - 8
      const above = rect.top - 8
      const height = Math.min(320, Math.max(below, above))
      const width = Math.min(Math.max(rect.width, 220), window.innerWidth - 16)
      setPosition({ top: below >= height ? rect.bottom + 4 : Math.max(8, rect.top - height - 4), left: Math.max(8, Math.min(rect.left, window.innerWidth - width - 8)), width, height })
    }
    function outside(event: PointerEvent) {
      if (!menu.current?.contains(event.target as Node) && !trigger.current?.contains(event.target as Node)) close()
    }
    place(); if (searchable) input.current?.focus()
    window.addEventListener('resize', place); window.addEventListener('scroll', place, true)
    document.addEventListener('pointerdown', outside)
    return () => { window.removeEventListener('resize', place); window.removeEventListener('scroll', place, true); document.removeEventListener('pointerdown', outside) }
  }, [open, searchable])
  useEffect(() => { if (open && active >= 0) document.getElementById(`${id}-${active}`)?.scrollIntoView?.({ block: 'nearest' }) }, [active, open, id])
  useEffect(() => { if (disabled) setOpen(false) }, [disabled])

  return <div className="ac-select">
    <button ref={trigger} type="button" role="combobox" aria-label={label} aria-expanded={open} aria-controls={open ? `${id}-list` : undefined}
      aria-haspopup="listbox" aria-activedescendant={open && active >= 0 && visible[active] ? `${id}-${active}` : undefined} aria-invalid={invalid || undefined}
      disabled={disabled} onClick={() => open ? close() : show()} onKeyDown={keys}>
      <span title={selected?.label}>{selected?.label || placeholder || t('ux.select')}</span><ChevronDown size={15} aria-hidden="true" />
    </button>
    {open && createPortal(<div className="ac-select-menu" ref={menu} style={{ top: position.top, left: position.left, width: position.width, maxHeight: position.height }} onKeyDown={keys}>
      {searchable && <div className="ac-select-search"><Search size={15} aria-hidden="true" /><input ref={input} role="combobox" aria-label={t('ux.searchOptions', { label })}
        aria-expanded="true" aria-controls={`${id}-list`} aria-autocomplete="list" aria-activedescendant={active >= 0 && visible[active] ? `${id}-${active}` : undefined}
        value={query} onChange={event => { setQuery(event.target.value); onSearch?.(event.target.value); setActive(0) }} /></div>}
      <div role="listbox" aria-label={label} id={`${id}-list`}>
        {visible.map((option, index) => <div role="option" id={`${id}-${index}`} key={option.value} aria-selected={option.value === value} aria-disabled={option.disabled || undefined}
          className={index === active ? 'active' : ''} onPointerMove={() => setActive(index)} onPointerDown={event => event.preventDefault()} onClick={() => choose(index)}>
          <span>{option.label}</span>{option.value === value && <Check size={15} aria-hidden="true" />}
        </div>)}
      </div>
      {(loading || !visible.length) && <p className="ac-select-empty" role="status">{t(loading ? 'common.loading' : 'ux.noResults')}</p>}
    </div>, document.body)}
  </div>
}
