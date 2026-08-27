import { useEffect, useState } from 'react'
import { api } from '../../api'
import AuthenticatedImage from '../../AuthenticatedImage'
import { useI18n } from '../../i18n'
import type { Machine } from '../../types'

export default function QrCodes() {
  const { t } = useI18n()
  const [machines, setMachines] = useState<Machine[]>([])
  useEffect(() => { void api<Machine[]>('/machines').then(setMachines).catch(() => undefined) }, [])
  return (<>
    <div className="toolbar qr-toolbar"><div><h3>{t('nav.qr')}</h3></div><button className="primary" onClick={() => window.print()}>{t('qr.printLabels')}</button></div>
    <div className="qr-grid printable-qr-labels">
      {machines.map((machine) => (
        <div className="qr-card" key={machine.id}>
          <AuthenticatedImage src={`/machines/${machine.id}/qr`} alt={t('qr.alt', { number: machine.inventory_number })} />
          <strong>{machine.name}</strong><span>{machine.brand} · {machine.pressure_bar} bar</span>
        </div>
      ))}
      {!machines.length && <div className="empty-state">{t('qr.empty')}</div>}
    </div>
  </>)
}
