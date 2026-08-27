import { useEffect, useState } from 'react'
import { Archive, ChevronRight, FileText, PackageCheck, Search, ShieldCheck, Wrench, X } from 'lucide-react'
import { api, downloadApiFile } from '../../api'
import { DOCUMENT_KEYS, translatedCode } from '../../industrialUi'
import { statusText, useI18n } from '../../i18n'
import type { GlobalSearchResults } from '../../types'

export function GlobalSearchBox({ onMachine }: { onMachine: (machineId: number) => void }) {
  const { t } = useI18n()
  const [query, setQuery] = useState('')
  const [results, setResults] = useState<GlobalSearchResults | null>(null)
  const [open, setOpen] = useState(false)

  useEffect(() => {
    if (query.trim().length < 2) {
      setResults(null)
      return
    }
    const timer = window.setTimeout(() => {
      void api<GlobalSearchResults>(`/search?q=${encodeURIComponent(query.trim())}`)
        .then((data) => { setResults(data); setOpen(true) })
        .catch(() => setResults(null))
    }, 250)
    return () => window.clearTimeout(timer)
  }, [query])

  const total = results
    ? results.machines.length + results.parts.length + results.documents.length + results.repairs.length + results.part_requests.length + results.transfers.length + results.generated_documents.length
    : 0
  return (
    <div className="global-search">
      <Search size={17} />
      <input aria-label={t('global.search')} placeholder={t('global.placeholder')} value={query} onChange={(event) => setQuery(event.target.value)} onFocus={() => setOpen(true)} />
      {open && query.trim().length >= 2 && (
        <div className="global-results">
          <div className="global-results-head"><b>{t('global.results', { count: total })}</b><button onClick={() => setOpen(false)} aria-label={t('common.close')}><X size={16} /></button></div>
          {!total && <div className="empty-state">{t('global.empty')}</div>}
          {results?.machines.map((item) => <button key={`m-${item.id}`} onClick={() => { onMachine(item.id); setOpen(false) }}><span><b>{item.name}</b><small>{item.brand} · №{item.inventory_number}</small></span><span className="badge">{statusText(t, item.status)}</span></button>)}
          {results?.parts.map((item) => <div className="global-result-row" key={`p-${item.id}`}><PackageCheck size={17} /><span><b>{item.part_number}</b><small>{item.description}</small></span>{item.is_verified && <ShieldCheck size={16} />}</div>)}
          {results?.documents.map((item) => <button key={`d-${item.id}`} onClick={() => { void downloadApiFile(item.download_endpoint, item.title); setOpen(false) }}><FileText size={17} /><span><b>{item.title}</b><small>{item.brand} · {item.category}</small></span></button>)}
          {results?.repairs.map((item) => <div className="global-result-row" key={`r-${item.id}`}><Wrench size={17} /><span><b>{item.repair_reference}</b><small>№{item.machine_number} · {item.reported_problem}</small></span><span className="badge">{statusText(t, item.status, 'repair')}</span></div>)}
          {results?.part_requests.map((item) => <div className="global-result-row" key={`q-${item.id}`}><Archive size={17} /><span><b>{item.request_reference}</b><small>{item.part_name}</small></span><span className="badge">{statusText(t, item.status, 'part')}</span></div>)}
          {results?.transfers.map((item) => <div className="global-result-row" key={`t-${item.id}`}><ChevronRight size={17} /><span><b>{item.protocol_number}</b><small>№{item.machine_number} · {item.batch_reference || item.location_text || item.company_unit || t('common.notSpecified')}</small></span><span className="badge">{item.is_active ? t('global.activeTransfer') : t('global.closedTransfer')}</span></div>)}
          {results?.generated_documents.map((item) => <button key={`g-${item.id}`} onClick={() => { void downloadApiFile(item.download_endpoint, item.filename); setOpen(false) }}><FileText size={17} /><span><b>{item.document_number}</b><small>{translatedCode(t, item.document_type, DOCUMENT_KEYS)} · {item.format.toUpperCase()}</small></span></button>)}
        </div>
      )}
    </div>
  )
}
