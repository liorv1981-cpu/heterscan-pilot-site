import { useEffect, useState, type FormEvent, type ReactNode } from 'react'
import type { Session } from '@supabase/supabase-js'
import { isLocalBackend, supabaseClient } from '../lib/api'

export function AuthGate({ children }: { children: ReactNode }) {
  const [session, setSession] = useState<Session | null>(null)
  const [ready, setReady] = useState(isLocalBackend)
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    if (!supabaseClient) return
    let mounted = true
    supabaseClient.auth.getSession().then(({ data }) => {
      if (mounted) { setSession(data.session); setReady(true) }
    })
    const { data } = supabaseClient.auth.onAuthStateChange((_event, nextSession) => setSession(nextSession))
    return () => { mounted = false; data.subscription.unsubscribe() }
  }, [])

  async function signIn(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setBusy(true)
    setError(null)
    const { error: signInError } = await supabaseClient!.auth.signInWithPassword({ email, password })
    if (signInError) setError('פרטי ההתחברות אינם נכונים או שהחשבון אינו מורשה.')
    setBusy(false)
  }

  if (!ready) return <div className="auth-loading">טוען את סביבת הפיילוט…</div>
  if (isLocalBackend || session) return children
  return (
    <main className="auth-page">
      <section className="auth-panel" aria-labelledby="login-heading">
        <div className="brand auth-brand">HETERSCAN</div>
        <h1 id="login-heading">כניסה לפיילוט</h1>
        <p>הגישה מיועדת למפעיל מורשה בלבד.</p>
        <form onSubmit={signIn}>
          <label><span>דוא״ל</span><input type="email" autoComplete="username" required value={email} onChange={(event) => setEmail(event.target.value)} /></label>
          <label><span>סיסמה</span><input type="password" autoComplete="current-password" required value={password} onChange={(event) => setPassword(event.target.value)} /></label>
          {error ? <p className="form-error" role="alert">{error}</p> : null}
          <button className="primary-button" type="submit" disabled={busy}>{busy ? 'מתחבר…' : 'כניסה'}</button>
        </form>
      </section>
    </main>
  )
}
