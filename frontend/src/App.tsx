import { FormEvent, useEffect, useMemo, useState } from 'react'
import {
  BarChart3, Boxes, FileText, Gauge, LogOut, Menu, PackageSearch, Plus, QrCode,
  Search, Settings, ShieldCheck, Wrench, X, ClipboardSignature, BookOpen, History
} from 'lucide-react'
import { api, downloadApiFile, getToken, logout, setToken } from './api'
import type { Location, Machine, PartRequest, Repair } from './types'
import BulkTransfers from './BulkTransfers'

type Page = 'dashboard' | 'machines' | 'transfers' | 'repairs' | 'catalog' | 'parts' | 'documents' | 'reports' | 'audit' | 'qr' | 'settings'

const STATUS_OPTIONS = ['Готова','Издадена','В употреба','Върната','За преглед','Почистване','В ремонт','Чака одобрение','Чака части','Тестване']

function Login({ onLogin }: { onLogin: () => void }) {
  const [email, setEmail] = useState('admin@assetcore.local')
  const [password, setPassword] = useState('AssetCore123!')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  async function submit(e: FormEvent) {
    e.preventDefault(); setBusy(true); setError('')
    try {
      const data = await api<{access_token:string; user:unknown}>('/auth/login', { method:'POST', body:JSON.stringify({email,password}) })
      setToken(data.access_token); localStorage.setItem('assetcore_user', JSON.stringify(data.user)); onLogin()
    } catch (err) { setError(err instanceof Error ? err.message : 'Грешка при вход') }
    finally { setBusy(false) }
  }

  return <div className="login-shell">
    <div className="login-panel">
      <div className="brand-mark"><ShieldCheck size={30}/></div>
      <h1>AssetCore</h1><p>Индустриално управление на активи</p>
      <form onSubmit={submit}>
        <label>Имейл<input value={email} onChange={e=>setEmail(e.target.value)} type="email"/></label>
        <label>Парола<input value={password} onChange={e=>setPassword(e.target.value)} type="password"/></label>
        {error && <div className="error">{error}</div>}
        <button disabled={busy}>{busy ? 'Влизане…' : 'Вход'}</button>
      </form>
      <small>Начален администратор: admin@assetcore.local</small>
    </div>
  </div>
}

function App() {
  const [authenticated, setAuthenticated] = useState(!!getToken())
  const [page, setPage] = useState<Page>('dashboard')
  const [mobileMenu, setMobileMenu] = useState(false)
  if (!authenticated) return <Login onLogin={()=>setAuthenticated(true)}/>

  const nav = [
    ['dashboard','Табло',Gauge], ['machines','Машини',Boxes], ['transfers','Приемане / предаване',ClipboardSignature], ['repairs','Ремонти',Wrench],
    ['catalog','Parts list',BookOpen], ['parts','Заявки за части',PackageSearch], ['documents','Технически документи',FileText], ['reports','Отчети',BarChart3], ['audit','Журнал',History], ['qr','QR кодове',QrCode], ['settings','Настройки',Settings]
  ] as const

  return <div className="app-shell">
    <aside className={mobileMenu ? 'sidebar open' : 'sidebar'}>
      <div className="brand"><div className="brand-mark small"><ShieldCheck size={22}/></div><div><strong>AssetCore</strong><span>HPWJ управление</span></div></div>
      <nav>{nav.map(([id,label,Icon])=><button key={id} className={page===id?'active':''} onClick={()=>{setPage(id);setMobileMenu(false)}}><Icon size={19}/>{label}</button>)}</nav>
      <button className="logout" onClick={()=>{logout();setAuthenticated(false)}}><LogOut size={18}/>Изход</button>
    </aside>
    <main>
      <header><button className="mobile-toggle" onClick={()=>setMobileMenu(v=>!v)}>{mobileMenu?<X/>:<Menu/>}</button><div><h2>{nav.find(x=>x[0]===page)?.[1]}</h2><p>Одесос — управление на техника и ремонти</p></div></header>
      <section className="content">
        {page==='dashboard' && <Dashboard/>}
        {page==='machines' && <Machines/>}
        {page==='transfers' && <Transfers/>}
        {page==='repairs' && <Repairs/>}
        {page==='catalog' && <PartCatalog/>}
        {page==='parts' && <Parts/>}
        {page==='documents' && <Documents/>}
        {page==='reports' && <Reports/>}
        {page==='audit' && <Audit/>}
        {page==='qr' && <QrCodes/>}
        {page==='settings' && <SettingsPage/>}
      </section>
    </main>
  </div>
}

function Dashboard() {
  const [data,setData] = useState<any>(null)
  useEffect(()=>{api('/dashboard').then(setData).catch(console.error)},[])
  if(!data) return <div className="loading">Зареждане…</div>
  const cards = [
    ['Общо машини',data.total_machines,Boxes],['Готови',data.ready,ShieldCheck],['В употреба',data.in_use,Gauge],['Отворени ремонти',data.open_repairs,Wrench],['Чакащи заявки',data.pending_parts,PackageSearch]
  ] as const
  return <>
    <div className="stats-grid">{cards.map(([label,value,Icon])=><div className="stat-card" key={label}><div className="stat-icon"><Icon size={23}/></div><div><span>{label}</span><strong>{value}</strong></div></div>)}</div>
    <div className="panel-grid">
      <div className="panel"><div className="panel-title"><h3>Състояние на машините</h3><BarChart3/></div>
        <div className="status-list">{Object.entries(data.status_breakdown).map(([status,count]:any)=><div key={status}><span>{status}</span><div className="bar"><i style={{width:`${Math.max(8,(count/data.total_machines)*100)}%`}}/></div><b>{count}</b></div>)}</div>
      </div>
      <div className="panel"><div className="panel-title"><h3>Последни ремонти</h3><Wrench/></div>
        <div className="activity-list">{data.recent_repairs.length ? data.recent_repairs.map((r:any)=><div key={r.id}><strong>{r.machine}</strong><span>{r.problem}</span><em>{r.status}</em></div>) : <p className="muted">Все още няма регистрирани ремонти.</p>}</div>
      </div>
    </div>
  </>
}

function Machines() {
  const [items,setItems]=useState<Machine[]>([]), [locations,setLocations]=useState<Location[]>([])
  const [query,setQuery]=useState(''), [selected,setSelected]=useState<Machine|null>(null), [showNew,setShowNew]=useState(false)
  const load=()=>Promise.all([api<Machine[]>('/machines'),api<Location[]>('/locations')]).then(([m,l])=>{setItems(m);setLocations(l)})
  useEffect(()=>{load().catch(console.error)},[])
  const filtered=useMemo(()=>items.filter(x=>`${x.name} ${x.brand} ${x.status} ${x.location?.name}`.toLowerCase().includes(query.toLowerCase())),[items,query])
  return <>
    <div className="toolbar"><div className="search"><Search size={18}/><input placeholder="Търси по номер, марка, статус или място…" value={query} onChange={e=>setQuery(e.target.value)}/></div><button className="primary" onClick={()=>setShowNew(true)}><Plus size={18}/>Нова машина</button></div>
    <div className="table-card"><table><thead><tr><th>Машина</th><th>Марка</th><th>Налягане</th><th>Статус</th><th>Местоположение</th><th></th></tr></thead><tbody>{filtered.map(m=><tr key={m.id}><td><strong>{m.name}</strong><small>Инв. № {m.inventory_number}</small></td><td>{m.brand}</td><td>{m.pressure_bar} bar</td><td><span className="badge">{m.status}</span></td><td>{m.location?.name||'Не е определено'}</td><td><button className="link" onClick={()=>setSelected(m)}>Отвори</button></td></tr>)}</tbody></table></div>
    {selected&&<MachineModal machine={selected} locations={locations} onClose={()=>setSelected(null)} onSaved={()=>{setSelected(null);load()}}/>}
    {showNew&&<MachineModal locations={locations} onClose={()=>setShowNew(false)} onSaved={()=>{setShowNew(false);load()}}/>}
  </>
}

function MachineModal({machine,locations,onClose,onSaved}:{machine?:Machine;locations:Location[];onClose:()=>void;onSaved:()=>void}) {
  const [form,setForm]=useState<any>(machine||{inventory_number:'',name:'',brand:'HYDWIN',category:'HPWJ машина',pressure_bar:500,status:'Готова',location_id:locations[0]?.id})
  async function save(e:FormEvent){e.preventDefault(); await api(machine?`/machines/${machine.id}`:'/machines',{method:machine?'PATCH':'POST',body:JSON.stringify(form)});onSaved()}
  return <div className="modal-bg"><div className="modal"><div className="modal-head"><h3>{machine?'Данни за машината':'Нова машина'}</h3><button onClick={onClose}><X/></button></div><form onSubmit={save} className="form-grid">
    {!machine&&<label>Инвентарен номер<input required value={form.inventory_number} onChange={e=>setForm({...form,inventory_number:e.target.value})}/></label>}
    <label>Наименование<input required value={form.name} onChange={e=>setForm({...form,name:e.target.value})}/></label>
    <label>Марка<input value={form.brand||''} onChange={e=>setForm({...form,brand:e.target.value})}/></label>
    <label>Модел<input value={form.model||''} onChange={e=>setForm({...form,model:e.target.value})}/></label>
    <label>Налягане (bar)<input type="number" value={form.pressure_bar} onChange={e=>setForm({...form,pressure_bar:+e.target.value})}/></label>
    <label>Статус<select value={form.status} onChange={e=>setForm({...form,status:e.target.value})}>{STATUS_OPTIONS.map(x=><option key={x}>{x}</option>)}</select></label>
    <label>Местоположение<select value={form.location_id||''} onChange={e=>setForm({...form,location_id:+e.target.value})}>{locations.map(x=><option key={x.id} value={x.id}>{x.name}</option>)}</select></label>
    <label className="wide">Бележки<textarea value={form.notes||''} onChange={e=>setForm({...form,notes:e.target.value})}/></label>
    {machine&&<div className="qr-box"><img src={`/api/machines/${machine.id}/qr`} alt="QR код"/><span>QR код на машината</span></div>}
    <div className="actions wide"><button type="button" className="secondary" onClick={onClose}>Отказ</button><button className="primary">Запази</button></div>
  </form></div></div>
}

function Repairs(){
  const [items,setItems]=useState<Repair[]>([]),[machines,setMachines]=useState<Machine[]>([]),[show,setShow]=useState(false)
  const load=()=>Promise.all([api<Repair[]>('/repairs'),api<Machine[]>('/machines')]).then(([r,m])=>{setItems(r);setMachines(m)})
  useEffect(()=>{load().catch(console.error)},[])
  return <><div className="toolbar"><div><h3>История и активни ремонти</h3><p className="muted">Приемане, диагностика, извършена работа и резултат</p></div><button className="primary" onClick={()=>setShow(true)}><Plus size={18}/>Нов ремонт</button></div>
  <div className="cards-list">{items.map(r=><div className="repair-card" key={r.id}><div><span className="badge">{r.status}</span><h3>{r.machine.name}</h3><p><b>Проблем:</b> {r.reported_problem}</p>{r.diagnosis&&<p><b>Диагностика:</b> {r.diagnosis}</p>}{r.work_performed&&<p><b>Извършено:</b> {r.work_performed}</p>}</div><div className="repair-side"><small>{new Date(r.opened_at).toLocaleString('bg-BG')}</small>{!r.closed_at&&<button onClick={async()=>{await api(`/repairs/${r.id}`,{method:'PATCH',body:JSON.stringify({close:true,status:'Тестване',result:'Тествана и подготвена за работа'})});load()}}>Приключи след тест</button>}</div></div>)}</div>
  {show&&<RepairModal machines={machines} onClose={()=>setShow(false)} onSaved={()=>{setShow(false);load()}}/>}</>
}

function RepairModal({machines,onClose,onSaved}:{machines:Machine[];onClose:()=>void;onSaved:()=>void}){
  const [form,setForm]=useState<any>({machine_id:machines[0]?.id,reported_problem:'',diagnosis:'',work_performed:'',status:'Приета'})
  async function save(e:FormEvent){e.preventDefault();await api('/repairs',{method:'POST',body:JSON.stringify(form)});onSaved()}
  return <div className="modal-bg"><div className="modal"><div className="modal-head"><h3>Приемане за ремонт</h3><button onClick={onClose}><X/></button></div><form onSubmit={save} className="form-grid">
    <label>Машина<select value={form.machine_id} onChange={e=>setForm({...form,machine_id:+e.target.value})}>{machines.map(m=><option value={m.id} key={m.id}>{m.name}</option>)}</select></label>
    <label>Статус<select value={form.status} onChange={e=>setForm({...form,status:e.target.value})}><option>Приета</option><option>Диагностика</option><option>В ремонт</option><option>Чака части</option><option>Тестване</option></select></label>
    <label className="wide">Установен проблем<textarea required value={form.reported_problem} onChange={e=>setForm({...form,reported_problem:e.target.value})}/></label>
    <label className="wide">Диагностика<textarea value={form.diagnosis} onChange={e=>setForm({...form,diagnosis:e.target.value})}/></label>
    <label className="wide">Извършена работа<textarea value={form.work_performed} onChange={e=>setForm({...form,work_performed:e.target.value})}/></label>
    <div className="actions wide"><button type="button" className="secondary" onClick={onClose}>Отказ</button><button className="primary">Запази</button></div>
  </form></div></div>
}

function Parts(){
  const [items,setItems]=useState<PartRequest[]>([]),[machines,setMachines]=useState<Machine[]>([]),[show,setShow]=useState(false)
  const load=()=>Promise.all([api<PartRequest[]>('/parts'),api<Machine[]>('/machines')]).then(([p,m])=>{setItems(p);setMachines(m)})
  useEffect(()=>{load().catch(console.error)},[])
  return <><div className="toolbar"><div><h3>Заявки за резервни части</h3><p className="muted">Проследяване от заявяване до доставка</p></div><button className="primary" onClick={()=>setShow(true)}><Plus size={18}/>Нова заявка</button></div>
  <div className="table-card"><table><thead><tr><th>Част</th><th>Part №</th><th>Машина</th><th>Количество</th><th>Приоритет</th><th>Статус</th></tr></thead><tbody>{items.map(p=><tr key={p.id}><td><strong>{p.part_name}</strong><small>{p.reason}</small></td><td>{p.part_number||'—'}</td><td>{p.machine?.name||'Обща'}</td><td>{p.quantity}</td><td>{p.priority}</td><td><span className="badge">{p.status}</span></td></tr>)}</tbody></table></div>
  {show&&<PartModal machines={machines} onClose={()=>setShow(false)} onSaved={()=>{setShow(false);load()}}/>}</>
}

function PartModal({machines,onClose,onSaved}:{machines:Machine[];onClose:()=>void;onSaved:()=>void}){
  const [form,setForm]=useState<any>({machine_id:machines[0]?.id,part_name:'',part_number:'',quantity:1,reason:'',priority:'Нормален',status:'Чернова'})
  async function save(e:FormEvent){e.preventDefault();await api('/parts',{method:'POST',body:JSON.stringify(form)});onSaved()}
  return <div className="modal-bg"><div className="modal"><div className="modal-head"><h3>Нова заявка</h3><button onClick={onClose}><X/></button></div><form onSubmit={save} className="form-grid">
    <label>Част<input required value={form.part_name} onChange={e=>setForm({...form,part_name:e.target.value})}/></label><label>Part №<input value={form.part_number} onChange={e=>setForm({...form,part_number:e.target.value})}/></label>
    <label>Машина<select value={form.machine_id} onChange={e=>setForm({...form,machine_id:+e.target.value})}>{machines.map(m=><option value={m.id} key={m.id}>{m.name}</option>)}</select></label><label>Количество<input type="number" min="1" value={form.quantity} onChange={e=>setForm({...form,quantity:+e.target.value})}/></label>
    <label>Приоритет<select value={form.priority} onChange={e=>setForm({...form,priority:e.target.value})}><option>Нисък</option><option>Нормален</option><option>Спешен</option></select></label><label>Статус<select value={form.status} onChange={e=>setForm({...form,status:e.target.value})}><option>Чернова</option><option>Изпратена</option><option>Одобрена</option><option>Поръчана</option><option>Доставена</option></select></label>
    <label className="wide">Основание<textarea value={form.reason} onChange={e=>setForm({...form,reason:e.target.value})}/></label><div className="actions wide"><button type="button" className="secondary" onClick={onClose}>Отказ</button><button className="primary">Запази</button></div>
  </form></div></div>
}

function Reports(){const [error,setError]=useState('');const download=()=>downloadApiFile('/reports/daily.pdf','assetcore-daily-report.pdf').catch(()=>setError('Дневният отчет не може да бъде изтеглен.'));return <div className="panel"><div className="panel-title"><div><h3>Документи и отчети</h3><p className="muted">Генериране на справки от текущите данни</p></div><FileText/></div>{error&&<div className="error" role="alert">{error}</div>}<div className="report-options"><button className="primary" onClick={download}>Изтегли дневен отчет PDF</button><div className="coming">Протоколите се генерират в Word и PDF от модул „Приемане / предаване“. Техническите ръководства и parts list файловете са в библиотеката.</div></div></div>}
function QrCodes(){const [machines,setMachines]=useState<Machine[]>([]);useEffect(()=>{api<Machine[]>('/machines').then(setMachines)},[]);return <div className="qr-grid">{machines.map(m=><div className="qr-card" key={m.id}><img src={`/api/machines/${m.id}/qr`}/><strong>{m.name}</strong><span>{m.brand} · {m.pressure_bar} bar</span></div>)}</div>}
function SettingsPage(){return <div className="panel"><div className="panel-title"><h3>Настройки</h3><Settings/></div><div className="settings-list"><div><b>Език</b><span>Български</span></div><div><b>Организация</b><span>КРЗ Одесос</span></div><div><b>Версия</b><span>AssetCore 2.5 Director Preview</span></div><div><b>База данни</b><span>SQLite локално / PostgreSQL в Render</span></div></div></div>}


function Transfers(){
  const [items,setItems]=useState<any[]>([]),[error,setError]=useState('')
  const load=()=>api<any[]>('/transfers').then(setItems).catch(()=>setError('Историята на протоколите не може да бъде заредена.'))
  useEffect(()=>{load().catch(console.error)},[])
  const download=(path:string,name:string)=>downloadApiFile(path,name).catch(()=>setError('Протоколът не може да бъде изтеглен.'))
  return <><div className="toolbar"><div><h3>Приемо-предавателни протоколи</h3><p className="muted">Защитено групово издаване, пълно и частично връщане с индивидуален Word/PDF протокол</p></div></div>
  {error&&<div className="error" role="alert">{error}</div>}
  <BulkTransfers onChanged={()=>void load()}/>
  <div className="toolbar protocol-history-title"><div><h3>Индивидуална история</h3><p className="muted">Всеки ред остава свързан с конкретна машина и партида</p></div></div>
  <div className="table-card"><table><thead><tr><th>№</th><th>Партида</th><th>Машина</th><th>Статус</th><th>Фирма / място</th><th>Издаване / връщане</th><th>Документи</th></tr></thead><tbody>{items.map(t=><tr key={t.id}><td><strong>{t.protocol_number}</strong></td><td>{t.batch_reference||'—'}</td><td>{t.machine.name}</td><td><span className="badge">{t.is_active?'Все още издадена':'Върната'}</span></td><td>{[t.company_unit,t.vessel,t.location_text].filter(Boolean).join(' · ')||'—'}</td><td>{new Date(t.issued_at||t.created_at).toLocaleString('bg-BG')}{t.returned_at&&<small>Върната: {new Date(t.returned_at).toLocaleString('bg-BG')}</small>}</td><td><button className="link" onClick={()=>download(`/transfers/${t.id}/docx`,`${t.protocol_number}.docx`)}>Word</button> · <button className="link" onClick={()=>download(`/transfers/${t.id}/pdf`,`${t.protocol_number}.pdf`)}>PDF</button></td></tr>)}</tbody></table></div></>
}
function PartCatalog(){
 const [items,setItems]=useState<any[]>([]),[q,setQ]=useState(''),[brand,setBrand]=useState('')
 const load=()=>api<any[]>(`/catalog/parts?q=${encodeURIComponent(q)}&brand=${encodeURIComponent(brand)}`).then(setItems)
 useEffect(()=>{load()},[q,brand])
 return <><div className="toolbar"><div><h3>Каталог резервни части</h3><p className="muted">Проверими Part No. записи с източник, страница и оригинален parts list</p></div></div><div className="filters"><div className="searchbox"><Search size={18}/><input value={q} onChange={e=>setQ(e.target.value)} placeholder="Търси по Part No., описание или възел…"/></div><select value={brand} onChange={e=>setBrand(e.target.value)}><option value="">Всички марки</option><option>CombiJet</option><option>Falch</option><option>HYDWIN (Fussen)</option></select></div>
 <div className="table-card"><table><thead><tr><th>Марка / модел</th><th>Възел</th><th>Поз.</th><th>Part No.</th><th>Описание</th><th>Кол.</th><th>Източник</th></tr></thead><tbody>{items.map(x=><tr key={x.id}><td><strong>{x.brand}</strong><small>{x.model}</small></td><td>{x.assembly||'—'}</td><td>{x.position||'—'}</td><td><strong>{x.part_number}</strong></td><td>{x.description}</td><td>{x.quantity||'—'}</td><td>{x.source_document?`${x.source_document.split('/').pop()} · стр. ${x.source_page||'—'}`:'—'}</td></tr>)}</tbody></table></div></>
}
function Documents(){
 const [items,setItems]=useState<any[]>([]),[error,setError]=useState(''); useEffect(()=>{api<any[]>('/documents').then(setItems).catch(()=>setError('Документите не могат да бъдат заредени.'))},[])
 const groups=useMemo(()=>Object.entries(items.reduce((a:any,x:any)=>{(a[x.brand]??=[]).push(x);return a},{})),[items])
 const download=(id:number,name:string)=>downloadApiFile(`/documents/${id}/download`,name).catch(()=>setError('Документът не може да бъде изтеглен.'))
 return <><div className="toolbar"><div><h3>Техническа библиотека</h3><p className="muted">Оригинални parts list, ръководства, спецификации, Excel и Word документи от работната база</p></div></div>{error&&<div className="error" role="alert">{error}</div>}<div className="cards-list">{groups.map(([brand,docs]:any)=><div className="panel" key={brand}><div className="panel-title"><h3>{brand}</h3><BookOpen/></div><div className="activity-list">{docs.map((d:any)=><div key={d.id}><strong>{d.title}</strong><span>{d.category}</span><button className="link" onClick={()=>download(d.id,d.title)}>Отвори / изтегли</button></div>)}</div></div>)}</div></>
}
function Audit(){const [items,setItems]=useState<any[]>([]);useEffect(()=>{api<any[]>('/audit').then(setItems)},[]);return <><div className="toolbar"><div><h3>Журнал на действията</h3><p className="muted">Проследимост на промени, ремонти, протоколи и заявки</p></div></div><div className="table-card"><table><thead><tr><th>Дата</th><th>Потребител</th><th>Обект</th><th>Действие</th><th>Детайли</th></tr></thead><tbody>{items.map(x=><tr key={x.id}><td>{new Date(x.created_at).toLocaleString('bg-BG')}</td><td>{x.user_name||'Система'}</td><td>{x.entity_type} #{x.entity_id||'—'}</td><td>{x.action}</td><td><small>{x.details||'—'}</small></td></tr>)}</tbody></table></div></>}

export default App
