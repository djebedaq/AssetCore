import { ArrowLeftRight, CircleCheck, Clock3, MapPin, Wrench } from 'lucide-react'

import AuthenticatedImage from '../../AuthenticatedImage'
import { statusText, useI18n } from '../../i18n'
import type { MachinePassport } from '../../types'

type Props = {
  machineId: number
  passport: MachinePassport
}

export function PassportHeroSummary({ machineId, passport }: Props) {
  const { date, locale, t } = useI18n()
  const { machine, current_state: state } = passport
  const category = machine.category_definition?.[`name_${locale}` as 'name_bg'] || machine.category || t('common.notSpecified')
  const machineDetails = [machine.brand, machine.model].filter(Boolean).join(' · ')
  const transferLocation = state.active_transfer
    ? [
      state.active_transfer.company_unit,
      state.active_transfer.department,
      state.active_transfer.vessel,
      state.active_transfer.dock,
      state.active_transfer.pier,
      state.active_transfer.work_area,
      state.active_transfer.location_text,
    ].filter(Boolean).join(' · ')
    : ''

  return <>
    <section className="passport-v2-hero" aria-labelledby="passport-machine-title">
      <AuthenticatedImage src={passport.qr_endpoint || `/machines/${machineId}/qr`} alt={t('machines.qrAlt', { number: machine.inventory_number })} />
      <div className="passport-v2-identity">
        <span className="eyebrow">{category}</span>
        <h2 id="passport-machine-title">{t('passport.machineNumber', { number: machine.inventory_number })}</h2>
        <strong>{machine.name}</strong>
        {machineDetails && <p>{machineDetails}</p>}
        {machine.pressure_bar ? <small>{t('machines.pressure')}: {machine.pressure_bar} bar</small> : null}
      </div>
      <dl className="passport-v2-state">
        <div><dt>{t('common.status')}</dt><dd><span className="badge">{statusText(t, machine.status)}</span></dd></div>
        <div><dt><MapPin size={14} aria-hidden="true" />{t('common.location')}</dt><dd>{machine.location?.name || t('common.notSpecified')}</dd></div>
        <div><dt><CircleCheck size={14} aria-hidden="true" />{t('passport.availability')}</dt><dd>{state.available ? t('bulk.available') : t('bulk.unavailable')}</dd></div>
      </dl>
    </section>

    <section className="passport-operational-summary" aria-labelledby="passport-operational-summary-title">
      <h3 id="passport-operational-summary-title">{t('passport.operationalSummary')}</h3>
      <div className="passport-summary-grid">
        <article>
          <header><ArrowLeftRight size={18} aria-hidden="true" /><span>{t('passport.activeTransfer')}</span></header>
          {state.active_transfer ? <>
            <strong>{state.active_transfer.protocol_number}</strong>
            {state.active_transfer.batch_reference && <small>{state.active_transfer.batch_reference}</small>}
            {transferLocation && <p>{transferLocation}</p>}
            {state.active_transfer.issued_at && <time>{date(state.active_transfer.issued_at)}</time>}
          </> : <p>{t('passport.noActiveTransfer')}</p>}
        </article>
        <article>
          <header><Wrench size={18} aria-hidden="true" /><span>{t('passport.activeRepair')}</span></header>
          {state.active_repair ? <>
            <strong>{state.active_repair.repair_reference || t('common.noValue')}</strong>
            <span className="badge">{statusText(t, state.active_repair.status, 'repair')}</span>
            {state.active_repair.reported_problem && <p>{state.active_repair.reported_problem}</p>}
            <time>{date(state.active_repair.opened_at)}</time>
          </> : <p>{t('passport.noActiveRepair')}</p>}
        </article>
        <article>
          <header><CircleCheck size={18} aria-hidden="true" /><span>{t('passport.lastCompletedRepair')}</span></header>
          {state.last_completed_repair ? <>
            <strong>{state.last_completed_repair.repair_reference || t('common.noValue')}</strong>
            <span className="badge">{statusText(t, state.last_completed_repair.status, 'repair')}</span>
            <time>{state.last_completed_repair.closed_at ? date(state.last_completed_repair.closed_at) : t('common.noValue')}</time>
          </> : <p>{t('passport.noCompletedRepair')}</p>}
        </article>
        <article>
          <header><Clock3 size={18} aria-hidden="true" /><span>{t('passport.lastTransfer')}</span></header>
          {state.last_transfer ? <>
            <strong>{state.last_transfer.protocol_number}</strong>
            <span>{state.last_transfer.is_active ? t('global.activeTransfer') : t('global.closedTransfer')}</span>
            {state.last_transfer.batch_reference && <small>{state.last_transfer.batch_reference}</small>}
            <time>{state.last_transfer.returned_at ? date(state.last_transfer.returned_at) : state.last_transfer.issued_at ? date(state.last_transfer.issued_at) : t('common.noValue')}</time>
          </> : <p>{t('passport.noTransferHistory')}</p>}
        </article>
        <article>
          <header><Clock3 size={18} aria-hidden="true" /><span>{t('passport.pendingPartRequests')}</span></header>
          <strong>{state.pending_part_requests?.count || 0}</strong>
          {state.pending_part_requests?.latest_request_reference
            ? <small>{state.pending_part_requests.latest_request_reference}</small>
            : <p>{t('passport.noPendingPartRequests')}</p>}
        </article>
      </div>
    </section>
  </>
}
