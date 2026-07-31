FROM python:3.12-slim

WORKDIR /app

RUN pip install --no-cache-dir fastapi==0.115.6 uvicorn[standard]==0.34.0

RUN cat > /app/main.py <<'PY'
from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel
from datetime import datetime
from typing import Optional

app = FastAPI(title="AssetCore", version="1.0.0")

MACHINES = [
    {"id": 1, "number": "7", "type": "HPWJ", "pressure": 500, "brand": "HYDWIN", "status": "Ready", "location": "Workshop"},
    {"id": 2, "number": "8", "type": "HPWJ", "pressure": 500, "brand": "HYDWIN", "status": "Ready", "location": "Workshop"},
    {"id": 3, "number": "9", "type": "HPWJ", "pressure": 500, "brand": "HYDWIN", "status": "In use", "location": "Dock 3"},
    {"id": 4, "number": "10", "type": "HPWJ", "pressure": 500, "brand": "HYDWIN", "status": "In use", "location": "Dock 3"},
    {"id": 5, "number": "13", "type": "HPWJ", "pressure": 500, "brand": "HYDWIN", "status": "Repair", "location": "Workshop"},
    {"id": 6, "number": "14", "type": "HPWJ", "pressure": 500, "brand": "HYDWIN", "status": "In use", "location": "Dock 3"},
    {"id": 7, "number": "15", "type": "HPWJ", "pressure": 500, "brand": "HYDWIN", "status": "Inspection", "location": "Workshop"},
    {"id": 8, "number": "16", "type": "HPWJ", "pressure": 500, "brand": "HYDWIN", "status": "Ready", "location": "Workshop"},
    {"id": 9, "number": "17", "type": "HPWJ", "pressure": 500, "brand": "HYDWIN", "status": "In use", "location": "Quay 1"},
    {"id": 10, "number": "18", "type": "HPWJ", "pressure": 500, "brand": "HYDWIN", "status": "In use", "location": "Dry dock"},
    {"id": 11, "number": "19", "type": "HPWJ", "pressure": 500, "brand": "HYDWIN", "status": "Repair", "location": "Workshop"},
    {"id": 12, "number": "20", "type": "HPWJ", "pressure": 500, "brand": "HYDWIN", "status": "Ready", "location": "Workshop"},
    {"id": 13, "number": "21", "type": "HPWJ", "pressure": 500, "brand": "HYDWIN", "status": "In use", "location": "Dock 3"},
    {"id": 14, "number": "22", "type": "HPWJ", "pressure": 500, "brand": "HYDWIN", "status": "In use", "location": "Dock 2"},
    {"id": 15, "number": "23", "type": "HPWJ", "pressure": 500, "brand": "HYDWIN", "status": "Ready", "location": "Workshop"},
    {"id": 16, "number": "24", "type": "HPWJ", "pressure": 500, "brand": "HYDWIN", "status": "In use", "location": "Dock 3"},
    {"id": 17, "number": "1000-1", "type": "HPWJ", "pressure": 1000, "brand": "Falch", "status": "In use", "location": "Quay 6"},
    {"id": 18, "number": "1000-2", "type": "HPWJ", "pressure": 1000, "brand": "Falch", "status": "Ready", "location": "Workshop"},
    {"id": 19, "number": "CJ-01", "type": "HPWJ", "pressure": 500, "brand": "CombiJet", "status": "Ready", "location": "Workshop"},
]

REPAIRS = []

class MachineUpdate(BaseModel):
    status: Optional[str] = None
    location: Optional[str] = None

class RepairCreate(BaseModel):
    machine_number: str
    problem: str
    action: str = ""
    result: str = ""

@app.get("/health")
def health():
    return {"status": "ok", "service": "AssetCore", "time": datetime.utcnow().isoformat()}

@app.get("/api/machines")
def machines():
    return MACHINES

@app.patch("/api/machines/{machine_id}")
def update_machine(machine_id: int, payload: MachineUpdate):
    machine = next((m for m in MACHINES if m["id"] == machine_id), None)
    if not machine:
        return JSONResponse({"error": "Machine not found"}, status_code=404)
    if payload.status is not None:
        machine["status"] = payload.status
    if payload.location is not None:
        machine["location"] = payload.location
    return machine

@app.get("/api/repairs")
def repairs():
    return REPAIRS

@app.post("/api/repairs")
def create_repair(payload: RepairCreate):
    item = payload.model_dump()
    item["id"] = len(REPAIRS) + 1
    item["created_at"] = datetime.utcnow().isoformat()
    REPAIRS.insert(0, item)
    return item

@app.get("/", response_class=HTMLResponse)
def home():
    return HTMLResponse(HTML)

HTML = r'''<!doctype html>
<html lang="bg">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover" />
<meta name="theme-color" content="#0b1f33" />
<title>AssetCore | HPWJ</title>
<style>
:root{--navy:#0b1f33;--blue:#1677ff;--bg:#f3f6fa;--card:#fff;--text:#142033;--muted:#697386;--ok:#14804a;--warn:#ad5700;--bad:#b42318;--line:#dfe5ec}
*{box-sizing:border-box} body{margin:0;font-family:Inter,system-ui,-apple-system,Segoe UI,Roboto,sans-serif;background:var(--bg);color:var(--text)}
header{background:linear-gradient(135deg,#081827,#153a5f);color:#fff;padding:18px 16px 24px;position:sticky;top:0;z-index:5;box-shadow:0 8px 24px #00152a2b}
.brand{display:flex;align-items:center;gap:12px;max-width:1200px;margin:auto}.mark{width:42px;height:42px;border-radius:12px;background:#fff;color:var(--navy);font-weight:900;display:grid;place-items:center}.brand h1{font-size:20px;margin:0}.brand p{margin:2px 0 0;color:#c9d8e7;font-size:12px}
main{max-width:1200px;margin:auto;padding:16px}.grid{display:grid;grid-template-columns:repeat(4,1fr);gap:12px}.card{background:var(--card);border:1px solid var(--line);border-radius:16px;padding:16px;box-shadow:0 4px 18px #0b1f330d}.metric b{font-size:28px;display:block}.metric span{font-size:12px;color:var(--muted)}
.toolbar{display:flex;gap:10px;flex-wrap:wrap;margin:16px 0}.toolbar input,.toolbar select,.modal input,.modal textarea,.modal select{border:1px solid var(--line);border-radius:10px;padding:11px 12px;font:inherit;background:#fff}.toolbar input{flex:1;min-width:180px}.btn{border:0;border-radius:10px;padding:11px 14px;font-weight:700;background:var(--blue);color:#fff}.btn.secondary{background:#e8eef6;color:#17324d}.section-title{display:flex;justify-content:space-between;align-items:center;margin:22px 0 10px}.section-title h2{font-size:18px;margin:0}.section-title small{color:var(--muted)}
.table-wrap{overflow:auto;background:#fff;border:1px solid var(--line);border-radius:16px}table{width:100%;border-collapse:collapse;min-width:760px}th,td{text-align:left;padding:13px 12px;border-bottom:1px solid #edf1f5;font-size:13px}th{color:var(--muted);font-size:11px;text-transform:uppercase;letter-spacing:.04em;background:#fafbfd}.badge{display:inline-block;border-radius:999px;padding:5px 9px;font-size:11px;font-weight:800}.Ready{background:#dff5e8;color:var(--ok)}.In-use{background:#e1edff;color:#175cd3}.Repair{background:#fee4e2;color:var(--bad)}.Inspection{background:#fff0d6;color:var(--warn)}
.machine-no{font-weight:900}.brand-cell{color:var(--muted)}.empty{text-align:center;padding:28px;color:var(--muted)}
.modal-bg{display:none;position:fixed;inset:0;background:#00162e99;z-index:20;padding:20px;align-items:center;justify-content:center}.modal{background:#fff;width:min(520px,100%);border-radius:18px;padding:18px}.modal h3{margin:0 0 14px}.form-grid{display:grid;gap:10px}.modal textarea{min-height:90px;resize:vertical}.actions{display:flex;justify-content:flex-end;gap:8px;margin-top:12px}
footer{text-align:center;color:var(--muted);font-size:12px;padding:28px}
@media(max-width:760px){.grid{grid-template-columns:repeat(2,1fr)}header{position:static}.card{padding:13px}.metric b{font-size:24px}}
</style>
</head>
<body>
<header><div class="brand"><div class="mark">AC</div><div><h1>AssetCore</h1><p>Industrial Asset Management · HPWJ</p></div></div></header>
<main>
  <div class="grid">
    <div class="card metric"><b id="total">0</b><span>Общо машини</span></div>
    <div class="card metric"><b id="ready">0</b><span>Готови за работа</span></div>
    <div class="card metric"><b id="active">0</b><span>В експлоатация</span></div>
    <div class="card metric"><b id="repair">0</b><span>Ремонт / преглед</span></div>
  </div>

  <div class="section-title"><h2>Регистър на HPWJ машините</h2><small>AssetCore v1.0 Cloud</small></div>
  <div class="toolbar">
    <input id="search" placeholder="Търси по номер, марка или местоположение…" />
    <select id="filter"><option value="">Всички статуси</option><option>Ready</option><option>In use</option><option>Inspection</option><option>Repair</option></select>
    <button class="btn" onclick="openRepair()">+ Нов ремонт</button>
  </div>
  <div class="table-wrap"><table><thead><tr><th>№</th><th>Марка</th><th>Налягане</th><th>Статус</th><th>Местоположение</th><th>Промяна</th></tr></thead><tbody id="rows"></tbody></table></div>

  <div class="section-title"><h2>Последни ремонти</h2><small id="repairCount">0 записа</small></div>
  <div class="table-wrap"><table><thead><tr><th>Машина</th><th>Проблем</th><th>Действие</th><th>Резултат</th><th>Дата</th></tr></thead><tbody id="repairRows"><tr><td colspan="5" class="empty">Все още няма въведени ремонти.</td></tr></tbody></table></div>
</main>
<footer>AssetCore · Odessos Shiprepair & Conversion · Cloud prototype</footer>

<div class="modal-bg" id="modal"><div class="modal"><h3>Нов ремонтен запис</h3><div class="form-grid">
<input id="rMachine" placeholder="Номер на машина" />
<textarea id="rProblem" placeholder="Установен проблем"></textarea>
<textarea id="rAction" placeholder="Извършена работа"></textarea>
<input id="rResult" placeholder="Резултат / статус" />
</div><div class="actions"><button class="btn secondary" onclick="closeRepair()">Отказ</button><button class="btn" onclick="saveRepair()">Запази</button></div></div></div>
<script>
let machines=[];
const statusBg=s=>s.replaceAll(' ','-');
async function load(){machines=await fetch('/api/machines').then(r=>r.json()); render(); loadRepairs();}
function render(){
 const q=document.getElementById('search').value.toLowerCase(); const f=document.getElementById('filter').value;
 const filtered=machines.filter(m=>(!f||m.status===f)&&(`${m.number} ${m.brand} ${m.location}`.toLowerCase().includes(q)));
 rows.innerHTML=filtered.map(m=>`<tr><td class="machine-no">${m.number}</td><td class="brand-cell">${m.brand}</td><td>${m.pressure} bar</td><td><span class="badge ${statusBg(m.status)}">${m.status}</span></td><td>${m.location}</td><td><select onchange="changeStatus(${m.id},this.value)"><option selected disabled>Избери…</option><option>Ready</option><option>In use</option><option>Inspection</option><option>Repair</option></select></td></tr>`).join('')||'<tr><td colspan="6" class="empty">Няма намерени машини.</td></tr>';
 total.textContent=machines.length; ready.textContent=machines.filter(m=>m.status==='Ready').length; active.textContent=machines.filter(m=>m.status==='In use').length; repair.textContent=machines.filter(m=>['Repair','Inspection'].includes(m.status)).length;
}
async function changeStatus(id,status){await fetch('/api/machines/'+id,{method:'PATCH',headers:{'Content-Type':'application/json'},body:JSON.stringify({status})}); const m=machines.find(x=>x.id===id);m.status=status;render();}
async function loadRepairs(){const data=await fetch('/api/repairs').then(r=>r.json());repairCount.textContent=data.length+' записа';repairRows.innerHTML=data.length?data.map(r=>`<tr><td class="machine-no">${r.machine_number}</td><td>${r.problem}</td><td>${r.action||'—'}</td><td>${r.result||'—'}</td><td>${new Date(r.created_at).toLocaleString('bg-BG')}</td></tr>`).join(''):'<tr><td colspan="5" class="empty">Все още няма въведени ремонти.</td></tr>';}
function openRepair(){modal.style.display='flex'} function closeRepair(){modal.style.display='none'}
async function saveRepair(){if(!rMachine.value.trim()||!rProblem.value.trim()){alert('Въведи номер на машина и проблем.');return}await fetch('/api/repairs',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({machine_number:rMachine.value.trim(),problem:rProblem.value.trim(),action:rAction.value.trim(),result:rResult.value.trim()})});rMachine.value=rProblem.value=rAction.value=rResult.value='';closeRepair();loadRepairs();}
search.addEventListener('input',render);filter.addEventListener('change',render);load();
</script>
</body></html>'''
PY

EXPOSE 10000
CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT:-10000}"]
