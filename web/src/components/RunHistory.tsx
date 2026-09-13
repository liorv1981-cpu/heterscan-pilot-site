import { CheckCircle2, CircleAlert, CircleStop, LoaderCircle, SquareArrowOutUpLeft } from 'lucide-react'
import { formatDate, formatDuration } from '../lib/date'
import type { Run } from '../types'

interface RunHistoryProps {
  runs: Run[]
  selectedRunId?: string
  onSelect(run: Run): Promise<void>
}

const activeStatuses = new Set<Run['status']>(['created', 'dispatching', 'running', 'safely_stopped'])
const statusLabels: Record<Run['status'], string> = {
  created: 'נוצרה', dispatching: 'מתחילה', running: 'מתבצעת', safely_stopped: 'ממשיכה במקטע הבא',
  completed: 'הושלמה', completed_with_errors: 'הושלמה עם אזהרות', requires_review: 'נדרשת בדיקה',
  cancelled: 'בוטלה', failed: 'נכשלה', dispatch_failed: 'ההפעלה נכשלה', dispatch_timeout: 'לא התחילה בזמן',
}

export function RunHistory({ runs, selectedRunId, onSelect }: RunHistoryProps) {
  return (
    <section className="history-section" aria-labelledby="history-heading">
      <div className="history-heading"><div><h2 id="history-heading">סריקות קודמות</h2><p>בחרו סריקה כדי להציג את הסטטוס, התוצאות והדוח שנשמרו.</p></div></div>
      <div className="table-shell table-shell--compact">
        <table>
          <thead><tr><th>תאריך ושעה</th><th>עיר</th><th>טווח תאריכים</th><th>סטטוס</th><th>בקשות</th><th>היתרים</th><th>משך זמן</th><th>פעולה</th></tr></thead>
          <tbody>
            {runs.length ? runs.map((run) => {
              const isActive = activeStatuses.has(run.status)
              const Icon = run.status === 'completed' ? CheckCircle2 : isActive ? LoaderCircle : run.status === 'cancelled' ? CircleStop : CircleAlert
              return <tr key={run.id} aria-selected={selectedRunId === run.id}><td>{formatDate(run.createdAt)}</td><td>{run.cityName}</td><td>{formatDate(run.dateFrom)}–{formatDate(run.dateTo)}</td><td><span className={`history-status history-status--${isActive ? 'active' : run.status}`}><Icon className={isActive ? 'spin' : ''} size={16} />{statusLabels[run.status]}</span></td><td>{run.applicationsFound.toLocaleString('he-IL')}</td><td>{run.permitsFound.toLocaleString('he-IL')}</td><td dir="ltr">{formatDuration(run.startedAt, run.completedAt)}</td><td><button className="history-open-button" type="button" onClick={() => void onSelect(run)}><SquareArrowOutUpLeft size={15} /> הצגה</button></td></tr>
            }) : <tr><td colSpan={8} className="empty-cell">טרם בוצעו סריקות.</td></tr>}
          </tbody>
        </table>
      </div>
    </section>
  )
}
