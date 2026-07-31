import { useEffect, useMemo, useState } from 'react'
import type { FormEvent, ReactNode } from 'react'
import { Archive, CheckCircle2, Download, RotateCcw, Search, Send, X } from 'lucide-react'
import { ApiError, api, downloadApiFile } from './api'
import type {
  BatchDetails,
  BatchProgress,
  BulkIssueResult,
  BulkReturnResult,
  Location,
  ProtocolDocument,
  TransferAvailability,
} from './types'

type BulkTransfersProps = { onChanged: () => void }

type IssueForm = {
  company_unit: string; vessel: string; location_text: string; location_id: string;
  handed_over_by: string; accepted_by: string; equipment: string;
  condition_text: string; remarks: string
}

const EMPTY_ISSUE_FORM: IssueForm = {
  company_unit: '', vessel: '', location_text: '', location_id: '', handed_over_by: '',
  accepted_by: '', equipment: '', condition_text: '', remarks: '',
}

type ReturnDraft = {
  transfer_id: number; machine_id: number; condition_text: string; result_text: string;
  notes: string; returned_by: string; accepted_by: string; location_id: string; next_status: string
}

const RETURN_STATUSES = [
  'Върната', 'За преглед', 'Почистване', 'В ремонт', 'Чака одобрение', 'Чака части', 'Тестване',
]

function ModalShell({ title, onClose, children, wide = false }: { title: string; onClose: () => void; children: ReactNode; wide?: boolean }) {
  return <div className="modal-bg" role="presentation">
    <section className={`modal bulk-modal ${wide ? 'bulk-modal-wide' : ''}`} role="dialog" aria-modal="true" aria-label={title}>
      <div className="modal-head"><h3>{title}</h3><button onClick={onClose} aria-label="Затвори"><X /></button></div>
      {children}
    </section>
  </div>
}

export function ConflictNotice({ error }: { error: Error | null }) {
  if (!error) return null
  const conflicts = error instanceof ApiError && Array.isArray(error.data.conflicts)
    ? error.data.conflicts as Array<Record<string, unknown>> : []
  return <div className="conflict-notice" role="alert">
    <strong>{error.message}</strong>
    {conflicts.length > 0 && <ul>{conflicts.map((conflict, index) => <li key={String(conflict.transfer_id || conflict.machine_id || index)}>
      <b>Машина №{String(conflict.machine_number || '—')}</b>
      {conflict.status ? ` · ${String(conflict.status)}` : ''}
      {conflict.protocol_number ? ` · протокол ${String(conflict.protocol_number)}` : ''}
      {conflict.issued_at ? ` · издадена ${new Date(String(conflict.issued_at)).toLocaleString('bg-BG')}` : ''}
      {conflict.current_recipient_or_location ? ` · ${String(conflict.current_recipient_or_location)}` : ''}
    </li>)}</ul>}
  </div>
}

export function IssueSelectionList({ items, selected, onToggle }: {
  items: TransferAvailability[]; selected: Set<number>; onToggle: (item: TransferAvailability) => void
}) {
  if (!items.length) return <div className="empty-state">Няма машини, отговарящи на търсенето.</div>
  return <div className="selection-list">{items.map(item => <label
    key={item.machine_id}
    className={`selection-row ${item.available ? '' : 'unavailable'} ${selected.has(item.machine_id) ? 'selected' : ''}`}
  >
    <input
      type="checkbox"
      aria-label={`Машина №${item.machine_number}`}
      checked={selected.has(item.machine_id)}
      disabled={!item.available}
      onChange={() => onToggle(item)}
    />
    <span className="selection-main"><strong>HPWJ №{item.machine_number}</strong><small>{item.brand} · {item.pressure_bar} bar · {item.location || 'Не е определено'}</small></span>
    <span className={`availability-pill ${item.available ? 'available' : 'blocked'}`}>{item.available ? 'Налична' : 'Недостъпна'}</span>
    {!item.available && <small className="unavailable-reason">{item.unavailable_reason}</small>}
  </label>)}</div>
}

export function ConfirmationSummary({ title, machineNumbers, rows }: {
  title: string; machineNumbers: string[]; rows: Array<[string, string]>
}) {
  return <section className="confirmation-summary" aria-label={title}>
    <h4>{title}</h4>
    <p><b>Избрани машини ({machineNumbers.length}):</b> {machineNumbers.map(number => `№${number}`).join(', ')}</p>
    <dl>{rows.filter(([, value]) => value).map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{value}</dd></div>)}</dl>
  </section>
}

export function IssueResult({ result, onDownload }: {
  result: BulkIssueResult; onDownload: (path: string, filename: string) => void
}) {
  return <div className="operation-result" role="status">
    <CheckCircle2 size={36} />
    <h4>{result.message}</h4><p>Партида <b>{result.batch_reference}</b></p>
    <button className="primary" onClick={() => onDownload(result.zip_download_endpoint, `${result.batch_reference}-protocols.zip`)}><Archive size={17} />Изтегли всички протоколи ZIP</button>
    <div className="result-protocols"><h4>Създадени протоколи</h4>{result.transfers.map(item => <div key={item.transfer_id}>
      <span><b>Машина №{item.machine_number}</b><small>{item.protocol_number}</small></span>
      <span>{item.documents.map(document => <button key={document.id} className="secondary compact" onClick={() => onDownload(document.download_endpoint, document.filename)}><Download size={15} />{document.format.toUpperCase()}</button>)}</span>
    </div>)}</div>
  </div>
}

export function IssueModal({ items, locations, onClose, onComplete }: {
  items: TransferAvailability[]; locations: Location[]; onClose: () => void; onComplete: () => void
}) {
  const [selected, setSelected] = useState<Set<number>>(new Set())
  const [query, setQuery] = useState('')
  const [form, setForm] = useState<IssueForm>(EMPTY_ISSUE_FORM)
  const [step, setStep] = useState<'select' | 'confirm' | 'result'>('select')
  const [result, setResult] = useState<BulkIssueResult | null>(null)
  const [error, setError] = useState<Error | null>(null)
  const [busy, setBusy] = useState(false)
  const filtered = useMemo(() => items.filter(item => `${item.machine_number} ${item.brand} ${item.status} ${item.location || ''}`.toLowerCase().includes(query.toLowerCase())), [items, query])
  const selectedItems = items.filter(item => selected.has(item.machine_id))
  const setField = (field: keyof IssueForm, value: string) => setForm(current => ({ ...current, [field]: value }))
  const toggle = (item: TransferAvailability) => {
    if (!item.available) return
    setSelected(current => {
      const next = new Set(current)
      if (next.has(item.machine_id)) next.delete(item.machine_id)
      else next.add(item.machine_id)
      return next
    })
  }
  const continueToConfirm = () => {
    if (!selected.size) { setError(new Error('Изберете поне една налична машина.')); return }
    setError(null); setStep('confirm')
  }
  async function submit() {
    setBusy(true); setError(null)
    try {
      const payload = {
        machine_ids: [...selected],
        ...Object.fromEntries(Object.entries(form).map(([key, value]) => [key, value || null])),
        location_id: form.location_id ? Number(form.location_id) : null,
      }
      const created = await api<BulkIssueResult>('/transfers/bulk-issue', { method: 'POST', body: JSON.stringify(payload) })
      setResult(created); setStep('result'); onComplete()
    } catch (caught) { setError(caught instanceof Error ? caught : new Error('Издаването не беше завършено.')); setStep('confirm') }
    finally { setBusy(false) }
  }
  const download = (path: string, filename: string) => downloadApiFile(path, filename).catch(caught => setError(caught instanceof Error ? caught : new Error('Документът не може да бъде изтеглен.')))

  return <ModalShell title="Групово издаване" onClose={onClose} wide>
    <ConflictNotice error={error} />
    {step === 'select' && <>
      <div className="bulk-step-head"><div><b>Избрани машини: {selected.size}</b><small>Недостъпните машини са блокирани с посочена причина.</small></div><div className="search small-search"><Search size={17} /><input aria-label="Търсене на машина" value={query} onChange={event => setQuery(event.target.value)} placeholder="Номер, марка, статус или място…" /></div></div>
      <IssueSelectionList items={filtered} selected={selected} onToggle={toggle} />
      <div className="form-grid bulk-fields">
        <label>Фирма / звено<input value={form.company_unit} onChange={event => setField('company_unit', event.target.value)} /></label>
        <label>Кораб<input value={form.vessel} onChange={event => setField('vessel', event.target.value)} /></label>
        <label>Описано място<input value={form.location_text} onChange={event => setField('location_text', event.target.value)} /></label>
        <label>Системно местоположение<select value={form.location_id} onChange={event => setField('location_id', event.target.value)}><option value="">Без промяна</option>{locations.map(location => <option key={location.id} value={location.id}>{location.name}</option>)}</select></label>
        <label>Предал<input value={form.handed_over_by} onChange={event => setField('handed_over_by', event.target.value)} /></label>
        <label>Приел<input value={form.accepted_by} onChange={event => setField('accepted_by', event.target.value)} /></label>
        <label className="wide">Комплектовка<textarea value={form.equipment} onChange={event => setField('equipment', event.target.value)} /></label>
        <label className="wide">Състояние при издаване<textarea value={form.condition_text} onChange={event => setField('condition_text', event.target.value)} /></label>
        <label className="wide">Забележки<textarea value={form.remarks} onChange={event => setField('remarks', event.target.value)} /></label>
      </div>
      <div className="actions"><button className="secondary" onClick={onClose}>Отказ</button><button className="primary" onClick={continueToConfirm} disabled={!selected.size}>Преглед и потвърждение</button></div>
    </>}
    {step === 'confirm' && <>
      <ConfirmationSummary title="Потвърждение на груповото издаване" machineNumbers={selectedItems.map(item => item.machine_number)} rows={[
        ['Фирма / звено', form.company_unit], ['Кораб', form.vessel], ['Място', form.location_text],
        ['Предал', form.handed_over_by], ['Приел', form.accepted_by], ['Комплектовка', form.equipment],
        ['Състояние', form.condition_text], ['Забележки', form.remarks],
      ]} />
      <p className="confirmation-warning">За всяка машина ще бъде създаден отделен проследим протокол. Операцията е атомична.</p>
      <div className="actions"><button className="secondary" onClick={() => setStep('select')} disabled={busy}>Назад</button><button className="primary" onClick={submit} disabled={busy}>{busy ? 'Издаване…' : 'Потвърди издаването'}</button></div>
    </>}
    {step === 'result' && result && <><IssueResult result={result} onDownload={download} /><div className="actions"><button className="primary" onClick={onClose}>Готово</button></div></>}
  </ModalShell>
}

function ReturnModal({ items, locations, onClose, onComplete }: {
  items: TransferAvailability[]; locations: Location[]; onClose: () => void; onComplete: () => void
}) {
  const activeItems = items.filter(item => item.active_transfer_id)
  const [drafts, setDrafts] = useState<Record<number, ReturnDraft>>({})
  const [query, setQuery] = useState('')
  const [step, setStep] = useState<'edit' | 'confirm' | 'result'>('edit')
  const [result, setResult] = useState<BulkReturnResult | null>(null)
  const [error, setError] = useState<Error | null>(null)
  const [busy, setBusy] = useState(false)
  const filtered = activeItems.filter(item => `${item.machine_number} ${item.brand} ${item.batch_reference || ''} ${item.protocol_number || ''}`.toLowerCase().includes(query.toLowerCase()))
  const toggle = (item: TransferAvailability) => setDrafts(current => {
    const next = { ...current }
    if (next[item.machine_id]) delete next[item.machine_id]
    else next[item.machine_id] = {
      transfer_id: item.active_transfer_id!, machine_id: item.machine_id, condition_text: '', result_text: '',
      notes: '', returned_by: '', accepted_by: '', location_id: '', next_status: 'За преглед',
    }
    return next
  })
  const update = (machineId: number, field: keyof ReturnDraft, value: string) => setDrafts(current => ({ ...current, [machineId]: { ...current[machineId], [field]: value } }))
  const selectedItems = activeItems.filter(item => drafts[item.machine_id])
  const confirm = (event: FormEvent) => {
    event.preventDefault()
    if (!selectedItems.length) { setError(new Error('Изберете поне една издадена машина.')); return }
    if (Object.values(drafts).some(draft => !draft.condition_text.trim() || !draft.result_text.trim())) {
      setError(new Error('Попълнете състояние и резултат за всяка избрана машина.')); return
    }
    setError(null); setStep('confirm')
  }
  async function submit() {
    setBusy(true); setError(null)
    try {
      const payload = { items: Object.values(drafts).map(draft => ({ ...draft, location_id: draft.location_id ? Number(draft.location_id) : null })) }
      const completed = await api<BulkReturnResult>('/transfers/bulk-return', { method: 'POST', body: JSON.stringify(payload) })
      setResult(completed); setStep('result'); onComplete()
    } catch (caught) { setError(caught instanceof Error ? caught : new Error('Връщането не беше завършено.')); setStep('confirm') }
    finally { setBusy(false) }
  }
  return <ModalShell title="Групово връщане" onClose={onClose} wide>
    <ConflictNotice error={error} />
    {step === 'edit' && <form onSubmit={confirm}>
      <div className="bulk-step-head"><div><b>Избрани машини: {selectedItems.length}</b><small>Възможно е частично или смесено връщане от различни партиди.</small></div><div className="search small-search"><Search size={17} /><input aria-label="Търсене на издадена машина" value={query} onChange={event => setQuery(event.target.value)} placeholder="Машина, партида или протокол…" /></div></div>
      {!filtered.length && <div className="empty-state">Няма активни предавания за връщане.</div>}
      <div className="return-list">{filtered.map(item => <section key={item.machine_id} className={`return-item ${drafts[item.machine_id] ? 'selected' : ''}`}>
        <label className="return-select"><input type="checkbox" aria-label={`Връщане на машина №${item.machine_number}`} checked={!!drafts[item.machine_id]} onChange={() => toggle(item)} /><span><b>HPWJ №{item.machine_number}</b><small>{item.brand} · {item.protocol_number} · {item.batch_reference || 'Без партида'}</small></span><span className="availability-pill blocked">Издадена</span></label>
        {drafts[item.machine_id] && <div className="form-grid return-fields">
          <label>Следващ етап<select value={drafts[item.machine_id].next_status} onChange={event => update(item.machine_id, 'next_status', event.target.value)}>{RETURN_STATUSES.map(value => <option key={value}>{value}</option>)}</select></label>
          <label>Местоположение<select value={drafts[item.machine_id].location_id} onChange={event => update(item.machine_id, 'location_id', event.target.value)}><option value="">Без промяна</option>{locations.map(location => <option key={location.id} value={location.id}>{location.name}</option>)}</select></label>
          <label>Върнал<input value={drafts[item.machine_id].returned_by} onChange={event => update(item.machine_id, 'returned_by', event.target.value)} /></label>
          <label>Приел<input value={drafts[item.machine_id].accepted_by} onChange={event => update(item.machine_id, 'accepted_by', event.target.value)} /></label>
          <label className="wide">Състояние при връщане *<textarea required value={drafts[item.machine_id].condition_text} onChange={event => update(item.machine_id, 'condition_text', event.target.value)} /></label>
          <label className="wide">Резултат / необходима последваща работа *<textarea required value={drafts[item.machine_id].result_text} onChange={event => update(item.machine_id, 'result_text', event.target.value)} /></label>
          <label className="wide">Бележки<textarea value={drafts[item.machine_id].notes} onChange={event => update(item.machine_id, 'notes', event.target.value)} /></label>
        </div>}
      </section>)}</div>
      <div className="actions"><button type="button" className="secondary" onClick={onClose}>Отказ</button><button className="primary" disabled={!selectedItems.length}>Преглед и потвърждение</button></div>
    </form>}
    {step === 'confirm' && <>
      <ConfirmationSummary title="Потвърждение на връщането" machineNumbers={selectedItems.map(item => item.machine_number)} rows={[]} />
      <div className="return-confirm-list">{selectedItems.map(item => { const draft = drafts[item.machine_id]; return <div key={item.machine_id}><b>№{item.machine_number} → {draft.next_status}</b><span>{draft.condition_text}</span><span>{draft.result_text}</span></div> })}</div>
      <p className="confirmation-warning">Машините няма да бъдат маркирани автоматично като „Готова“. Всяка ще продължи по избрания етап.</p>
      <div className="actions"><button className="secondary" onClick={() => setStep('edit')} disabled={busy}>Назад</button><button className="primary" onClick={submit} disabled={busy}>{busy ? 'Връщане…' : 'Потвърди връщането'}</button></div>
    </>}
    {step === 'result' && result && <div className="operation-result" role="status"><CheckCircle2 size={36} /><h4>{result.message}</h4><div className="return-confirm-list">{result.returned.map(item => <div key={item.transfer_id}><b>Машина №{item.machine_number}</b><span>Нов статус: {item.new_status}</span></div>)}</div>{result.batches.map(batch => <BatchProgressCard key={batch.batch_id} batch={batch} />)}<div className="actions"><button className="primary" onClick={onClose}>Готово</button></div></div>}
  </ModalShell>
}

export function BatchProgressCard({ batch, onOpen }: { batch: BatchProgress; onOpen?: (batch: BatchProgress) => void }) {
  const returnedPercent = batch.total_machines ? Math.round((batch.returned_machines / batch.total_machines) * 100) : 0
  return <article className="batch-card">
    <div><span className={`badge ${batch.still_issued_machines ? 'batch-active' : 'batch-complete'}`}>{batch.status}</span><h4>{batch.batch_reference}</h4>{batch.created_at && <small>{new Date(batch.created_at).toLocaleString('bg-BG')}</small>}</div>
    <div className="batch-progress"><span style={{ width: `${returnedPercent}%` }} /><small>Върнати: {batch.returned_machines} · Все още издадени: {batch.still_issued_machines} · Общо: {batch.total_machines}</small></div>
    {onOpen && <button className="secondary compact" onClick={() => onOpen(batch)}>Детайли</button>}
  </article>
}

function BatchDetailsPanel({ details, onDownload }: { details: BatchDetails; onDownload: (path: string, filename: string) => void }) {
  return <div className="batch-details"><button className="secondary" onClick={() => onDownload(details.zip_download_endpoint, `${details.batch_reference}-protocols.zip`)}><Archive size={16} />ZIP протоколи</button>{details.transfers.map(transfer => <div key={transfer.transfer_id}><span><b>HPWJ №{transfer.machine_number}</b><small>{transfer.brand} · {transfer.protocol_number}</small></span><span className={`availability-pill ${transfer.is_active ? 'blocked' : 'available'}`}>{transfer.is_active ? 'Все още издадена' : 'Върната'}</span><span>{transfer.documents.map((document: ProtocolDocument) => <button className="link" key={document.id} onClick={() => onDownload(document.download_endpoint, document.filename)}>{document.format.toUpperCase()}</button>)}</span></div>)}</div>
}

export default function BulkTransfers({ onChanged }: BulkTransfersProps) {
  const [availabilityItems, setAvailability] = useState<TransferAvailability[]>([])
  const [locations, setLocations] = useState<Location[]>([])
  const [batches, setBatches] = useState<BatchProgress[]>([])
  const [details, setDetails] = useState<Record<number, BatchDetails>>({})
  const [mode, setMode] = useState<'issue' | 'return' | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<Error | null>(null)
  const load = async () => {
    setLoading(true)
    try {
      const [available, locationItems, batchItems] = await Promise.all([
        api<TransferAvailability[]>('/transfers/availability'), api<Location[]>('/locations'), api<BatchProgress[]>('/transfer-batches'),
      ])
      setAvailability(available); setLocations(locationItems); setBatches(batchItems); setError(null)
    } catch (caught) { setError(caught instanceof Error ? caught : new Error('Данните за предаванията не могат да бъдат заредени.')) }
    finally { setLoading(false) }
  }
  useEffect(() => { void load() }, [])
  const completed = () => { void load(); onChanged() }
  const openBatch = async (batch: BatchProgress) => {
    if (details[batch.batch_id]) { setDetails(current => { const next = { ...current }; delete next[batch.batch_id]; return next }); return }
    try { const value = await api<BatchDetails>(`/transfer-batches/${batch.batch_id}`); setDetails(current => ({ ...current, [batch.batch_id]: value })) }
    catch (caught) { setError(caught instanceof Error ? caught : new Error('Партидата не може да бъде отворена.')) }
  }
  const download = (path: string, filename: string) => downloadApiFile(path, filename).catch(caught => setError(caught instanceof Error ? caught : new Error('Документът не може да бъде изтеглен.')))
  return <section className="bulk-workspace">
    <div className="bulk-actions"><button className="primary" onClick={() => setMode('issue')}><Send size={18} />Групово издаване</button><button className="secondary emphasized" onClick={() => setMode('return')}><RotateCcw size={18} />Групово връщане</button></div>
    <ConflictNotice error={error} />
    <div className="panel batch-panel"><div className="panel-title"><div><h3>Партиди и напредък</h3><p className="muted">Пълни и частично върнати партиди с индивидуална проследимост</p></div></div>
      {loading ? <div className="loading">Зареждане…</div> : batches.length ? <div className="batch-list">{batches.map(batch => <div key={batch.batch_id}><BatchProgressCard batch={batch} onOpen={openBatch} />{details[batch.batch_id] && <BatchDetailsPanel details={details[batch.batch_id]} onDownload={download} />}</div>)}</div> : <div className="empty-state">Все още няма създадени партиди.</div>}
    </div>
    {mode === 'issue' && <IssueModal items={availabilityItems} locations={locations} onClose={() => setMode(null)} onComplete={completed} />}
    {mode === 'return' && <ReturnModal items={availabilityItems} locations={locations} onClose={() => setMode(null)} onComplete={completed} />}
  </section>
}
