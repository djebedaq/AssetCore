import { useState } from 'react'
import { api, ApiError } from '../../api'
import { useI18n, type TranslationKey } from '../../i18n'
import Modal from './CatalogDialog'
import { builderBase } from './wizardTypes'
import { ux04Bg } from './ux04Translations'

type Preview = { digest: string; counts: Record<string, number>; blockers: Array<{ table: string; count: number; record_ids?: number[] }> }
export default function DraftDeleteButton({ kind, identity, onDeleted, label, disabled = false }: {
  kind: string; identity: number; onDeleted: () => Promise<void>; label?: string; disabled?: boolean
}) {
  const { t } = useI18n()
  const [open, setOpen] = useState(false)
  const [preview, setPreview] = useState<Preview | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const path = `${builderBase}/draft-deletion/${kind}/${identity}`
  function report(caught: unknown) {
    setError(t(caught instanceof ApiError && ['catalog_delete_stale', 'catalog_delete_protected_dependency'].includes(caught.code || '') ? 'ux04.deleteStale'
      : caught instanceof ApiError && caught.code === 'catalog_delete_published_protected' ? 'ux04.deleteProtected' : 'guided.error'))
  }
  async function load() {
    setBusy(true); setError(''); setOpen(true); setPreview(null)
    try { setPreview(await api<Preview>(path)) } catch (caught) { report(caught) } finally { setBusy(false) }
  }
  async function remove() {
    if (!preview || busy) return
    setBusy(true); setError('')
    try {
      await api(path, { method: 'POST', body: JSON.stringify({ expected_digest: preview.digest }) })
      setOpen(false); await onDeleted()
    } catch (caught) { report(caught) } finally { setBusy(false) }
  }
  function countName(table: string) {
    const key = `ux04.count.${table}`
    return t(key in ux04Bg ? key as TranslationKey : 'ux04.count.protected')
  }
  return <>
    <button type="button" className="secondary" disabled={disabled || busy} onClick={() => void load()}>{label || t('ux04.delete')}</button>
    {open && <Modal title={t('ux04.deleteTitle')} onClose={() => { if (!busy) setOpen(false) }}>
      <p>{t('ux04.deleteHelp')}</p>
      {error && <p className="error" role="alert">{error}</p>}
      {preview && <><ul>{Object.entries(preview.counts).map(([table, count]) => <li key={table}>{countName(table)}: {count}</li>)}</ul>
        {!!preview.blockers.length && <><h4>{t('ux04.dependencies')}</h4><ul>{preview.blockers.map((item, index) => <li key={index}>{countName(item.table)}: {item.count} {item.record_ids?.map(id => `№${id}`).join(', ')}</li>)}</ul></>}
        <button className="primary" disabled={busy || !!preview.blockers.length} onClick={() => void remove()}>{t('guided.delete')}</button></>}
      {error && <button className="secondary" disabled={busy} onClick={() => void load()}>{t('wizard.retry')}</button>}
    </Modal>}
  </>
}
