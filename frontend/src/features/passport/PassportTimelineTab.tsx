import { ArrowLeft, ArrowRight, Boxes, FileText, History, Truck, Wrench } from 'lucide-react'

import { translatedEventCode } from '../../industrialUi'
import { useI18n } from '../../i18n'
import type { TimelineCategory } from '../../types'
import { CATEGORY_KEYS, TIMELINE_CATEGORIES, timelineDetails, timelineSource, timelineStatus } from './timelinePresentation'
import type { usePassportTimeline } from './usePassportTimeline'

const ICONS = { all: History, asset: Boxes, transfer: Truck, repair: Wrench, parts: Boxes, document: FileText }

export function PassportTimelineTab({ timeline }: { timeline: ReturnType<typeof usePassportTimeline> }) {
  const { t, date, number } = useI18n()
  const { category, data, error, loading, selectCategory, selectPage, retry } = timeline
  return <section className="passport-timeline" aria-label={t('timeline.title')}>
    <div className="passport-timeline-heading"><h3>{t('timeline.title')}</h3></div>
    <div className="passport-timeline-filters" role="group" aria-label={t('timeline.filters')}>
      {TIMELINE_CATEGORIES.map((value) => <button key={value} type="button" aria-pressed={category === value} onClick={() => selectCategory(value)}>
        {t(CATEGORY_KEYS[value])}
      </button>)}
    </div>
    {loading && <div className="loading" role="status">{t('timeline.loading')}</div>}
    {error && <div className="error passport-timeline-error" role="alert"><span>{t('timeline.error')}</span>
      <button type="button" className="secondary" onClick={retry}>{t('official.retry')}</button>
    </div>}
    {data && !loading && !error && (data.limited_view ? <p className="empty-state">{t('passport.limitedView')}</p> : <>
      <p className="passport-timeline-count" role="status">{t('timeline.count', { count: data.count, total: data.total })}</p>
      {!data.items.length && <p className="empty-state">{t(data.total === 0 ? (category === 'all' ? 'timeline.emptyAll' : 'timeline.emptyCategory') : 'timeline.emptyPage')}</p>}
      <ol className="passport-timeline-list">
        {data.items.map((item) => {
          const Icon = ICONS[item.category] || History
          const detailRows = timelineDetails(t, number, item)
          return <li key={item.event_key} data-event-key={item.event_key}>
            <time dateTime={item.occurred_at}>{date(item.occurred_at)}</time>
            <article className="passport-timeline-event">
              <div className="passport-timeline-category"><Icon size={17} aria-hidden="true" />
                <span>{t(CATEGORY_KEYS[item.category as TimelineCategory] || 'event.other')}</span>
              </div>
              <h4>{translatedEventCode(t, item.event_type)}</h4>
              {item.reference && <strong className="passport-timeline-reference">{item.reference}</strong>}
              {(item.status_before || item.status_after) && <dl className="passport-timeline-status">
                {item.status_before && <div><dt>{t('timeline.before')}</dt><dd>{timelineStatus(t, item, item.status_before)}</dd></div>}
                {item.status_after && <div><dt>{t('timeline.after')}</dt><dd>{timelineStatus(t, item, item.status_after)}</dd></div>}
              </dl>}
              {item.description && <p className="passport-timeline-description">{item.description}</p>}
              {detailRows.length > 0 && <dl className="passport-timeline-details">{detailRows.map(({ field, label, text }) => <div key={field}><dt>{label}</dt><dd>{text}</dd></div>)}</dl>}
              <small className="passport-timeline-source">{t('catalog.source')}: {timelineSource(t, item.source_type)}</small>
            </article>
          </li>
        })}
      </ol>
      <nav className="passport-timeline-pagination" aria-label={t('timeline.title')}>
        <button type="button" className="secondary" disabled={!data.has_previous} onClick={() => selectPage(Math.max(1, data.page - 1))}>
          <ArrowLeft size={16} aria-hidden="true" />{t('timeline.previous')}
        </button>
        <span>{data.total_pages > 0 && t(data.page > data.total_pages ? 'timeline.outOfRange' : 'timeline.page', { page: data.page, pages: data.total_pages })}</span>
        <button type="button" className="secondary" disabled={!data.has_next} onClick={() => selectPage(data.page + 1)}>
          {t('timeline.next')}<ArrowRight size={16} aria-hidden="true" />
        </button>
      </nav>
    </>)}
  </section>
}
