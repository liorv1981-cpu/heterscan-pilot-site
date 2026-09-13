import { useEffect, useRef, useState } from 'react'
import { History, LoaderCircle } from 'lucide-react'
import { AppHeader } from './components/AppHeader'
import { PermitsTable } from './components/PermitsTable'
import { RunForm } from './components/RunForm'
import { RunHistory } from './components/RunHistory'
import { RunStatusPanel } from './components/RunStatusPanel'
import { api, isLocalBackend } from './lib/api'
import { isActiveRun } from './lib/run'
import type { City, Permit, Run, StartRunInput } from './types'

type Results = { runId: string; rows: Permit[]; error?: string }

export default function App() {
  const [cities, setCities] = useState<City[]>([])
  const [displayedRun, setDisplayedRun] = useState<Run | null>(null)
  const [liveRun, setLiveRun] = useState<Run | null>(null)
  const [results, setResults] = useState<Results | null>(null)
  const [resultsRetry, setResultsRetry] = useState(0)
  const [error, setError] = useState<string | null>(null)
  const [connectionError, setConnectionError] = useState<string | null>(null)
  const [ready, setReady] = useState(false)
  const [isStarting, setIsStarting] = useState(false)
  const [isStopping, setIsStopping] = useState(false)
  const [isDownloading, setIsDownloading] = useState(false)
  const [formResetKey, setFormResetKey] = useState(0)
  const [historyRuns, setHistoryRuns] = useState<Run[]>([])
  const [historyOpen, setHistoryOpen] = useState(false)
  const [historyLoading, setHistoryLoading] = useState(false)
  const startInFlight = useRef(false)
  const stopInFlight = useRef(false)
  const downloadInFlight = useRef(false)
  const operationVersion = useRef(0)
  const liveRunId = liveRun?.id
  const displayedId = displayedRun?.id
  const displayedStatus = displayedRun?.status
  const displayedReport = displayedRun?.reportPath
  const displayedStartedAt = displayedRun?.startedAt

  // Discover work on reload/reconnection, independently of the displayed history.
  useEffect(() => {
    let cancelled = false
    let loading = false
    let timer = 0
    async function refresh() {
      if (loading || cancelled) return
      loading = true
      const version = operationVersion.current
      try {
        const [availableCities, currentRun] = await Promise.all([api.listCities(), api.getActiveRun()])
        if (cancelled) return
        setCities(availableCities)
        setReady(true)
        setConnectionError(null)
        if (version === operationVersion.current && currentRun) {
          setLiveRun(currentRun)
          setDisplayedRun((current) => !current || current.id === currentRun.id ? currentRun : current)
        }
      } catch {
        if (!cancelled) setConnectionError('לא ניתן לעדכן את מצב המערכת כרגע. ננסה שוב אוטומטית.')
      } finally {
        loading = false
        if (!cancelled) {
          window.clearTimeout(timer)
          timer = window.setTimeout(() => void refresh(), 15000)
        }
      }
    }
    const onVisible = () => { if (document.visibilityState === 'visible') void refresh() }
    void refresh()
    document.addEventListener('visibilitychange', onVisible)
    window.addEventListener('online', onVisible)
    return () => {
      cancelled = true
      window.clearTimeout(timer)
      document.removeEventListener('visibilitychange', onVisible)
      window.removeEventListener('online', onVisible)
    }
  }, [])

  useEffect(() => {
    if (!liveRunId) return
    let cancelled = false
    let timer = 0
    async function poll() {
      let finished = false
      const version = operationVersion.current
      try {
        const run = await api.getRun(liveRunId!)
        if (cancelled) return
        if (version !== operationVersion.current) {
          timer = window.setTimeout(() => void poll(), 1500)
          return
        }
        finished = !isActiveRun(run)
        setLiveRun(finished ? null : run)
        setDisplayedRun((current) => current?.id === run.id ? run : current)
        setHistoryRuns((runs) => runs.map((old) => old.id === run.id ? run : old))
        setConnectionError(null)
      } catch {
        if (!cancelled) setConnectionError('לא ניתן לעדכן את מצב ההרצה כרגע. ננסה שוב אוטומטית.')
      }
      if (!cancelled && !finished) timer = window.setTimeout(() => void poll(), 4000)
    }
    timer = window.setTimeout(() => void poll(), 1500)
    return () => { cancelled = true; window.clearTimeout(timer) }
  }, [liveRunId])

  // A separate effect survives status completion and discards stale selections.
  useEffect(() => {
    if (!displayedId || !displayedStatus || isActiveRun({ status: displayedStatus })) return
    let cancelled = false
    void api.listPermits(displayedId).then(
      (rows) => { if (!cancelled) setResults({ runId: displayedId, rows }) },
      () => { if (!cancelled) setResults({ runId: displayedId, rows: [], error: 'לא ניתן לטעון את התוצאות. נסו שוב.' }) },
    )
    return () => { cancelled = true }
  }, [displayedId, displayedStatus, displayedReport, resultsRetry])

  // A stop may finish before the worker uploads its partial report.
  useEffect(() => {
    if (!displayedId || !displayedStatus || isActiveRun({ status: displayedStatus }) || displayedReport || !displayedStartedAt) return
    let cancelled = false
    let timer = 0
    async function refreshReport() {
      let reportReady = false
      try {
        const run = await api.getRun(displayedId!)
        if (cancelled) return
        reportReady = Boolean(run.reportPath)
        setDisplayedRun((current) => current?.id === run.id ? run : current)
      } catch { /* Preserve the visible pending state and retry. */ }
      if (!cancelled && !reportReady) timer = window.setTimeout(() => void refreshReport(), 5000)
    }
    timer = window.setTimeout(() => void refreshReport(), 1500)
    return () => { cancelled = true; window.clearTimeout(timer) }
  }, [displayedId, displayedStatus, displayedReport, displayedStartedAt])

  async function startRun(input: StartRunInput) {
    if (!ready || startInFlight.current || isActiveRun(liveRun) || stopInFlight.current) return
    startInFlight.current = true
    operationVersion.current += 1
    setIsStarting(true)
    setError(null)
    try {
      const run = await api.startRun(input)
      operationVersion.current += 1
      setResults(null)
      setDisplayedRun(run)
      setLiveRun(isActiveRun(run) ? run : null)
      setHistoryOpen(false)
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'לא ניתן להתחיל את הסריקה.')
    } finally {
      startInFlight.current = false
      setIsStarting(false)
    }
  }

  async function toggleHistory() {
    if (historyOpen) return setHistoryOpen(false)
    setHistoryOpen(true)
    setHistoryLoading(true)
    setError(null)
    try { setHistoryRuns(await api.listRuns()) }
    catch { setError('לא ניתן לטעון את הסריקות הקודמות כרגע.') }
    finally { setHistoryLoading(false) }
  }

  async function selectHistoricalRun(run: Run) {
    setError(null)
    setResults(null)
    setDisplayedRun(run)
    if (isActiveRun(run)) setLiveRun(run)
    setResultsRetry((value) => value + 1)
  }

  async function downloadReport() {
    if (!displayedRun?.reportPath || downloadInFlight.current) return
    downloadInFlight.current = true
    setIsDownloading(true)
    setError(null)
    try { await api.downloadReport(displayedRun, results?.runId === displayedRun.id ? results.rows : []) }
    catch { setError('הורדת הדוח נכשלה. נסו שוב בעוד רגע.') }
    finally { downloadInFlight.current = false; setIsDownloading(false) }
  }

  async function stopRun() {
    if (!liveRun || !isActiveRun(liveRun) || stopInFlight.current) return
    stopInFlight.current = true
    operationVersion.current += 1
    setIsStopping(true)
    setError(null)
    try {
      const run = await api.cancelRun(liveRun.id)
      operationVersion.current += 1
      setLiveRun(isActiveRun(run) ? run : null)
      setDisplayedRun((current) => current?.id === run.id ? run : current)
      setResults(null)
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'לא ניתן היה לעצור את הסריקה. נסו שוב.')
    } finally { stopInFlight.current = false; setIsStopping(false) }
  }

  function resetScreen() {
    if (isActiveRun(liveRun) || startInFlight.current || stopInFlight.current) return
    setDisplayedRun(null)
    setResults(null)
    setError(null)
    setFormResetKey((value) => value + 1)
  }

  const finished = Boolean(displayedRun && !isActiveRun(displayedRun))
  const selectedResults = results?.runId === displayedId ? results : null
  const resultsLoading = finished && !selectedResults
  const formDisabled = !ready || isStarting || isStopping || isActiveRun(liveRun)
  return (
    <div className="app-shell">
      <AppHeader localMode={isLocalBackend} />
      <main>
        <section className="intro" aria-labelledby="page-title">
          <div className="title-rule" aria-hidden="true" />
          <div><h1 id="page-title">איתור בקשות והיתרי בנייה</h1><p>בחרו רשות וטווח תאריכים. כל פעולות האיסוף, המיפוי והאימות מתבצעות מאחורי הקלעים.</p></div>
        </section>
        {isLocalBackend ? <p className="local-notice">גרסת פיילוט להדגמה — התוצאות במסך זה מסומנות כנתוני הדגמה ואינן נשמרות.</p> : null}
        {connectionError ? <div className="global-error" role="alert">{connectionError}</div> : null}
        {error ? <div className="global-error" role="alert">{error}<button type="button" onClick={() => setError(null)}>סגירה</button></div> : null}
        {liveRun && liveRun.id !== displayedId ? <div className="live-run-notice" role="status">
          <span>סריקה של {liveRun.cityName} ממשיכה ברקע. ניתן לצפות בסריקות קודמות בזמן ההמתנה.</span>
          <button type="button" className="outline-button" onClick={() => void selectHistoricalRun(liveRun)}>חזרה לסריקה הפעילה</button>
        </div> : null}
        <RunForm key={`${displayedId ?? 'new-run'}-${formResetKey}`} cities={cities} disabled={formDisabled}
          disabledLabel={!ready ? 'בודק את מצב המערכת…' : isStarting ? 'מפעיל סריקה…' : isStopping ? 'מבקש עצירה…' : undefined}
          displayedRun={displayedRun} onSubmit={startRun} onReset={resetScreen} />
        <div className="history-toolbar">
          <button className="history-toggle-button" type="button" aria-expanded={historyOpen} aria-controls="run-history" onClick={() => void toggleHistory()} disabled={historyLoading || isStarting}>
            {historyLoading ? <LoaderCircle className="spin" size={18} /> : <History size={18} />}
            {historyLoading ? 'טוען סריקות…' : historyOpen ? 'סגירת סריקות קודמות' : 'סריקות קודמות'}
          </button>
        </div>
        {historyOpen ? <div id="run-history"><RunHistory runs={historyRuns} selectedRunId={displayedId} onSelect={selectHistoricalRun} /></div> : null}
        {displayedRun ? <RunStatusPanel run={displayedRun} isStopping={isStopping} onStop={stopRun} /> : <section className="status-placeholder"><h2>סטטוס ההרצה</h2><p>לאחר הפעלת הסריקה יוצגו כאן ההתקדמות והתוצאות.</p></section>}
        <PermitsTable run={displayedRun} permits={selectedResults?.rows ?? []} loading={resultsLoading}
          error={selectedResults?.error} downloading={isDownloading} onRetry={() => { setResults(null); setResultsRetry((value) => value + 1) }} onDownload={downloadReport} />
      </main>
    </div>
  )
}
