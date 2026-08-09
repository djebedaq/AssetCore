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

  it('показва българска хронология и пази въведените данни при business conflict', async () => {
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
    expect(screen.getAllByText('Чака части')).not.toHaveLength(0)
    expect(screen.queryByText('RETURN_DIRECTED_TO_REPAIR')).not.toBeInTheDocument()
    expect(screen.queryByText('WAITING_PARTS')).not.toBeInTheDocument()
    expect(screen.getByText('7. Използвани и сменени части')).toBeInTheDocument()
    expect(screen.getByText('10. Хронология')).toBeInTheDocument()

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
      inspection_complete: true,
      condition_before: 'Ново контролно състояние',
    })
  })

  it('не изпраща duplicate participant при двоен click и показва записания участник', async () => {
    let participantAdded = false
    let participantPosts = 0
    const base = repair()
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input)
      const current = participantAdded
        ? repair({ participants: [{
          id: 9,
          repair_id: 41,
          full_name: 'Иван Иванов Иванов',
          job_title: 'Електротехник',
          contribution: 'Електрическа диагностика',
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
    await userEvent.dblClick(screen.getByRole('button', { name: 'Добави участник' }))

    await waitFor(() => expect(participantPosts).toBe(1))
    expect(await screen.findByText('Иван Иванов Иванов')).toBeInTheDocument()
  })
})
