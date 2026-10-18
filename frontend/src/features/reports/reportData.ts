import { useEffect, useState } from 'react'
import { api } from '../../api'
import { useI18n } from '../../i18n'
import type { PageData } from '../../ui/workspace'
import labels from './labels.json'

export type Section = 'overview' | 'usage' | 'repairs' | 'requests'
export type Kind = 'machines' | 'usage' | 'repairs' | 'requests'
export type Asset = { id: number; inventory_number: string; name: string; brand: string; model: string | null; category_id: number | null; name_bg: string | null; name_en: string | null; name_ru: string | null; status: string; location: string | null }
export type Metric = { key: string; value: number | null; unit: string; previous: number | null; change: number | null; percent: number | null; sample: number | null; drill: string | null; current: boolean }
export type RecordRow = { metric_date?: string | null; date_basis?: string; issue_count?: number; last_issued_at?: string; id: number; original_id?: number; is_active?: boolean; machine?: Asset | null; module?: 'transfers' | 'repairs' | 'parts'; machine_id?: number; inventory_number?: string; name?: string; status?: string; issue_status?: string; return_status?: string; protocol_number?: string; repair_reference?: string; official_number?: string; request_reference?: string; reported_problem?: string; part_name?: string; issued_at?: string; returned_at?: string; opened_at?: string; closed_at?: string; created_at?: string; ordered_at?: string; elapsed_days?: number; remaining_lines?: number; batch_id?: number; remaining?: { id: number; description: string; quantity: string; unit: string | null }[] }
export type Reason = { code: string; count: number; days: number; previous?: number }
export type Attention = { machine: Asset; reasons: Reason[]; open_count: number }
export type MachineStats = { machine: Asset; metrics: Partial<Record<Section, Metric[]>> }
export type Report = { section: string; digests?: Record<string, string>; thresholds?: { window_days: number; delivery_days: number }; generated_at: string; filters: { date_from: string; date_to: string }; previous_filters: { date_from: string; date_to: string }; capabilities: Record<Exclude<Kind, 'machines'>, boolean>; current: Metric[]; metrics: Metric[]; categories: { id: number | null; name_bg: string | null; name_en: string | null; name_ru: string | null; total: number; statuses: Record<string, number>; metrics?: Record<string, number> }[]; trends: ({ period: string } & Record<string, number | string>)[]; rankings: MachineStats[]; ranking_kind: Kind; ranking_key: string; attention: Attention[]; attention_total: number; machines: MachineStats[]; records: PageData<RecordRow>; delayed: PageData<RecordRow> | null; parts_total?: number; articles_total?: number; parts: { id: number; repair_id: number; description: string; part_number: string | null; quantity: number; unit: string | null }[]; articles: { line_id: number; request_id: number; description: string; part_number: string | null; quantity: string; unit: string | null; requests: number }[] }
export type Filters = { preset: string; from: string; to: string; category: string; machine: string; q: string }
export type Drill = { kind: Kind; metric: string; machine?: Asset; attention?: Attention; from?: string; to?: string }

export function useReportText() {
  const { locale } = useI18n()
  return (key: string, values: Record<string, string | number | undefined> = {}) => {
    let value = (labels as Record<string, string[]>)[key]?.[['bg', 'en', 'ru'].indexOf(locale)] || key
    Object.entries(values).forEach(([name, content]) => { value = value.replaceAll(`{{${name}}}`, String(content ?? '')) })
    return value
  }
}
export function useReportDate() {
  const { locale } = useI18n()
  return (value: string) => {
    const instant = value.includes('T') && !/(Z|[+-]\d{2}:\d{2})$/.test(value) ? value + 'Z' : value
    return new Intl.DateTimeFormat(locale, { timeZone: 'Europe/Sofia', dateStyle: 'medium', timeStyle: 'short' }).format(new Date(instant))
  }
}
export function period(preset: string) {
  const parts = new Intl.DateTimeFormat('en-CA', { timeZone: 'Europe/Sofia', year: 'numeric', month: '2-digit', day: '2-digit' }).formatToParts(new Date())
  const part = (name: string) => parts.find(p => p.type === name)?.value
  const to = `${part('year')}-${part('month')}-${part('day')}`
  const end = new Date(`${to}T12:00:00Z`)
  if (preset === '365') { end.setUTCFullYear(end.getUTCFullYear() - 1); end.setUTCDate(end.getUTCDate() + 1) }
  else end.setUTCDate(end.getUTCDate() - Number(preset) + 1)
  return { from: end.toISOString().slice(0, 10), to }
}
export function useReport(path: string | null) {
  const [state, setState] = useState<{ data: Report | null; error: boolean; loading: boolean }>({ data: null, error: false, loading: true })
  useEffect(() => {
    const controller = new AbortController()
    setState({ data: null, error: false, loading: !!path })
    if (path) void api<Report>(path, { signal: controller.signal }).then(data => { if (!controller.signal.aborted) setState({ data, error: false, loading: false }) })
      .catch(() => { if (!controller.signal.aborted) setState({ data: null, error: true, loading: false }) })
    return () => controller.abort()
  }, [path])
  return state
}
