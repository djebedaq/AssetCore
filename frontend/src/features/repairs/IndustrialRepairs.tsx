import { type FormEvent, useEffect, useRef, useState } from 'react'
import { ChevronRight, FileText, Plus, Upload } from 'lucide-react'

import {
  AttachmentList,
  DOCUMENT_KEYS,
  DocumentButtons,
  Modal,
  filePayload,
  friendlyError,
  translatedCode,
  translatedEventCode,
} from '../../industrialUi'
import { statusText, useI18n, type TranslationKey } from '../../i18n'
import { hasPermission } from '../../permissions'
import type { CatalogPartEnhanced, Machine, RepairCase } from '../../types'
import { repairApi } from './repairApi'
import {
  canonicalRepairStage,
  durationText,
  repairFormFrom,
  repairStageOrder,
  repairStagePayload,
  repairStageTitleKeys,
  type RepairFormState,
} from './workflow'

function RepairCreateModal({ machines, onClose, onSaved }: { machines: Machine[]; onClose: () => void; onSaved: () => void }) {
  const { t } = useI18n()
  const eligible = machines.filter((machine) => machine.status === 'READY')
  const [form, setForm] = useState({ machine_id: eligible[0]?.id || 0, reported_problem: '', condition_before: '' })
  const [error, setError] = useState('')
  async function submit(event: FormEvent) {
    event.preventDefault()
    try {
      await repairApi.create(form)
      onSaved()
    } catch (caught) { setError(friendlyError(caught, t('repairs.saveError'))) }
  }
  return <Modal title={t('repairs.acceptTitle')} onClose={onClose}><form className="form-grid" onSubmit={submit}>
    <label>{t('repairs.machine')}<select value={form.machine_id} onChange={(event) => setForm({ ...form, machine_id: Number(event.target.value) })}>{eligible.map((machine) => <option key={machine.id} value={machine.id}>{machine.name} · {statusText(t, machine.status)}</option>)}</select></label>
    <label className="wide">{t('repairs.reportedProblem')}<textarea required value={form.reported_problem} onChange={(event) => setForm({ ...form, reported_problem: event.target.value })} /></label>
    <label className="wide">{t('repairCase.conditionBefore')}<textarea required value={form.condition_before} onChange={(event) => setForm({ ...form, condition_before: event.target.value })} /></label>
    {error && <div className="error wide">{error}</div>}<div className="actions wide"><button type="button" className="secondary" onClick={onClose}>{t('common.cancel')}</button><button className="primary" disabled={!eligible.length}>{t('repairCase.accept')}</button></div>
  </form></Modal>
}

function RepairWorkspace({ repairId, onClose, onChanged }: { repairId: number; onClose: () => void; onChanged: () => void }) {
  const { date, t } = useI18n()
  const [repair, setRepair] = useState<RepairCase | null>(null)
  const [form, setForm] = useState<RepairFormState | null>(null)
  const [savedForm, setSavedForm] = useState('')
  const [editingStage, setEditingStage] = useState<number | null>(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [catalog, setCatalog] = useState<CatalogPartEnhanced[]>([])
  const [partDraft, setPartDraft] = useState({ catalog_part_id: '', quantity: 1 })
  const [participantDraft, setParticipantDraft] = useState({ full_name: '', job_title: '', contribution: '', hours: '', minutes: '' })
  const [participantBusy, setParticipantBusy] = useState(false)
  const fileRef = useRef<HTMLInputElement>(null)
  const load = (preserveDraft = false) => repairApi.get(repairId).then(async (data) => {
    const partItems = await repairApi.verifiedParts(data.machine_id)
    setRepair(data)
    setCatalog(partItems)
    if (!preserveDraft) {
      const canonical = repairFormFrom(data)
      setForm(canonical)
      setSavedForm(JSON.stringify(canonical))
    }
    setError('')
  }).catch((caught) => setError(friendlyError(caught, t('repairCase.loadError'))))
  useEffect(() => { void load(false) }, [repairId])
  const dirty = form !== null && JSON.stringify(form) !== savedForm
  useEffect(() => {
    const warn = (event: BeforeUnloadEvent) => { if (dirty) event.preventDefault() }
    window.addEventListener('beforeunload', warn)
    return () => window.removeEventListener('beforeunload', warn)
  }, [dirty])
  function closeWorkspace() {
    if (dirty && !window.confirm(t('repairCase.unsavedConfirm'))) return
    onClose()
  }
  async function save(stage: number, advance = false) {
    if (!repair || !form) return
    if (stage === 3 && advance && !window.confirm(t('repairCase.completeConfirm'))) return
    setBusy(true)
    setError('')
    const payload = repairStagePayload(form, stage, advance)
    try {
      await repairApi.update(repair.id, payload)
      setEditingStage(null)
      await load(false); onChanged()
    } catch (caught) { setError(friendlyError(caught, advance ? t('repairCase.transitionError') : t('repairCase.saveError'))) } finally { setBusy(false) }
  }
  async function upload(file?: File) {
    if (!file || !repair) return
    try { await repairApi.upload(repair.id, { ...(await filePayload(file)), stage: repairStageOrder[canonicalRepairStage(repair)], description: file.name }); await load(true) } catch (caught) { setError(friendlyError(caught, t('passport.uploadError'))) }
  }
  async function generate() {
    if (!repair) return
    try { await repairApi.generateDocuments(repair.id); await load(true); onChanged() } catch (caught) { setError(friendlyError(caught, t('repairCase.documentError'))) }
  }
  async function addPart(event: FormEvent) {
    event.preventDefault()
    if (!repair || !partDraft.catalog_part_id) return
    const part = catalog.find((item) => item.id === Number(partDraft.catalog_part_id))
    if (!part) return
    try {
      await repairApi.addPart(repair.id, { catalog_part_id: part.id, part_number: part.part_number, description: part.description, quantity: partDraft.quantity, unit: part.unit, source: part.source_document })
      setPartDraft({ catalog_part_id: '', quantity: 1 })
      await load(true)
      onChanged()
    } catch (caught) { setError(friendlyError(caught, t('repairCase.partError'))) }
  }
  async function addParticipant(event: FormEvent) {
    event.preventDefault()
    if (!repair || !participantDraft.full_name.trim()) return
    const minutesWorked = (Number(participantDraft.hours) || 0) * 60 + (Number(participantDraft.minutes) || 0)
    if (minutesWorked < 1) { setError(t('repairCase.participantTimeRequired')); return }
    if (participantBusy) return
    setParticipantBusy(true)
    setError('')
    try {
      await repairApi.addParticipant(repair.id, {
        full_name: participantDraft.full_name.trim(),
        job_title: participantDraft.job_title.trim() || null,
        contribution: participantDraft.contribution.trim() || null,
        minutes_worked: minutesWorked,
      })
      setParticipantDraft({ full_name: '', job_title: '', contribution: '', hours: '', minutes: '' })
      await load(true); onChanged()
    } catch (caught) { setError(friendlyError(caught, t('repairCase.participantError'))) }
    finally { setParticipantBusy(false) }
  }
  async function removeParticipant(id: number) {
    if (!repair) return
    try { await repairApi.removeParticipant(repair.id, id); await load(true); onChanged() }
    catch (caught) { setError(friendlyError(caught, t('repairCase.participantError'))) }
  }
  if (!repair || !form) return <Modal title={t('common.loading')} onClose={closeWorkspace} wide><div className="loading">{t('common.loading')}</div></Modal>
  const currentStage = canonicalRepairStage(repair)
  const viewedStage = editingStage ?? currentStage
  const canEdit = hasPermission('repairs.edit') && repair.status !== 'COMPLETED'
  const summaryRows: Array<Array<[TranslationKey, string]>> = [
    [['repairs.reportedProblem', repair.reported_problem], ['repairCase.conditionBefore', repair.condition_before || '']],
    [['repairCase.removedParts', repair.removed_parts_text || ''], ['repairCase.diagnosticCleaning', repair.diagnostic_cleaning || ''], ['repairs.diagnosisField', repair.diagnosis || ''], ['repairCase.requiredWork', repair.required_work || ''], ['repairCase.requiredParts', repair.required_parts_text || ''], ['repairCase.diagnosisMinutes', durationText(repair.diagnosis_minutes, t)]],
    [['repairs.workField', repair.work_performed || ''], ['repairCase.repairMinutes', durationText(repair.repair_minutes, t)], ['repairCase.section.parts', t('repairCase.partCount', { count: repair.parts_used.length })]],
    [['repairCase.testMethod', repair.test_method || ''], ['repairs.testResult', repair.test_details || ''], ['repairCase.conditionAfter', repair.condition_after || ''], ['repairCase.result', repair.result || ''], ['repairCase.testingMinutes', durationText(repair.testing_minutes, t)], ['repairCase.section.participants', t('repairCase.participantCount', { count: repair.participants.length })]],
  ]
  return <Modal title={repair.repair_reference || t('common.loading')} onClose={closeWorkspace} wide>{error && <div className="error" role="alert">{error}</div>}
    <div className="repair-wizard-head"><div><h4>{repair.machine_name} · №{repair.machine_number}</h4><p className="muted">{t('repairCase.currentStage', { stage: t(repairStageTitleKeys[repairStageOrder[currentStage]]) })}</p></div><div className="repair-time-totals"><span>{t('repairCase.totalStageTime')}: {durationText(repair.total_work_minutes, t)}</span><span>{t('repairCase.totalParticipantTime')}: {durationText(repair.participant_total_minutes, t)}</span></div></div>
    <div className="workflow-strip repair-wizard-strip" aria-label={t('repairCase.stageProgress')}>{repairStageOrder.map((stage, index) => { const state = repair.status === 'COMPLETED' || index < currentStage ? 'completed' : index === currentStage ? 'active' : 'unavailable'; return <span aria-current={state === 'active' ? 'step' : undefined} aria-disabled={state === 'unavailable'} className={state} key={stage}><b>{index + 1}</b>{t(repairStageTitleKeys[stage])}</span> })}</div>
    <div className="repair-stage-cards">{repairStageOrder.map((stage, index) => <section className={`${index === viewedStage ? 'active' : ''} ${index > currentStage ? 'future' : ''}`} key={stage}><div className="repair-stage-card-head"><div><small>{t('repairCase.stageNumber', { number: index + 1 })}</small><h5>{t(repairStageTitleKeys[stage])}</h5></div>{index < currentStage && canEdit && <button className="link" type="button" onClick={() => setEditingStage(index)}>{t('common.edit')}</button>}</div>{index < currentStage && index !== viewedStage && <dl className="repair-stage-summary">{summaryRows[index].filter(([, value]) => value).map(([key, value]) => <div key={key}><dt>{t(key)}</dt><dd>{value}</dd></div>)}</dl>}{index > currentStage && <p className="muted">{t('repairCase.futureStage')}</p>}</section>)}</div>
    <div className="repair-workspace-grid"><section className="repair-stage-editor"><h4>{t(repairStageTitleKeys[repairStageOrder[viewedStage]])}</h4>
      {viewedStage === 0 && <div className="form-grid"><label className="wide">{t('repairs.reportedProblem')}<textarea required value={form.reported_problem} onChange={(event) => setForm({ ...form, reported_problem: event.target.value })} /></label><label className="wide">{t('repairCase.conditionBefore')}<textarea required value={form.condition_before} onChange={(event) => setForm({ ...form, condition_before: event.target.value })} /></label></div>}
      {viewedStage === 1 && <div className="form-grid"><label className="wide">{t('repairCase.removedParts')}<textarea value={form.removed_parts_text} onChange={(event) => setForm({ ...form, removed_parts_text: event.target.value })} /></label><label className="wide">{t('repairCase.diagnosticCleaning')}<textarea value={form.diagnostic_cleaning} onChange={(event) => setForm({ ...form, diagnostic_cleaning: event.target.value })} /></label><label className="wide">{t('repairs.diagnosisField')}<textarea required value={form.diagnosis} onChange={(event) => setForm({ ...form, diagnosis: event.target.value })} /></label><label className="wide">{t('repairCase.requiredWork')}<textarea required value={form.required_work} onChange={(event) => setForm({ ...form, required_work: event.target.value })} /></label><label className="wide">{t('repairCase.requiredParts')}<textarea value={form.required_parts_text} onChange={(event) => setForm({ ...form, required_parts_text: event.target.value })} /></label><label>{t('repairCase.diagnosisMinutes')}<input required type="number" min="1" max="100000" value={form.diagnosis_minutes} onChange={(event) => setForm({ ...form, diagnosis_minutes: event.target.value })} /></label></div>}
      {viewedStage === 2 && <><div className="form-grid"><label className="wide">{t('repairs.workField')}<textarea required value={form.work_performed} onChange={(event) => setForm({ ...form, work_performed: event.target.value })} /></label><label>{t('repairCase.repairMinutes')}<input required type="number" min="1" max="100000" value={form.repair_minutes} onChange={(event) => setForm({ ...form, repair_minutes: event.target.value })} /></label></div><section className="repair-parts"><h4>{t('repairCase.section.parts')}</h4><div className="request-line-list">{repair.parts_used.map((part) => <div key={part.id}><span><b>{part.part_number || t('common.noValue')}</b><small>{part.description}{part.source ? ` · ${part.source}` : ''}</small></span><em>{part.quantity} {part.unit}</em></div>)}{!repair.parts_used.length && <div className="empty-state">{t('repairCase.noParts')}</div>}</div>{canEdit && <form className="repair-part-form" onSubmit={addPart}><label>{t('repairCase.catalogPart')}<select required value={partDraft.catalog_part_id} onChange={(event) => setPartDraft({ ...partDraft, catalog_part_id: event.target.value })}><option value="">{t('common.notSpecified')}</option>{catalog.map((part) => <option value={part.id} key={part.id}>{part.part_number} · {part.description}</option>)}</select></label><label>{t('common.quantity')}<input required min="0.01" step="0.01" type="number" value={partDraft.quantity} onChange={(event) => setPartDraft({ ...partDraft, quantity: Number(event.target.value) })} /></label><button className="secondary" disabled={!partDraft.catalog_part_id || partDraft.quantity <= 0}><Plus size={15} />{t('repairCase.addPart')}</button></form>}</section></>}
      {viewedStage === 3 && <><div className="form-grid"><label>{t('repairCase.testPassed')}<select required value={form.test_passed} onChange={(event) => setForm({ ...form, test_passed: event.target.value })}><option value="">{t('common.notSpecified')}</option><option value="no">{t('common.no')}</option><option value="yes">{t('common.yes')}</option></select></label><label>{t('repairCase.testMethod')}<input required value={form.test_method} onChange={(event) => setForm({ ...form, test_method: event.target.value })} /></label><label>{t('repairCase.testPressure')}<input type="number" min="0" max="10000" value={form.test_pressure_bar} onChange={(event) => setForm({ ...form, test_pressure_bar: event.target.value })} /></label><label>{t('repairCase.testingMinutes')}<input required type="number" min="1" max="100000" value={form.testing_minutes} onChange={(event) => setForm({ ...form, testing_minutes: event.target.value })} /></label><label>{t('repairCase.leaksDetected')}<select value={form.leaks_detected} onChange={(event) => setForm({ ...form, leaks_detected: event.target.value })}><option value="">{t('common.notSpecified')}</option><option value="no">{t('common.no')}</option><option value="yes">{t('common.yes')}</option></select></label><label>{t('repairCase.electricalTest')}<input value={form.electrical_test_result} onChange={(event) => setForm({ ...form, electrical_test_result: event.target.value })} /></label><label>{t('repairCase.functionalTest')}<input value={form.functional_test_result} onChange={(event) => setForm({ ...form, functional_test_result: event.target.value })} /></label><label className="wide">{t('repairs.testResult')}<textarea required value={form.test_details} onChange={(event) => setForm({ ...form, test_details: event.target.value })} /></label><label className="wide">{t('repairCase.conditionAfter')}<textarea required value={form.condition_after} onChange={(event) => setForm({ ...form, condition_after: event.target.value })} /></label><label className="wide">{t('repairCase.result')}<textarea required value={form.result} onChange={(event) => setForm({ ...form, result: event.target.value })} /></label></div><section className="repair-parts"><h4>{t('repairCase.section.participants')}</h4><div className="request-line-list">{repair.participants.map((participant) => <div key={participant.id}><span><b>{participant.full_name}</b><small>{[participant.job_title, participant.contribution, durationText(participant.minutes_worked, t)].filter(Boolean).join(' · ')}</small></span>{canEdit && <button className="link" type="button" onClick={() => void removeParticipant(participant.id)}>{t('common.remove')}</button>}</div>)}{!repair.participants.length && <div className="empty-state">{t('repairCase.noParticipants')}</div>}</div>{canEdit && <form className="repair-part-form repair-participant-form" onSubmit={addParticipant}><label>{t('repairCase.participantName')}<input required value={participantDraft.full_name} onChange={(event) => setParticipantDraft({ ...participantDraft, full_name: event.target.value })} /></label><label>{t('repairCase.participantJobTitle')}<input value={participantDraft.job_title} onChange={(event) => setParticipantDraft({ ...participantDraft, job_title: event.target.value })} /></label><label>{t('repairCase.participantContribution')}<input value={participantDraft.contribution} onChange={(event) => setParticipantDraft({ ...participantDraft, contribution: event.target.value })} /></label><label>{t('repairCase.participantHours')}<input type="number" min="0" max="1666" value={participantDraft.hours} onChange={(event) => setParticipantDraft({ ...participantDraft, hours: event.target.value })} /></label><label>{t('repairCase.participantMinutes')}<input type="number" min="0" max="59" value={participantDraft.minutes} onChange={(event) => setParticipantDraft({ ...participantDraft, minutes: event.target.value })} /></label><button className="secondary" disabled={participantBusy || !participantDraft.full_name.trim()}><Plus size={15} />{participantBusy ? t('repairCase.addingParticipant') : t('repairCase.addParticipant')}</button></form>}</section></>}
      {canEdit && <div className="repair-action-footer"><div>{editingStage !== null && <button className="secondary" type="button" onClick={() => { setEditingStage(null); const canonical = repairFormFrom(repair); setForm(canonical); setSavedForm(JSON.stringify(canonical)) }}>{t('common.cancel')}</button>}</div><div className="actions"><button disabled={busy} className="secondary" type="button" onClick={() => void save(viewedStage, false)}>{t('common.save')}</button>{editingStage === null && currentStage < 3 && <button disabled={busy} className="primary" type="button" onClick={() => void save(currentStage, true)}>{currentStage === 0 ? t('repairCase.continueDiagnosis') : currentStage === 1 ? t('repairCase.continueRepair') : t('repairCase.continueCompletion')}<ChevronRight size={15} /></button>}{editingStage === null && currentStage === 3 && <button disabled={busy} className="primary" type="button" onClick={() => void save(3, true)}>{t('repairCase.finishAndGenerate')}</button>}</div></div>}
    </section><aside><details><summary>{t('repairCase.section.timeline')}</summary><div className="timeline compact-timeline">{repair.events.map((event) => <div key={event.id}><i /><span><b>{translatedEventCode(t, event.event_type)}</b>{event.description && ['NOTE', 'REPAIR_ACTION', 'DIAGNOSIS', 'TEST', 'PARTS', 'PART_ADDED', 'PARTICIPANT_ADDED', 'PARTICIPANT_REMOVED', 'ATTACHMENT_ADDED', 'DOCUMENT_GENERATED'].includes(event.event_type) && <em>{event.description}</em>}<small>{date(event.created_at)} · {statusText(t, event.status_after || repair.status, 'repair')}</small></span></div>)}</div></details></aside></div>
    <details className="repair-secondary"><summary>{t('repairCase.section.attachments')}</summary><div className="toolbar"><div /><div className="actions">{canEdit && <><input ref={fileRef} hidden type="file" accept="image/png,image/jpeg,image/webp,application/pdf,.docx" onChange={(event) => void upload(event.target.files?.[0])} /><button className="secondary" onClick={() => fileRef.current?.click()}><Upload size={16} />{t('passport.addFile')}</button></>}{repair.status === 'COMPLETED' && <button className="primary" onClick={() => void generate()}><FileText size={16} />{t('repairCase.generateProtocolBg')}</button>}</div></div><AttachmentList items={repair.attachments} /></details>
    <div className="document-list">{repair.generated_documents.map((document) => <div key={document.id}><span><b>{document.document_number}</b><small>{translatedCode(t, document.document_type, DOCUMENT_KEYS)} · {date(document.created_at)}</small></span><DocumentButtons path={document.download_endpoint} filename={document.filename} format={document.format} /></div>)}</div>
  </Modal>
}

export function IndustrialRepairs() {
  const { date, t } = useI18n()
  const [items, setItems] = useState<RepairCase[]>([])
  const [machines, setMachines] = useState<Machine[]>([])
  const [selected, setSelected] = useState<number | null>(null)
  const [create, setCreate] = useState(false)
  const [error, setError] = useState('')
  const load = () => Promise.all([repairApi.list(), repairApi.machines()]).then(([repairs, machineItems]) => { setItems(repairs); setMachines(machineItems); setError('') }).catch((caught) => setError(friendlyError(caught, t('repairCase.loadError'))))
  useEffect(() => { void load() }, [])
  return <><div className="toolbar"><div><h3>{t('repairs.title')}</h3><p className="muted">{t('repairCase.workflowHint')}</p></div>{hasPermission('repairs.create') && <button className="primary" onClick={() => setCreate(true)}><Plus size={18} />{t('repairs.new')}</button>}</div>{error && <div className="error">{error}</div>}<div className="cards-list">{items.map((repair) => { const stage = canonicalRepairStage(repair); return <button className="repair-card repair-card-button" key={repair.id} onClick={() => setSelected(repair.id)}><div><span className="badge">{t(repairStageTitleKeys[repairStageOrder[stage]])}</span><h3>{repair.machine_name} · {repair.repair_reference}</h3><p><b>{t('repairs.problem')}</b> {repair.reported_problem}</p><div className="workflow-checks">{repairStageOrder.map((item, index) => <span className={repair.status === 'COMPLETED' || index <= stage ? 'done' : ''} key={item}>{t(repairStageTitleKeys[item])}</span>)}</div></div><div className="repair-side"><small>{date(repair.opened_at)}</small><ChevronRight /></div></button> })}{!items.length && <div className="empty-state">{t('repairs.empty')}</div>}</div>{create && <RepairCreateModal machines={machines} onClose={() => setCreate(false)} onSaved={() => { setCreate(false); void load() }} />}{selected && <RepairWorkspace repairId={selected} onClose={() => setSelected(null)} onChanged={() => void load()} />}</>
}
