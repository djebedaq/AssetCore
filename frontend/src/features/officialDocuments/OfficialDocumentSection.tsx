import { FileText } from 'lucide-react'
import { DocumentButtons } from '../../industrialUi'
import { statusText, useI18n, type TranslationKey } from '../../i18n'
import type { OfficialRegistryDocument, OfficialRegistryItem, OfficialRegistrySection as RegistrySection } from './types'

const TRANSFER_DOCUMENT_ORDER: Record<string, number> = {
  TRANSFER_ISSUE: 0,
  TRANSFER_RETURN: 1,
}

type Props = {
  section: RegistrySection
  titleKey: TranslationKey
  emptyKey: TranslationKey
  typeKey: TranslationKey
  statusDomain: 'transfer' | 'repair' | 'part'
}

export default function OfficialDocumentSection({ section, titleKey, emptyKey, typeKey, statusDomain }: Props) {
  const { date, t } = useI18n()
  return (
    <section className="official-registry-section" aria-labelledby={`official-section-${statusDomain}`}>
      <header className="official-registry-heading">
        <div>
          <FileText size={20} aria-hidden="true" />
          <h4 id={`official-section-${statusDomain}`}>{t(titleKey)}</h4>
        </div>
        <span className="badge official-count" aria-label={t('official.sectionCount', { count: section.count })}>{section.count}</span>
      </header>
      {statusDomain === 'transfer' ? <TransferRegistry section={section} /> : <div className="table-card official-registry-table">
        <table>
          <thead><tr><th>{t('official.number')}</th><th>{t('official.type')}</th><th>{t('common.status')}</th><th>{t('official.progress')}</th><th>{t('official.created')}</th><th>{t('transfers.documents')}</th></tr></thead>
          <tbody>{section.items.map((item) => (
            <OfficialDocumentRow key={item.registry_key} item={item} typeKey={typeKey} statusDomain={statusDomain} />
          ))}</tbody>
        </table>
        {!section.items.length && <div className="empty-state">{t(emptyKey)}</div>}
      </div>}
    </section>
  )

  function TransferRegistry({ section: transferSection }: { section: RegistrySection }) {
    return (
      <div className="table-card official-transfer-registry">
        <div className="official-transfer-list" role="list">
          {transferSection.items.map((item) => <TransferRegistryItem key={item.registry_key} item={item} />)}
        </div>
        {!transferSection.items.length && <div className="empty-state">{t(emptyKey)}</div>}
      </div>
    )
  }

  function TransferRegistryItem({ item }: { item: OfficialRegistryItem }) {
    const created = item.created_at ? date(item.created_at) : t('common.noValue')
    const orderedDocuments = item.documents
      .map((document, index) => ({ document, index }))
      .sort((left, right) => (
        (TRANSFER_DOCUMENT_ORDER[left.document.document_type] ?? 2)
        - (TRANSFER_DOCUMENT_ORDER[right.document.document_type] ?? 2)
        || left.index - right.index
      ))
      .map(({ document }) => document)

    return (
      <article className="official-transfer-item" role="listitem" data-registry-key={item.registry_key}>
        <div className="official-transfer-info">
          <h5>{item.machine_number ? t('official.machineNumber', { number: item.machine_number }) : t(typeKey)}</h5>
          <dl className="official-transfer-metadata">
            <div><dt>{t('common.status')}</dt><dd><span className={`badge official-status ${item.status.toLowerCase()}`}>{registryStatus(item.status, 'transfer')}</span></dd></div>
            <div><dt>{t('official.progress')}</dt><dd><span className={`official-signature ${item.signature_status.toLowerCase()}`}>{signatureLabel(item.signature_status)}</span></dd></div>
            <div><dt>{t('official.created')}</dt><dd>{created}{!item.created_at && item.started_at && <small>{t('official.startedAt', { date: date(item.started_at) })}</small>}</dd></div>
          </dl>
        </div>
        <div className="official-transfer-protocols" aria-label={t('transfers.documents')}>
          {orderedDocuments.map((document) => (
            <DocumentAction
              key={`${item.registry_key}-${document.document_type}-${document.document_number}`}
              document={document}
              transferLayout
            />
          ))}
        </div>
      </article>
    )
  }

  function OfficialDocumentRow({ item, typeKey: rowTypeKey, statusDomain: rowStatusDomain }: { item: OfficialRegistryItem; typeKey: TranslationKey; statusDomain: Props['statusDomain'] }) {
    const created = item.created_at ? date(item.created_at) : t('common.noValue')
    return (
      <tr>
        <td data-label={t('official.number')}>
          {item.documents.map((document) => <span className="official-number" key={`${item.registry_key}-${document.document_type}-${document.document_number}`}><strong>{document.document_number}</strong>{item.documents.length > 1 && <small>{documentLabel(document)}</small>}</span>)}
          {item.machine_number && <small>{t('official.machineNumber', { number: item.machine_number })}</small>}
        </td>
        <td data-label={t('official.type')}>{t(rowTypeKey)}</td>
        <td data-label={t('common.status')}><span className={`badge official-status ${item.status.toLowerCase()}`}>{registryStatus(item.status, rowStatusDomain)}</span></td>
        <td data-label={t('official.progress')}><span className={`official-signature ${item.signature_status.toLowerCase()}`}>{signatureLabel(item.signature_status)}</span></td>
        <td data-label={t('official.created')}>{created}{!item.created_at && item.started_at && <small>{t('official.startedAt', { date: date(item.started_at) })}</small>}</td>
        <td data-label={t('transfers.documents')}><div className="official-document-actions">{item.documents.map((document) => <DocumentAction key={`${item.registry_key}-${document.document_type}-${document.document_number}`} document={document} />)}</div></td>
      </tr>
    )
  }

  function DocumentAction({ document, transferLayout = false }: { document: OfficialRegistryDocument; transferLayout?: boolean }) {
    const safeNumber = document.document_number.replace(/[^A-Za-z0-9._-]/g, '_')
    return (
      <div className={`official-document-action${transferLayout ? ' official-transfer-protocol' : ''}`} data-document-type={document.document_type}>
        <span>{documentLabel(document)}</span>
        {transferLayout && <strong className="official-transfer-protocol-number">{document.document_number}</strong>}
        <div>{document.files.map((file) => <DocumentButtons key={`${document.document_number}-${file.format}`} path={file.preview_endpoint || file.download_endpoint} filename={`${safeNumber}${document.version ? `-v${document.version}` : ''}.${file.format}`} format={file.format} label={transferLayout ? file.format.toUpperCase() : file.format === 'docx' ? t('common.word') : t('common.pdf')} />)}{!document.files.length && <span className="muted">{t('common.noValue')}</span>}</div>
      </div>
    )
  }

  function documentLabel(document: OfficialRegistryDocument): string {
    const key = ({
      TRANSFER_ISSUE: 'official.issueProtocol',
      TRANSFER_RETURN: 'official.returnProtocol',
      REPAIR_PROTOCOL: 'official.repairProtocol',
      PART_REQUEST: 'official.partRequestProtocol',
    } as Record<string, TranslationKey>)[document.document_type] || 'documentType.other'
    return t(key)
  }

  function registryStatus(value: string, domain: Props['statusDomain']): string {
    if (value === 'COMPLETE') return t('official.lifecycleComplete')
    if (value === 'INCOMPLETE') return t('official.lifecycleIncomplete')
    if (domain === 'repair') return statusText(t, value, 'repair')
    if (domain === 'part') return statusText(t, value, 'part')
    return value
  }

  function signatureLabel(value: OfficialRegistryItem['signature_status']): string {
    return t(({
      SIGNED: 'official.signatureSigned',
      PARTIALLY_SIGNED: 'official.signaturePartial',
      UNSIGNED: 'official.signatureUnsigned',
      NOT_REQUIRED: 'official.signatureNotRequired',
      UNKNOWN: 'official.signatureUnknown',
    } as const)[value])
  }
}
