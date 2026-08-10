import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { IndustrialRepairs } from './IndustrialPlatform'
import { I18nProvider } from './i18n'
import type { RepairCase } from './types'

function json(value: unknown, status = 200): Response {
  return new Response(JSON.stringify(value), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

function repair(overrides: Partial<RepairCase> = {}): RepairCase {
  return {
    id: 41,
    repair_reference: 'REP-2026-000041',
    machine_id: 7,
    machine_number: '12',
    machine_name: 'Falch 500 bar',
    reported_problem: 'Контролен проблем',
    condition_before: 'Приета за диагностика',
    status: 'ACCEPTED',
    total_work_minutes: 0,
    participant_total_minutes: 0,
    cleaning_required: false,
    test_required: true,
    participants: [],
    events: [
      {
        id: 1,
        event_type: 'RETURN_DIRECTED_TO_REPAIR',
        status_after: 'ACCEPTED',
        user_id: 1,
        created_at: '2026-08-09T10:00:00Z',
      },
      {
        id: 2,
        event_type: 'WAITING_PARTS',
        status_after: 'WAITING_PARTS',
        user_id: 1,
        created_at: '2026-08-09T10:01:00Z',
      },
    ],
    parts_used: [],
    attachments: [],
    generated_documents: [],
    opened_at: '2026-08-09T10:00:00Z',
    ...overrides,
  }
}

describe('ремонтен работен процес', () => {
  beforeEach(() => {
    localStorage.clear()
    localStorage.setItem('assetcore_user', JSON.stringify({
      role: 'mechanic',
      permissions: ['repairs.view', 'repairs.create', 'repairs.edit', 'repairs.complete', 'parts.view', 'documents.view'],
    }))
  })

  afterEach(() => vi.unstubAllGlobals())

  it('показва точно четири етапа, само текущите полета и пази draft при conflict', async () => {
    const current = repair()
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input)
      if (path.endsWith('/api/repair-cases') && !init?.method) return json([current])
      if (path.endsWith('/api/machines')) return json([])
      if (path.endsWith('/api/repair-cases/41') && init?.method === 'PATCH') {
        return json({
          detail: {
            code: 'repair_stage_requirements_missing',
            message: 'За преминаване към Диагностика попълнете състоянието при приемане.',
          },
        }, 409)
      }
      if (path.endsWith('/api/repair-cases/41')) return json(current)
      if (path.includes('/api/catalog/parts?verified_only=true&machine_id=7')) return json([])
      throw new Error(`Unexpected request: ${path}`)
    })
    vi.stubGlobal('fetch', fetchMock)

    render(<I18nProvider initialLocale="bg"><IndustrialRepairs /></I18nProvider>)
    await userEvent.click(await screen.findByRole('button', { name: /Falch 500 bar/ }))

    expect(await screen.findByText('Върната директно за ремонт')).toBeInTheDocument()
    expect(screen.queryByText('RETURN_DIRECTED_TO_REPAIR')).not.toBeInTheDocument()
    expect(screen.queryByText('WAITING_PARTS')).not.toBeInTheDocument()
    for (const stage of ['Приета', 'Диагностика', 'В ремонт', 'Завършена']) {
      expect(screen.getAllByText(stage).length).toBeGreaterThan(0)
    }
    expect(screen.queryByLabelText('Диагностика')).not.toBeInTheDocument()
    expect(screen.queryByText('Използвани и сменени части')).not.toBeInTheDocument()
    expect(screen.getByText('Хронология')).toBeInTheDocument()

    const condition = screen.getByLabelText('Състояние преди ремонта')
    await userEvent.clear(condition)
    await userEvent.type(condition, 'Ново контролно състояние')
    expect(screen.getByRole('button', { name: 'Запази' })).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Запази и продължи към Диагностика' }))

    expect(await screen.findByText('За преминаване към Диагностика попълнете състоянието при приемане.')).toBeInTheDocument()
    expect(condition).toHaveValue('Ново контролно състояние')
    const patchCall = fetchMock.mock.calls.find(([, init]) => init?.method === 'PATCH')
    expect(JSON.parse(String(patchCall?.[1]?.body))).toMatchObject({
      status: 'DIAGNOSIS',
      condition_before: 'Ново контролно състояние',
    })
  })

  it('отваря финалната стъпка само чрез Запази и продължи', async () => {
    let current = repair({
      status: 'REPAIRING',
      diagnosis: 'Контролна диагностика',
      required_work: 'Контролна необходима работа',
      diagnosis_minutes: 20,
    })
    const patchBodies: Array<Record<string, unknown>> = []
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input)
      if (path.endsWith('/api/repair-cases') && !init?.method) return json([current])
      if (path.endsWith('/api/machines')) return json([])
      if (path.endsWith('/api/repair-cases/41') && init?.method === 'PATCH') {
        const body = JSON.parse(String(init.body)) as Record<string, unknown>
        patchBodies.push(body)
        current = repair({
          ...current,
          work_performed: String(body.work_performed ?? current.work_performed ?? ''),
          repair_minutes: Number(body.repair_minutes ?? current.repair_minutes ?? 0),
          events: body.advance_to_final
            ? [...current.events, {
              id: 8,
              event_type: 'REPAIR_ACTION',
              status_after: 'REPAIRING',
              structured_data: { wizard_stage: 'COMPLETION' },
              user_id: 1,
              created_at: '2026-08-09T10:10:00Z',
            }]
            : current.events,
        })
        return json(current)
      }
      if (path.endsWith('/api/repair-cases/41')) return json(current)
      if (path.includes('/api/catalog/parts?verified_only=true&machine_id=7')) return json([])
      throw new Error(`Unexpected request: ${path}`)
    })
    vi.stubGlobal('fetch', fetchMock)

    render(<I18nProvider initialLocale="bg"><IndustrialRepairs /></I18nProvider>)
    await userEvent.click(await screen.findByRole('button', { name: /Falch 500 bar/ }))
    await userEvent.type(await screen.findByLabelText('Извършена работа'), 'Извършена контролна работа')
    await userEvent.type(screen.getByLabelText('Реално време за ремонт (минути)'), '30')

    await userEvent.click(screen.getByRole('button', { name: 'Запази' }))
    await waitFor(() => expect(patchBodies).toHaveLength(1))
    expect(patchBodies[0]).not.toHaveProperty('advance_to_final')
    expect(screen.queryByRole('button', { name: 'Завърши ремонта и създай протокол' })).not.toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: 'Запази и продължи към Завършване' }))
    await waitFor(() => expect(patchBodies).toHaveLength(2))
    expect(patchBodies[1]).toMatchObject({ advance_to_final: true })
    expect(await screen.findByRole('button', { name: 'Завърши ремонта и създай протокол' })).toBeInTheDocument()
  })

  it('не изпраща duplicate participant при двоен click и показва записания участник', async () => {
    let participantAdded = false
    let participantPosts = 0
    const baseOverrides: Partial<RepairCase> = {
      status: 'REPAIRING',
      work_performed: 'Контролна работа',
      repair_minutes: 30,
      events: [{
        id: 3,
        event_type: 'REPAIR_ACTION',
        status_after: 'REPAIRING',
        structured_data: { wizard_stage: 'COMPLETION' },
        user_id: 1,
        created_at: '2026-08-09T10:02:00Z',
      }],
    }
    const base = repair(baseOverrides)
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input)
      const current = participantAdded
        ? repair({ ...baseOverrides, participant_total_minutes: 75, participants: [{
          id: 9,
          repair_id: 41,
          full_name: 'Иван Иванов Иванов',
          job_title: 'Електротехник',
          contribution: 'Електрическа диагностика',
          minutes_worked: 75,
          created_by_id: 1,
          created_at: '2026-08-09T10:05:00Z',
        }] })
        : base
      if (path.endsWith('/api/repair-cases') && !init?.method) return json([current])
      if (path.endsWith('/api/machines')) return json([])
      if (path.endsWith('/api/repair-cases/41/participants') && init?.method === 'POST') {
        participantPosts += 1
        participantAdded = true
        return json({ id: 9 }, 201)
      }
      if (path.endsWith('/api/repair-cases/41')) return json(current)
      if (path.includes('/api/catalog/parts?verified_only=true&machine_id=7')) return json([])
      throw new Error(`Unexpected request: ${path}`)
    })
    vi.stubGlobal('fetch', fetchMock)

    render(<I18nProvider initialLocale="bg"><IndustrialRepairs /></I18nProvider>)
    await userEvent.click(await screen.findByRole('button', { name: /Falch 500 bar/ }))
    await userEvent.type(await screen.findByLabelText('Три имена'), 'Иван Иванов Иванов')
    await userEvent.type(screen.getByLabelText('Длъжност'), 'Електротехник')
    await userEvent.type(screen.getByLabelText('Участие в ремонта'), 'Електрическа диагностика')
    await userEvent.type(screen.getByLabelText('Часове'), '1')
    await userEvent.type(screen.getByLabelText('Минути'), '15')
    await userEvent.dblClick(screen.getByRole('button', { name: 'Добави участник' }))

    await waitFor(() => expect(participantPosts).toBe(1))
    expect(await screen.findByText('Иван Иванов Иванов')).toBeInTheDocument()
    const postCall = fetchMock.mock.calls.find(([path, init]) => String(path).endsWith('/participants') && init?.method === 'POST')
    expect(JSON.parse(String(postCall?.[1]?.body))).toMatchObject({ minutes_worked: 75 })
    expect(screen.getAllByText(/1 ч 15 мин/).length).toBeGreaterThanOrEqual(2)
  })

  it('изисква потвърждение и изпраща точния финален action от REPAIRING', async () => {
    let completed = false
    const finalDraft = repair({
      status: 'REPAIRING', work_performed: 'Извършена работа', repair_minutes: 45,
      test_method: 'Функционален тест', test_passed: true, test_details: 'Успешен тест',
      testing_minutes: 15, condition_after: 'Изправна', result: 'Ремонтът е завършен',
    })
    const completedRepair = repair({
      ...finalDraft, status: 'COMPLETED',
      generated_documents: [{
        id: 77, document_number: 'REP-2026-000041', document_type: 'REPAIR_PROTOCOL',
        format: 'docx', filename: 'REP-2026-000041.docx', created_at: '2026-08-09T11:00:00Z',
        download_endpoint: '/generated-documents/77/download',
      }],
    })
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input)
      if (path.endsWith('/api/repair-cases') && !init?.method) return json([completed ? completedRepair : finalDraft])
      if (path.endsWith('/api/machines')) return json([])
      if (path.endsWith('/api/repair-cases/41') && init?.method === 'PATCH') {
        completed = true
        return json(completedRepair)
      }
      if (path.endsWith('/api/repair-cases/41')) return json(completed ? completedRepair : finalDraft)
      if (path.includes('/api/catalog/parts?verified_only=true&machine_id=7')) return json([])
      throw new Error(`Unexpected request: ${path}`)
    })
    const confirmMock = vi.spyOn(window, 'confirm').mockReturnValueOnce(false).mockReturnValueOnce(true)
    vi.stubGlobal('fetch', fetchMock)

    render(<I18nProvider initialLocale="bg"><IndustrialRepairs /></I18nProvider>)
    await userEvent.click(await screen.findByRole('button', { name: /Falch 500 bar/ }))
    const finish = await screen.findByRole('button', { name: 'Завърши ремонта и създай протокол' })
    await userEvent.click(finish)
    expect(fetchMock.mock.calls.filter(([, init]) => init?.method === 'PATCH')).toHaveLength(0)
    await userEvent.click(finish)
    await waitFor(() => expect(fetchMock.mock.calls.filter(([, init]) => init?.method === 'PATCH')).toHaveLength(1))
    const patch = fetchMock.mock.calls.find(([, init]) => init?.method === 'PATCH')
    expect(JSON.parse(String(patch?.[1]?.body))).toMatchObject({ status: 'COMPLETED' })
    expect(confirmMock).toHaveBeenCalledTimes(2)
    expect((await screen.findAllByText('REP-2026-000041')).length).toBeGreaterThanOrEqual(2)
  })
})
