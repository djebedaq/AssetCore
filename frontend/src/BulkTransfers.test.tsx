import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { ApiError } from './api'
import {
  BatchProgressCard,
  ConfirmationSummary,
  ConflictNotice,
  IssueModal,
  IssueResult,
  IssueSelectionList,
} from './BulkTransfers'
import type { BulkIssueResult, TransferAvailability } from './types'

const available: TransferAvailability = {
  machine_id: 1, machine_number: '4', brand: 'CombiJet', pressure_bar: 500,
  status: 'Готова', location: 'Цех', available: true,
}
const unavailable: TransferAvailability = {
  machine_id: 2, machine_number: '7', brand: 'Falch', pressure_bar: 1000,
  status: 'Издадена', location: 'Док 2', available: false,
  unavailable_reason: 'Машината има активно предаване.', protocol_number: 'HPWJ-1',
}

describe('групови предавания', () => {
  it('позволява избор само на налична машина', async () => {
    const onToggle = vi.fn()
    render(<IssueSelectionList items={[available, unavailable]} selected={new Set()} onToggle={onToggle} />)
    await userEvent.click(screen.getByLabelText('Машина №4'))
    expect(onToggle).toHaveBeenCalledWith(available)
    expect(screen.getByLabelText('Машина №7')).toBeDisabled()
    expect(screen.getByText('Машината има активно предаване.')).toBeVisible()
  })

  it('изисква confirmation стъпка и запазва избора', async () => {
    render(<IssueModal items={[available]} locations={[]} onClose={vi.fn()} onComplete={vi.fn()} />)
    await userEvent.click(screen.getByLabelText('Машина №4'))
    expect(screen.getByText('Избрани машини: 1')).toBeVisible()
    await userEvent.click(screen.getByRole('button', { name: 'Преглед и потвърждение' }))
    expect(screen.getByRole('heading', { name: 'Потвърждение на груповото издаване' })).toBeVisible()
    expect(screen.getByText(/№4/)).toBeVisible()
    expect(screen.getByRole('button', { name: 'Потвърди издаването' })).toBeEnabled()
  })

  it('показва структуриран конфликт без raw JSON', () => {
    const error = new ApiError(409, {
      code: 'issue_conflict', message: 'Машината не може да бъде издадена.',
      conflicts: [{ machine_number: '7', status: 'Издадена', protocol_number: 'HPWJ-7' }],
    })
    render(<ConflictNotice error={error} />)
    expect(screen.getByRole('alert')).toHaveTextContent('Машината не може да бъде издадена.')
    expect(screen.getByRole('alert')).toHaveTextContent('протокол HPWJ-7')
    expect(screen.queryByText(/issue_conflict/)).not.toBeInTheDocument()
  })

  it('показва частично върната партида и оставащи машини', () => {
    render(<BatchProgressCard batch={{
      batch_id: 1, batch_reference: 'HPWJ-B-1', status: 'Частично върната партида',
      total_machines: 3, returned_machines: 1, still_issued_machines: 2,
    }} />)
    expect(screen.getByText('Частично върната партида')).toBeVisible()
    expect(screen.getByText(/Все още издадени: 2/)).toBeVisible()
  })

  it('показва всички индивидуални протоколи и ZIP резултата', async () => {
    const onDownload = vi.fn()
    const result: BulkIssueResult = {
      message: 'Успешно', batch_id: 1, batch_reference: 'HPWJ-B-1',
      zip_download_endpoint: '/batch.zip',
      transfers: [{
        transfer_id: 10, protocol_number: 'HPWJ-10', machine_id: 1, machine_number: '4',
        documents: [
          { id: 1, format: 'docx', filename: 'HPWJ-10.docx', download_endpoint: '/docx' },
          { id: 2, format: 'pdf', filename: 'HPWJ-10.pdf', download_endpoint: '/pdf' },
        ],
      }],
    }
    render(<IssueResult result={result} onDownload={onDownload} />)
    expect(screen.getByText('Създадени протоколи')).toBeVisible()
    expect(screen.getByText('HPWJ-10')).toBeVisible()
    await userEvent.click(screen.getByRole('button', { name: /Изтегли всички протоколи ZIP/ }))
    expect(onDownload).toHaveBeenCalledWith('/batch.zip', 'HPWJ-B-1-protocols.zip')
  })

  it('обобщава избраните машини преди потвърждение', () => {
    render(<ConfirmationSummary title="Обобщение" machineNumbers={['4', '5']} rows={[["Място", "Док 2"]]} />)
    expect(screen.getByText(/Избрани машини \(2\)/)).toBeVisible()
    expect(screen.getByText('№4, №5')).toBeVisible()
    expect(screen.getByText('Док 2')).toBeVisible()
  })
})
