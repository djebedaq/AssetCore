import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { ApiError } from './api'
import {
  BatchProgressCard,
  BatchDetailsPanel,
  CancelBatchModal,
  ConfirmationSummary,
  ConflictNotice,
  IssueModal,
  IssueResult,
  IssueSelectionList,
  ReturnModal,
} from './BulkTransfers'
import type { BatchDetails, BulkIssueResult, TransferAvailability } from './types'

const available: TransferAvailability = {
  machine_id: 1, machine_number: '4', brand: 'CombiJet', pressure_bar: 500,
  status: 'READY', location: 'Цех', available: true, returnable: false,
}
const unavailable: TransferAvailability = {
  machine_id: 2, machine_number: '7', brand: 'Falch', pressure_bar: 1000,
  status: 'ISSUED', location: 'Док 2', available: false, returnable: true,
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
    render(<IssueModal items={[available]} locations={[{ id: 1, name: 'Цех', is_active: true }]} onClose={vi.fn()} onComplete={vi.fn()} />)
    await userEvent.click(screen.getByLabelText('Машина №4'))
    expect(screen.getByText('Избрани машини: 1')).toBeVisible()
    await userEvent.type(screen.getByLabelText('Собствено име'), 'Иван')
    await userEvent.type(screen.getByLabelText('Бащино име'), 'Иванов')
    await userEvent.type(screen.getByLabelText('Фамилия'), 'Петров')
    await userEvent.selectOptions(screen.getByLabelText('Системно местоположение'), '1')
    await userEvent.type(screen.getByLabelText('Ще се използва за'), 'Проверена производствена задача')
    await userEvent.type(screen.getByLabelText('Състояние при издаване'), 'Изправна')
    await userEvent.click(screen.getByRole('button', { name: 'Преглед и потвърждение' }))
    expect(screen.getByRole('heading', { name: 'Потвърждение на издаването' })).toBeVisible()
    expect(screen.getByText(/№4/)).toBeVisible()
    expect(screen.getByRole('button', { name: 'Потвърди издаването' })).toBeEnabled()
  })

  it('показва структуриран конфликт без raw JSON', () => {
    const error = new ApiError(409, {
      code: 'issue_conflict', message: 'Машината не може да бъде издадена.',
      conflicts: [{ machine_number: '7', status: 'Издадена', protocol_number: 'HPWJ-7' }],
    })
    render(<ConflictNotice error={error} />)
    expect(screen.getByRole('alert')).toHaveTextContent('Една или повече машини не могат да бъдат издадени.')
    expect(screen.getByRole('alert')).toHaveTextContent('протокол HPWJ-7')
    expect(screen.queryByText(/issue_conflict/)).not.toBeInTheDocument()
  })

  it('показва диагностичния код и точния етап при вътрешна грешка', () => {
    const error = new ApiError(500, {
      code: 'bulk_return_internal_error',
      message: 'Приемането не можа да бъде завършено. Диагностичен код: RET-ABC123.',
      diagnostic_id: 'RET-ABC123',
      stage: 'prepare_return_batch_signing',
    })
    render(<ConflictNotice error={error} />)
    expect(screen.getByRole('alert')).toHaveTextContent('Приемането не можа да бъде завършено.')
    expect(screen.getByRole('alert')).toHaveTextContent('RET-ABC123')
    expect(screen.getByRole('alert')).toHaveTextContent('prepare_return_batch_signing')
  })

  it('показва частично върната партида и оставащи машини', () => {
    render(<BatchProgressCard batch={{
      batch_id: 1, batch_reference: 'HPWJ-B-1', status: 'PARTIALLY_RETURNED',
      total_machines: 3, returned_machines: 1, still_issued_machines: 2,
      awaiting_signature_machines: 0,
      machine_numbers: ['4', '7', '10'],
    }} />)
    expect(screen.getByText('Частично върната партида')).toBeVisible()
    expect(screen.getByText(/Все още издадени: 2/)).toBeVisible()
    expect(screen.getByRole('heading', { name: '№4, №7, №10' })).toBeVisible()
  })

  it('предлага само Готова или За ремонт при връщане', async () => {
    render(<ReturnModal items={[unavailable]} onClose={vi.fn()} onComplete={vi.fn()} />)
    await userEvent.click(screen.getByLabelText('Връщане на машина №7'))
    expect(screen.getByRole('radio', { name: 'Готова' })).toBeChecked()
    expect(screen.getByRole('radio', { name: 'За ремонт' })).toBeVisible()
    expect(screen.queryByText('Следващ етап')).not.toBeInTheDocument()
  })

  it('разделя издаващия и връщащия протокол без фиктивен документ', () => {
    const details: BatchDetails = {
      batch_id: 1, batch_reference: 'HPWJ-B-1', status: 'ACTIVE', total_machines: 1,
      returned_machines: 0, still_issued_machines: 1, awaiting_signature_machines: 0,
      machine_numbers: ['4'], created_at: '2026-08-08T10:00:00Z', operation: 'ISSUE',
      zip_download_endpoint: '/zip',
      transfers: [{
        transfer_id: 1, machine_id: 1, machine_number: '4', machine_name: 'HPWJ №4', brand: 'CombiJet',
        pressure_bar: 500, protocol_number: 'HPWJ-1', is_active: true, issue_status: 'COMPLETED',
        return_status: null, current_status: 'ISSUED', documents: [],
        issue_documents: [{ id: 1, format: 'docx', filename: 'issue.docx', download_endpoint: '/issue' }],
        return_documents: [],
      }],
    }
    render(<BatchDetailsPanel details={details} onDownload={vi.fn()} />)
    expect(screen.getByText('Протокол за издаване')).toBeVisible()
    expect(screen.queryByText('Протокол за връщане')).not.toBeInTheDocument()
    expect(screen.getByText('Машината все още не е приета')).toBeVisible()
  })

  it('показва всички индивидуални протоколи и ZIP резултата', async () => {
    const onDownload = vi.fn()
    const result: BulkIssueResult = {
      message: 'Успешно', batch_id: 1, batch_reference: 'HPWJ-B-1',
      zip_download_endpoint: '/batch.zip',
      signing_tasks: [],
      transfers: [{
        transfer_id: 10, protocol_number: 'HPWJ-10', machine_id: 1, machine_number: '4',
        workflow_status: 'COMPLETED', official_document_id: 20, signing_tasks: [],
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

  it('анулира незавършена операция само след въведена причина', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(JSON.stringify({
      batch_id: 11,
      batch_reference: 'HPWJ-B-11',
      status: 'CANCELLED',
      cancelled_transfers: 3,
      invalidated_signing_sessions: 2,
      message: 'Незавършената операция е анулирана безопасно.',
    }), { status: 200, headers: { 'Content-Type': 'application/json' } }))
    const onCancelled = vi.fn()
    render(<CancelBatchModal batch={{
      batch_id: 11, batch_reference: 'HPWJ-B-11', operation: 'ISSUE',
      awaiting_signature_machines: 3, total_machines: 3,
    }} onClose={vi.fn()} onCancelled={onCancelled} />)

    const confirm = screen.getByRole('button', { name: 'Потвърди анулирането' })
    expect(confirm).toBeDisabled()
    await userEvent.type(screen.getByLabelText('Причина за анулиране'), 'Получателят отказа подписване')
    expect(confirm).toBeEnabled()
    await userEvent.click(confirm)

    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith('/api/transfer-batches/11/cancel', expect.objectContaining({
      method: 'POST',
      body: JSON.stringify({ reason: 'Получателят отказа подписване' }),
    })))
    expect(await screen.findByText('Незавършената операция е анулирана безопасно.')).toBeVisible()
    expect(screen.getByText('3')).toBeVisible()
    expect(onCancelled).toHaveBeenCalledWith(expect.objectContaining({ status: 'CANCELLED' }))
    fetchMock.mockRestore()
  })

  it('обяснява, че анулираното приемане запазва активното издаване', () => {
    render(<CancelBatchModal batch={{
      batch_id: 12, batch_reference: 'HPWJ-R-12', operation: 'RETURN',
      awaiting_signature_machines: 2, total_machines: 2,
    }} onClose={vi.fn()} onCancelled={vi.fn()} />)
    expect(screen.getByText(/Първоначалното издаване остава валидно/)).toBeVisible()
  })

})
