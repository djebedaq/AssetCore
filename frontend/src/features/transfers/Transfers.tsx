import { useEffect, useState } from 'react'
import { api, downloadApiFile } from '../../api'
import BulkTransfers from './BulkTransfers'
import { useI18n } from '../../i18n'
import type { Machine } from '../../types'

type TransferRecord = {
  id: number
  protocol_number: string
  batch_reference?: string | null
  is_active: boolean
  company_unit?: string | null
  vessel?: string | null
  location_text?: string | null
  issued_at?: string | null
  returned_at?: string | null
  created_at: string
  machine: Machine
}

export default function Transfers() {
  const { date, t } = useI18n()
  const [items, setItems] = useState<TransferRecord[]>([])
  const [error, setError] = useState('')
  const load = () => api<TransferRecord[]>('/transfers')
    .then((records) => {
      setItems(records)
      setError('')
    })
    .catch(() => setError(t('transfers.loadError')))

  useEffect(() => { void load() }, [t])

  const download = (path: string, name: string) => downloadApiFile(path, name)
    .catch(() => setError(t('transfers.downloadError')))

  return (
    <>
      <div className="toolbar"><div><h3>{t('transfers.title')}</h3><p className="muted">{t('transfers.subtitle')}</p></div></div>
      {error && <div className="error" role="alert">{error}</div>}
      <BulkTransfers onChanged={() => { void load() }} />
      <div className="toolbar protocol-history-title"><div><h3>{t('transfers.historyTitle')}</h3><p className="muted">{t('transfers.historySubtitle')}</p></div></div>
      <div className="table-card">
        <table>
          <thead><tr><th>{t('transfers.number')}</th><th>{t('transfers.batch')}</th><th>{t('common.machine')}</th><th>{t('common.status')}</th><th>{t('transfers.companyLocation')}</th><th>{t('transfers.issueReturn')}</th><th>{t('transfers.documents')}</th></tr></thead>
          <tbody>{items.map((transfer) => (
            <tr key={transfer.id}>
              <td><strong>{transfer.protocol_number}</strong></td>
              <td>{transfer.batch_reference || t('common.noValue')}</td>
              <td>{transfer.machine.name}</td>
              <td><span className="badge">{transfer.is_active ? t('transfers.stillIssued') : t('transfers.returned')}</span></td>
              <td>{[transfer.company_unit, transfer.vessel, transfer.location_text].filter(Boolean).join(' · ') || t('common.noValue')}</td>
              <td>{date(transfer.issued_at || transfer.created_at)}{transfer.returned_at && <small>{t('transfers.returnedAt', { date: date(transfer.returned_at) })}</small>}</td>
              <td><button className="link" onClick={() => download(`/transfers/${transfer.id}/docx`, `${transfer.protocol_number}.docx`)}>{t('common.word')}</button> · <button className="link" onClick={() => download(`/transfers/${transfer.id}/pdf`, `${transfer.protocol_number}.pdf`)}>{t('common.pdf')}</button></td>
            </tr>
          ))}</tbody>
        </table>
        {!items.length && <div className="empty-state">{t('transfers.emptyHistory')}</div>}
      </div>
    </>
  )
}
