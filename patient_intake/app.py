#!/usr/bin/env python3
"""patient_intake/app.py — Flask UI для приёма пациента (история болезни).

Интегративная медицина LongevityCommon.
Запуск: python3 app.py
Открыть в браузере: http://localhost:5050
"""

import json
import os
import sqlite3
import uuid
from datetime import datetime
from pathlib import Path

from flask import Flask, request, jsonify, send_from_directory, render_template_string

app = Flask(__name__)
BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "patients.db"
BACKUP_DIR = BASE_DIR / "backups"

# --- SQLite ---
def init_db():
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("""
        CREATE TABLE IF NOT EXISTS patients (
            id TEXT PRIMARY KEY,
            created_at TEXT,
            updated_at TEXT,
            data_json TEXT
        )
    """)
    conn.commit()
    conn.close()

def save_patient(patient_id: str, data: dict):
    conn = sqlite3.connect(str(DB_PATH))
    now = datetime.now().isoformat()
    existing = conn.execute("SELECT id FROM patients WHERE id=?", (patient_id,)).fetchone()
    if existing:
        conn.execute("UPDATE patients SET updated_at=?, data_json=? WHERE id=?",
                     (now, json.dumps(data, ensure_ascii=False), patient_id))
    else:
        conn.execute("INSERT INTO patients (id, created_at, updated_at, data_json) VALUES (?,?,?,?)",
                     (patient_id, now, now, json.dumps(data, ensure_ascii=False)))
    conn.commit()
    conn.close()
    return patient_id

def get_patient(patient_id: str) -> dict | None:
    conn = sqlite3.connect(str(DB_PATH))
    row = conn.execute("SELECT data_json, created_at, updated_at FROM patients WHERE id=?", (patient_id,)).fetchone()
    conn.close()
    if row:
        data = json.loads(row[0])
        data["_created"] = row[1]
        data["_updated"] = row[2]
        return data
    return None

def list_patients() -> list:
    conn = sqlite3.connect(str(DB_PATH))
    rows = conn.execute("SELECT id, created_at, updated_at, json_extract(data_json, '$.full_name') as name FROM patients ORDER BY updated_at DESC").fetchall()
    conn.close()
    return [{"id": r[0], "created": r[1], "updated": r[2], "name": r[3] or "Без имени"} for r in rows]

# --- Backup to local JSON (and later to Google Drive) ---
def local_backup(patient_id: str, data: dict):
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    fname = f"{patient_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    path = BACKUP_DIR / fname
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return str(path)

# --- Routes ---
INDEX_HTML = """<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>AIM · Приём пациента</title>
<style>
  *,*::before,*::after{box-sizing:border-box}
  :root{--bg:#f4f5f7;--card:#fff;--border:#e2e4e9;--text:#1a1a2e;--soft:#6b7280;--accent:#4f46e5;--accent2:#10b981;--danger:#ef4444;--radius:10px}
  body{margin:0;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;background:var(--bg);color:var(--text);line-height:1.5}
  .topbar{background:linear-gradient(135deg,#1e1b4b,#312e81,#4338ca);color:#fff;padding:12px 24px;display:flex;align-items:center;gap:12px}
  .topbar h1{font-size:18px;font-weight:700;margin:0;letter-spacing:-0.01em}
  .topbar .dot{width:8px;height:8px;border-radius:50%;background:#34d399;box-shadow:0 0 6px #34d399}
  .container{max-width:1000px;margin:0 auto;padding:20px}
  .card{background:var(--card);border:1px solid var(--border);border-radius:var(--radius);padding:20px 24px;margin-bottom:16px}
  .card h2{font-size:15px;font-weight:600;margin:0 0 16px 0;color:var(--text);border-bottom:1px solid var(--border);padding-bottom:8px}
  .row{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:12px}
  .field{display:flex;flex-direction:column;gap:4px}
  .field label{font-size:12px;color:var(--soft);font-weight:500;text-transform:uppercase;letter-spacing:0.03em}
  .field input,.field select,.field textarea{border:1px solid var(--border);border-radius:6px;padding:8px 12px;font-size:14px;font-family:inherit;transition:border .15s}
  .field input:focus,.field select:focus,.field textarea:focus{outline:none;border-color:var(--accent);box-shadow:0 0 0 3px rgba(79,70,229,.1)}
  textarea{resize:vertical;min-height:60px}
  .btn{display:inline-flex;align-items:center;gap:6px;padding:10px 20px;border-radius:8px;font-size:14px;font-weight:600;border:none;cursor:pointer;transition:transform .1s,box-shadow .1s}
  .btn:hover{transform:translateY(-1px)}
  .btn-primary{background:var(--accent);color:#fff}
  .btn-success{background:var(--accent2);color:#fff}
  .btn-outline{background:#fff;color:var(--accent);border:1.5px solid var(--accent)}
  .btn-danger{background:#fff;color:var(--danger);border:1.5px solid var(--danger)}
  .actions{display:flex;gap:8px;flex-wrap:wrap;margin-top:16px}
  .toast{position:fixed;bottom:20px;right:20px;background:#1a1a2e;color:#fff;padding:12px 20px;border-radius:8px;font-size:14px;z-index:999;opacity:0;transition:opacity .3s;box-shadow:0 4px 12px rgba(0,0,0,.2)}
  .toast.show{opacity:1}
  .patient-list {margin-top:10px}
  .patient-list a{display:block;padding:8px 12px;border-radius:6px;color:var(--accent);text-decoration:none;font-size:14px;transition:background .1s}
  .patient-list a:hover{background:#eef2ff}
  .badge{display:inline-block;background:#eef2ff;color:var(--accent);font-size:11px;padding:2px 8px;border-radius:999px;margin-left:8px}
</style>
</head>
<body>
<div class="topbar">
  <div class="dot"></div>
  <h1>AIM · Приём пациента</h1>
  <span style="margin-left:auto;font-size:12px;opacity:.7">Интегративная медицина · LongevityCommon</span>
</div>
<div class="container">
  <div class="card">
    <h2>📋 Новая запись / Редактирование</h2>
    <form id="patientForm">
      <input type="hidden" id="patientId">
      <div class="row">
        <div class="field"><label>ФИО *</label><input id="full_name" required placeholder="Иванов Иван Иванович"></div>
        <div class="field"><label>Дата рождения</label><input type="date" id="dob"></div>
        <div class="field"><label>Пол</label><select id="gender"><option>М</option><option>Ж</option></select></div>
        <div class="field"><label>Телефон</label><input id="phone" placeholder="+995 XXX XXX XXX"></div>
        <div class="field"><label>Email</label><input type="email" id="email"></div>
        <div class="field"><label>Группа крови</label><select id="blood"><option></option><option>A+</option><option>A-</option><option>B+</option><option>B-</option><option>AB+</option><option>AB-</option><option>O+</option><option>O-</option></select></div>
      </div>
    </form>
  </div>

  <div class="card">
    <h2>🩺 Жалобы и анамнез</h2>
    <div class="row">
      <div class="field" style="grid-column:1/-1"><label>Основная жалоба</label><textarea id="chief_complaint" placeholder="Что беспокоит пациента..."></textarea></div>
      <div class="field" style="grid-column:1/-1"><label>История настоящего заболевания</label><textarea id="hpi" placeholder="Когда началось, динамика, что провоцирует/облегчает..."></textarea></div>
    </div>
  </div>

  <div class="card">
    <h2>💊 Хронические заболевания и терапия</h2>
    <div class="row">
      <div class="field" style="grid-column:1/-1"><label>Перенесённые и хронические заболевания</label><textarea id="pmh" placeholder="Диагнозы, операции, госпитализации..."></textarea></div>
      <div class="field" style="grid-column:1/-1"><label>Принимаемые препараты</label><textarea id="medications" placeholder="Название, доза, как долго..."></textarea></div>
      <div class="field" style="grid-column:1/-1"><label>Аллергии</label><textarea id="allergies" placeholder="Лекарства, пища, другое..."></textarea></div>
      <div class="field" style="grid-column:1/-1"><label>БАДы и добавки</label><textarea id="supplements" placeholder="Витамины, травы, пробиотики..."></textarea></div>
    </div>
  </div>

  <div class="card">
    <h2>🧬 Интегративный / Longevity профиль</h2>
    <div class="row">
      <div class="field"><label>χ_Ze (если измерялся)</label><input id="chi_ze" type="number" step="0.001" min="0" max="1" placeholder="0.000"></div>
      <div class="field"><label>Дата χ_Ze</label><input type="date" id="chi_ze_date"></div>
      <div class="field"><label>Сон (часов/сут)</label><input id="sleep_hours" type="number" step="0.5" min="0" max="24" placeholder="7"></div>
      <div class="field"><label>Качество сна (1-10)</label><input id="sleep_quality" type="number" min="1" max="10" placeholder="7"></div>
      <div class="field"><label>Физическая активность</label><select id="exercise"><option></option><option>Сидячий</option><option>Лёгкая 1-2 р/нед</option><option>Умеренная 3-4 р/нед</option><option>Интенсивная 5+ р/нед</option></select></div>
      <div class="field"><label>Питание</label><select id="diet"><option></option><option>Стандартное</option><option>Средиземноморское</option><option>Кето/LCHF</option><option>Вегетарианское</option><option>Веганское</option><option>Интервальное голодание</option></select></div>
      <div class="field"><label>Курение</label><select id="smoking"><option></option><option>Нет</option><option>Бросил</option><option>Да</option></select></div>
      <div class="field"><label>Алкоголь</label><select id="alcohol"><option></option><option>Нет</option><option>Редко</option><option>Умеренно</option><option>Часто</option></select></div>
      <div class="field"><label>Стресс (1-10)</label><input id="stress" type="number" min="1" max="10" placeholder="5"></div>
      <div class="field"><label>Семейный анамнез (долголетие)</label><textarea id="family_longevity" placeholder="Возраст родителей, бабушек/дедушек, причины смерти..."></textarea></div>
    </div>
  </div>

  <div class="card">
    <h2>🔬 Лабораторные данные (выборочно)</h2>
    <div class="row">
      <div class="field"><label>Глюкоза (ммоль/л)</label><input id="lab_glucose" type="number" step="0.1" placeholder="4.0-6.0"></div>
      <div class="field"><label>HbA1c (%)</label><input id="lab_hba1c" type="number" step="0.1" placeholder="<5.7"></div>
      <div class="field"><label>Общий холестерин (ммоль/л)</label><input id="lab_chol" type="number" step="0.1"></div>
      <div class="field"><label>ЛПНП</label><input id="lab_ldl" type="number" step="0.1"></div>
      <div class="field"><label>ЛПВП</label><input id="lab_hdl" type="number" step="0.1"></div>
      <div class="field"><label>СРБ (мг/л)</label><input id="lab_crp" type="number" step="0.1" placeholder="<3.0"></div>
      <div class="field"><label>Ферритин (нг/мл)</label><input id="lab_ferritin" type="number" step="0.1"></div>
      <div class="field"><label>Витамин D (нг/мл)</label><input id="lab_vitd" type="number" step="0.1"></div>
      <div class="field"><label>ТТГ (мМЕ/л)</label><input id="lab_tsh" type="number" step="0.01"></div>
      <div class="field"><label>Теломерная длина (kb)</label><input id="lab_telomere" type="number" step="0.1"></div>
    </div>
  </div>

  <div class="card">
    <h2>📝 Заключение врача</h2>
    <div class="row">
      <div class="field" style="grid-column:1/-1"><label>Диагноз (рабочий)</label><textarea id="diagnosis" placeholder="Основной, сопутствующие..."></textarea></div>
      <div class="field" style="grid-column:1/-1"><label>MCOA-профиль (оценка счётчиков)</label><textarea id="mcoa_profile" placeholder="C#1 Центриолярный: ?&#10;C#2 Теломерный: ?&#10;C#3 Митохондриальный: ?&#10;C#4 Эпигенетический: ?&#10;C#5 Протеостаз: ?"></textarea></div>
      <div class="field" style="grid-column:1/-1"><label>Рекомендации</label><textarea id="recommendations" placeholder="Назначения, направления, контроль..."></textarea></div>
      <div class="field" style="grid-column:1/-1"><label>Заметки</label><textarea id="notes"></textarea></div>
    </div>
  </div>

  <div class="actions">
    <button class="btn btn-primary" onclick="savePatient()">💾 Сохранить</button>
    <button class="btn btn-success" onclick="saveAndBackup()">☁️ Сохранить + Backup в Google Drive</button>
    <button class="btn btn-outline" onclick="newPatient()">📄 Новый пациент</button>
    <span id="saveStatus" style="font-size:13px;color:var(--soft);align-self:center"></span>
  </div>

  <div class="card" style="margin-top:20px">
    <h2>📂 Сохранённые пациенты</h2>
    <div class="patient-list" id="patientList">Загрузка...</div>
  </div>
</div>
<div class="toast" id="toast"></div>

<script>
const API = '';
let currentId = null;

function showToast(msg, ok=true){const t=document.getElementById('toast');t.textContent=msg;t.style.background=ok?'#1a1a2e':'#7f1d1d';t.classList.add('show');setTimeout(()=>t.classList.remove('show'),3000)}

function collectData(){
  const fields=['full_name','dob','gender','phone','email','blood',
    'chief_complaint','hpi','pmh','medications','allergies','supplements',
    'chi_ze','chi_ze_date','sleep_hours','sleep_quality','exercise','diet','smoking','alcohol','stress','family_longevity',
    'lab_glucose','lab_hba1c','lab_chol','lab_ldl','lab_hdl','lab_crp','lab_ferritin','lab_vitd','lab_tsh','lab_telomere',
    'diagnosis','mcoa_profile','recommendations','notes'];
  const d={};
  fields.forEach(f=>{const el=document.getElementById(f);d[f]=el?(el.value||''):''});
  if(currentId) d._id = currentId;
  return d;
}

function fillForm(data){
  for(const [k,v] of Object.entries(data)){
    if(k.startsWith('_')) continue;
    const el=document.getElementById(k);
    if(el) el.value = v;
  }
}

async function savePatient(){
  const data=collectData();
  if(!data.full_name){showToast('⚠ Введите ФИО',false);return}
  const resp=await fetch(API+'/api/save',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)});
  const r=await resp.json();
  if(r.ok){currentId=r.id;document.getElementById('patientId').value=r.id;showToast('✅ Сохранено: '+r.id);loadPatientList()}
  else showToast('❌ '+r.error,false)
}

async function saveAndBackup(){
  const data=collectData();
  if(!data.full_name){showToast('⚠ Введите ФИО',false);return}
  const resp=await fetch(API+'/api/save_and_backup',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)});
  const r=await resp.json();
  if(r.ok){currentId=r.id;document.getElementById('patientId').value=r.id;showToast('☁️ Сохранено + бэкап: '+r.backup);loadPatientList()}
  else showToast('❌ '+r.error,false)
}

function newPatient(){currentId=null;document.getElementById('patientId').value='';document.getElementById('patientForm').reset();showToast('📄 Новый пациент')}

async function loadPatient(id){
  const resp=await fetch(API+'/api/get/'+id);
  const r=await resp.json();
  if(r.ok){currentId=r.data._id||id;document.getElementById('patientId').value=currentId;fillForm(r.data);showToast('📂 Загружен: '+r.data.full_name)}
  else showToast('❌ Не найден',false)
}

async function loadPatientList(){
  const resp=await fetch(API+'/api/list');
  const r=await resp.json();
  const div=document.getElementById('patientList');
  if(!r.patients||!r.patients.length){div.innerHTML='<span style="color:var(--soft)">Нет сохранённых пациентов</span>';return}
  div.innerHTML=r.patients.map(p=>
    `<a href="#" onclick="loadPatient('${p.id}');return false">📋 ${p.name} <span class="badge">${p.updated?.slice(0,10)||''}</span></a>`
  ).join('')
}

document.addEventListener('DOMContentLoaded',loadPatientList);
</script>
</body>
</html>"""

@app.route("/")
def index():
    return INDEX_HTML

@app.route("/api/save", methods=["POST"])
def api_save():
    data = request.get_json(force=True)
    pid = data.pop("_id", None) or str(uuid.uuid4())[:8]
    if not data.get("full_name"):
        return jsonify(ok=False, error="full_name required")
    save_patient(pid, data)
    return jsonify(ok=True, id=pid)

@app.route("/api/save_and_backup", methods=["POST"])
def api_save_and_backup():
    data = request.get_json(force=True)
    pid = data.pop("_id", None) or str(uuid.uuid4())[:8]
    if not data.get("full_name"):
        return jsonify(ok=False, error="full_name required")
    save_patient(pid, data)
    backup_path = local_backup(pid, data)
    # Try Google Drive backup
    gdrive_msg = ""
    try:
        from gdrive_backup import backup_to_gdrive
        gdrive_msg = backup_to_gdrive(pid, data, str(BACKUP_DIR))
    except Exception as e:
        gdrive_msg = f"GDrive: {e}"
    return jsonify(ok=True, id=pid, backup=backup_path, gdrive=gdrive_msg)

@app.route("/api/get/<pid>")
def api_get(pid):
    data = get_patient(pid)
    if data:
        return jsonify(ok=True, data=data)
    return jsonify(ok=False, error="not found")

@app.route("/api/list")
def api_list():
    return jsonify(patients=list_patients())

@app.route("/backups/<path:filename>")
def serve_backup(filename):
    return send_from_directory(str(BACKUP_DIR), filename)

if __name__ == "__main__":
    init_db()
    print(f"\n  🏥 AIM Patient Intake запущен: http://localhost:5050\n")
    app.run(host="0.0.0.0", port=5050, debug=True)
