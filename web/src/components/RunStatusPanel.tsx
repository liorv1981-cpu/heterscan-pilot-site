import { useState } from 'react'
import { CheckCircle2, CircleAlert, CircleStop, LoaderCircle } from 'lucide-react'
import { formatDate, formatDuration } from '../lib/date'
import type { Run } from '../types'

const statusCopy: Record<Run['status'], string> = {
  created: 'ההרצה נוצרה', dispatching: 'מפעיל את הסריקה', running: 'הסריקה מתבצעת', safely_stopped: 'הסריקה ממשיכה במקטע הבא',
  completed: 'הסריקה הושלמה', completed_with_errors: 'הסריקה הושלמה עם אזהרות',
  requires_review: 'נדרשת בדיקה', failed: 'הסריקה נכשלה', dispatch_failed: 'הפעלת הסריקה נכשלה',
  dispatch_timeout: 'הפעלת הסריקה לא החלה בזמן', cancelled: 'הסריקה בוטלה',
}

interface RunStatusPanelProps {
  run: Run
  isStopping: boolean
  onStop(): Promise<void>
}

const activeStatuses = new Set<Run['status']>(['created', 'dispatching', 'running', 'safely_stopped'])

export function RunStatusPanel({ run, isStopping, onStop }: RunStatusPanelProps) {
  const [confirmationFor, setConfirmationFor] = useState<string | null>(null)
  const isDone = run.status === 'completed'
  const isFinished = ['completed', 'completed_with_errors', 'requires_review'].includes(run.status)
  const isActive = activeStatuses.has(run.status)
  const stopRequested = isActive && Boolean(run.cancelRequestedAt)
  const confirming = confirmationFor === run.id
  const hasIssue = ['completed_with_errors', 'requires_review', 'failed', 'dispatch_failed', 'dispatch_timeout', 'cancelled'].includes(run.status)
  const completedUnits = isFinished ? run.unitsTotal : run.unitsCompleted
  const progress = isFinished ? 100 : run.unitsTotal ? Math.round((run.unitsCompleted / run.unitsTotal) * 100) : 0
  const Icon = isDone ? CheckCircle2 : hasIssue ? CircleAlert : stopRequested ? CircleStop : LoaderCircle

  return (
    <section className={`status-panel ${hasIssue ? 'status-panel--warning' : ''}`} aria-labelledby="run-status-heading">
      <div className="status-main">
        <h2 id="run-status-heading">סטטוס ההרצה</h2>
        <p className={isDone ? 'status-success' : hasIssue ? 'status-warning' : 'status-running'}>
          <Icon size={20} className={!isDone && !hasIssue && !stopRequested ? 'spin' : ''} /> {stopRequested ? 'בקשת העצירה התקבלה' : statusCopy[run.status]}
        </p>
      </div>
      <dl className="status-metrics">
        <div><dt>יחידות שנבדקו</dt><dd>
          <span dir="rtl" style={{ display: 'inline-flex', gap: '0.3em' }} aria-label={`${completedUnits.toLocaleString('he-IL')} מתוך ${run.unitsTotal.toLocaleString('he-IL')} יחידות חיפוש`}>
            <bdi dir="ltr">{completedUnits.toLocaleString('he-IL')}</bdi>
            <span aria-hidden="true">/</span>
            <bdi dir="ltr">{run.unitsTotal.toLocaleString('he-IL')}</bdi>
          </span>
        </dd></div>
        <div><dt>נמצאו בקשות</dt><dd>{run.applicationsFound.toLocaleString('he-IL')}</dd></div>
        <div><dt>נמצאו היתרים</dt><dd>{run.permitsFound.toLocaleString('he-IL')}</dd></div>
        <div><dt>זמן התחלה</dt><dd>{formatDate(run.startedAt)}</dd></div>
        <div><dt>משך זמן</dt><dd dir="ltr">{formatDuration(run.startedAt, run.completedAt)}</dd></div>
      </dl>
      <div className="progress-row">
        <div className="progress-track" aria-label={`התקדמות ${progress}%`} role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={progress}>
          <span style={{ width: `${Math.min(100, progress)}%` }} />
        </div>
        <strong>{progress}%</strong>
      </div>
      {isActive ? (
        <div className="stop-controls" aria-live="polite">
          {stopRequested ? (
            <p className="stop-requested"><CircleStop size={18} /> מסיים את מקטע העבודה הנוכחי ושומר דוח חלקי. אפשר לצאת מהדף ולחזור בהמשך.</p>
          ) : confirming ? (
            <div className="stop-confirmation" role="group" aria-label="אישור עצירת הסריקה">
              <p>לאחר אישור העצירה בשרת ניתן יהיה להתחיל סריקה חדשה. התוצאות שכבר נמצאו יישמרו בדוח חלקי.</p>
              <div>
                <button className="stop-confirm-button" type="button" disabled={isStopping} onClick={() => void onStop()}>
                  {isStopping ? 'מבקש עצירה…' : 'כן, עצור את הסריקה'}
                </button>
                <button className="stop-back-button" type="button" disabled={isStopping} onClick={() => setConfirmationFor(null)}>חזרה</button>
              </div>
            </div>
          ) : (
            <button className="stop-button" type="button" onClick={() => setConfirmationFor(run.id)}><CircleStop size={18} /> עצירת הסריקה</button>
          )}
        </div>
      ) : null}
      {isDone && run.applicationsFound === 0 ? <p className="status-note">הסריקה הסתיימה בהצלחה, אך לא נמצאו בקשות או היתרים בטווח התאריכים שנבחר.</p> : null}
      {['requires_review', 'completed_with_errors'].includes(run.status) ? <p className="status-note">חלק מבדיקות המקור לא הושלמו בהצלחה. {run.applicationsFound === 0 ? 'לא נמצאו תוצאות בחלק שנבדק; אין בכך אישור שאין בקשות בטווח.' : 'התוצאות שנאספו זמינות למטה.'} פרטי הבדיקות מופיעים בדוח.</p> : null}
      {run.status === 'cancelled' ? <p className="status-note">הסריקה נעצרה מיד וניתן להתחיל סריקה חדשה. {run.applicationsFound > 0 ? 'התוצאות שנמצאו עד העצירה מוצגות למטה' : 'עד העצירה לא נמצאו תוצאות'}{run.reportPath ? ', והדוח החלקי מוכן להורדה.' : '; הדוח החלקי מושלם ברקע.'}</p> : null}
      {run.errorMessage ? <p className="status-error" role="alert">{run.errorMessage}</p> : null}
    </section>
  )
}
