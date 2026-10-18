import { Bar, BarChart, CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { useI18n } from '../../i18n'
import { useReportText, type Kind, type MachineStats, type Report, type Section } from './reportData'
export function Trends({ data, drill }: { data: Report; drill: (kind: Kind, metric: string, from: string, to: string) => void }) {
  const text = useReportText()
  const keys = ['issues', 'completed_cycles', 'opened', 'closed', 'created', 'receipts'].filter(key => data.capabilities[key === 'issues' || key === 'completed_cycles' ? 'usage' : key === 'opened' || key === 'closed' ? 'repairs' : 'requests'])
  const colors = ['#0e7490', '#15803d', '#ea580c', '#7c3aed', '#2563eb', '#be185d']
  function choose(label: string, key: string) {
    const monthly = label.length === 7, start = `${label}${monthly ? '-01' : ''}`, end = new Date(`${label}${monthly ? '-01' : ''}T12:00:00Z`)
    if (monthly) { end.setUTCMonth(end.getUTCMonth() + 1); end.setUTCDate(0) } else end.setUTCDate(end.getUTCDate() + 6)
    drill(key === 'issues' || key === 'completed_cycles' ? 'usage' : key === 'opened' || key === 'closed' ? 'repairs' : 'requests', key, start < data.filters.date_from ? data.filters.date_from : start, end.toISOString().slice(0, 10) > data.filters.date_to ? data.filters.date_to : end.toISOString().slice(0, 10))
  }
  return <section className="panel reports-chart"><h3>{text('trends')}</h3><div className="reports-chart-canvas" role="img" aria-label={text('trends')}><ResponsiveContainer width="100%" height={270}><LineChart data={data.trends} margin={{ top: 12, right: 12, left: -22, bottom: 4 }} accessibilityLayer>
    <CartesianGrid strokeDasharray="3 3" vertical={false} /><XAxis dataKey="period" tick={{ fontSize: 11 }} minTickGap={28} /><YAxis allowDecimals={false} tick={{ fontSize: 11 }} /><Tooltip /><Legend wrapperStyle={{ fontSize: 12 }} />
    {keys.map((key, index) => <Line key={key} dataKey={key} name={text(key)} stroke={colors[index]} strokeWidth={2} connectNulls isAnimationActive={false} activeDot={{ r: 6 }} />)}
  </LineChart></ResponsiveContainer></div><details><summary>{text('chartTable')}</summary><div className="reports-table"><table><thead><tr><th>{text('period')}</th>{keys.map(key => <th key={key}>{text(key)}</th>)}</tr></thead><tbody>{data.trends.map(row => <tr key={row.period}><th>{row.period}</th>{keys.map(key => <td key={key}>{key === 'receipts' ? row[key] || 0 : <button type="button" className="link" onClick={() => choose(row.period, key)}>{row[key] || 0}</button>}</td>)}</tr>)}</tbody></table></div></details></section>
}
export function Ranking({ data, drill }: { data: Report; drill: (item: MachineStats) => void }) {
  const text = useReportText(), { number } = useI18n()
  const rows = data.rankings.map(item => ({ name: `№${item.machine.inventory_number}`, value: item.metrics[data.ranking_kind as Section]?.find(m => m.key === data.ranking_key)?.value || 0, item }))
  return <section className="panel reports-chart"><h3>{text(data.ranking_kind === 'repairs' ? 'rankingRepairs' : data.ranking_kind === 'usage' ? 'rankingUsage' : 'rankingRequests')}</h3><div className="reports-chart-canvas" role="img" aria-label={text('chartTable')}><ResponsiveContainer width="100%" height={Math.max(170, rows.length * 32)}><BarChart data={rows} layout="vertical" margin={{ left: 0, right: 20 }} accessibilityLayer><XAxis type="number" allowDecimals={false} /><YAxis type="category" dataKey="name" width={65} tick={{ fontSize: 11 }} /><Tooltip /><Bar dataKey="value" name={text(data.ranking_key)} fill="#0e7490" radius={[0, 4, 4, 0]} isAnimationActive={false} onClick={row => { if (row.item) drill(row.item) }} /></BarChart></ResponsiveContainer></div><div className="reports-ranking-list">{rows.map(row => <button type="button" key={row.item.machine.id} onClick={() => drill(row.item)}><span>№{row.item.machine.inventory_number} · {row.item.machine.name}</span><strong>{number(row.value)}</strong></button>)}</div></section>
}
