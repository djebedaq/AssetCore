import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { I18nProvider } from '../i18n'
import { Select } from './Select'
import { StatusBadge, statusTone } from './StatusBadge'

describe('shared selection control', () => {
  it('supports search, disabled options, keyboard selection, Escape and focus return', async () => {
    const user = userEvent.setup()
    const changed = vi.fn()
    render(<I18nProvider><Select label="QA selector" value="a" onChange={changed} options={[{ value: 'a', label: 'Alpha' }, { value: 'b', label: 'Blocked', disabled: true }, { value: 'c', label: 'Category with a very long label' }]} /></I18nProvider>)
    const trigger = screen.getByRole('combobox', { name: 'QA selector' })
    trigger.focus(); await user.keyboard('{Enter}')
    const input = screen.getByRole('combobox', { name: 'Търсене: QA selector' })
    expect(input).toHaveFocus()
    expect(within(screen.getByRole('listbox')).getByRole('option', { name: 'Alpha' })).toHaveAttribute('aria-selected', 'true')
    await user.keyboard('{ArrowDown}{Enter}')
    expect(changed).toHaveBeenCalledWith('c')
    expect(trigger).toHaveFocus()
    expect(screen.queryByRole('listbox')).not.toBeInTheDocument()
    await user.click(trigger); await user.type(screen.getByRole('combobox', { name: 'Търсене: QA selector' }), 'absent')
    expect(screen.getByText('Няма резултати')).toBeVisible()
    await user.keyboard('{Escape}')
    expect(trigger).toHaveFocus()
  })
  it('portals outside a scroll container, responds to mouse and respects disabled state', async () => {
    const user = userEvent.setup(), changed = vi.fn()
    const { container } = render(<div style={{ overflow: 'hidden' }}><Select label="QA portal" value="a" onChange={changed} options={[{ value: 'a', label: 'Alpha' }, { value: 'b', label: 'Beta' }]} /><Select label="QA disabled" value="" disabled onChange={changed} options={[]} /></div>)
    expect(screen.getByRole('combobox', { name: 'QA disabled' })).toBeDisabled()
    await user.click(screen.getByRole('combobox', { name: 'QA portal' }))
    expect(container.contains(screen.getByRole('listbox'))).toBe(false)
    await user.click(screen.getByRole('option', { name: 'Beta' }))
    expect(changed).toHaveBeenCalledWith('b')
    expect(screen.queryByRole('listbox')).not.toBeInTheDocument()
  })
})

describe('domain status semantics', () => {
  it('uses distinct meanings, icons and localized labels with neutral legacy fallback', () => {
    expect(statusTone('COMPLETED', 'repair')).toBe('success')
    expect(statusTone('ISSUED')).toBe('info')
    expect(statusTone('REPAIR')).toBe('attention')
    expect(statusTone('WAITING_APPROVAL', 'part')).toBe('neutral')
    expect(statusTone('REJECTED', 'part')).toBe('neutral')
    expect(statusTone('LEGACY')).toBe('neutral')
    const { container } = render(<I18nProvider><StatusBadge status="READY" /><StatusBadge status="LEGACY" /><StatusBadge status="COMPLETED" domain="repair" /></I18nProvider>)
    expect(screen.getByText('LEGACY')).toBeVisible()
    expect(container.querySelectorAll('.ac-status svg')).toHaveLength(3)
    expect(container.querySelector('[data-status-domain=repair]')).toHaveClass('ac-status-success')
  })
})
