import { ArrowDownToLine, ExternalLink } from 'lucide-react'
import { formatDate } from '../lib/date'
import { getMunicipalSourceLink } from '../lib/municipalSource'
import type { Permit, Run } from '../types'

interface PermitsTableProps {
  run: Run | null
  permits: Permit[]
  loading?: boolean
  error?: string
  downloading?: boolean
  onRetry?(): void
  onDownload(): Promise<void>
}

export function PermitsTable({ run, permits, loading = false, error, downloading = false, onRetry, onDownload }: PermitsTableProps) {
  const hasFinished = Boolean(run && ['completed', 'completed_with_errors', 'requires_review', 'cancelled', 'failed', 'dispatch_failed', 'dispatch_timeout'].includes(run.status))
  const reportReady = Boolean(hasFinished && run?.reportPath)
  const isPartial = Boolean(run && ['cancelled', 'failed', 'dispatch_failed', 'dispatch_timeout', 'requires_review', 'completed_with_errors'].includes(run.status))
  const issuedCount = permits.filter((result) => result.isPermitIssued).length
  const hideEmptyTable = isPartial && permits.length === 0
  const emptyMessage = run?.status === 'completed'
    ? 'לא נמצאו בקשות או היתרים בטווח שנבחר.'
    : run?.status === 'cancelled' ? 'עד לעצירת הסריקה לא נמצאו בקשות או היתרים.'
      : 'לא נמצאו תוצאות בחלק שנבדק. יש לעיין בסטטוס ובדוח לפני הסקת מסקנות.'
  return (
    <section className="results-section" aria-labelledby="results-heading" aria-busy={loading}>
      <div className="section-heading-row">
        <div><h2 id="results-heading">בקשות והיתרים שנמצאו</h2><p>{loading ? 'טוען תוצאות…' : error ? 'טעינת התוצאות לא הושלמה.' : hasFinished ? `${permits.length} בקשות, מתוכן ${issuedCount} היתרים שהופקו${isPartial ? ' — תוצאות חלקיות; יש לעיין בסטטוס ובדוח' : ''}` : 'התוצאות יוצגו כאן בסיום הסריקה'}</p></div>
        <button className="outline-button" type="button" disabled={!reportReady || downloading} onClick={() => void onDownload()}>
          <ArrowDownToLine size={18} /> {downloading ? 'מכין הורדה…' : isPartial ? 'הורדת Excel חלקי' : 'הורדת Excel'}
        </button>
      </div>
      {hasFinished && !reportReady ? <p className="report-note">הדוח עדיין אינו זמין. כפתור ההורדה יופעל כשהקובץ יהיה מוכן.</p> : null}
      {loading ? <p role="status">טוען את הבקשות וההיתרים של הסריקה שנבחרה…</p> : error ? <div className="global-error" role="alert">{error}<button type="button" onClick={onRetry}>ניסיון נוסף</button></div> : hideEmptyTable ? <p>{emptyMessage}</p> : <div className="table-shell" role="region" aria-label="טבלת תוצאות — ניתנת לגלילה" tabIndex={0}>
        <table>
          <thead><tr><th>עיר</th><th>כתובת</th><th>מספר בקשה</th><th>תאריך בקשה</th><th>מספר היתר</th><th>תאריך היתר</th><th>סטטוס</th><th>מקור</th></tr></thead>
          <tbody>
            {permits.length ? permits.map((permit) => {
              const sourceLink = getMunicipalSourceLink(permit)
              return (
                <tr key={permit.id}>
                  <td>{permit.cityName}</td><td>{permit.address}</td><td dir="ltr">{permit.applicationNumber}</td><td>{formatDate(permit.submissionDate)}</td>
                  <td dir="ltr">{permit.permitNumber}</td><td>{formatDate(permit.permitIssueDate)}</td><td>{permit.statusOriginal}</td>
                  <td><a href={sourceLink.href} target="_blank" rel="noreferrer" aria-label={`פתיחת מקור עבור בקשה ${permit.applicationNumber}`}><ExternalLink size={17} /> {sourceLink.label}</a></td>
                </tr>
              )
            }) : (
              <tr><td colSpan={8} className="empty-cell">{hasFinished ? emptyMessage : 'עדיין אין תוצאות להצגה.'}</td></tr>
            )}
          </tbody>
        </table>
      </div>}
    </section>
  )
}
