import { LogOut, UserRound } from 'lucide-react'
import { supabaseClient } from '../lib/api'

export function AppHeader({ localMode }: { localMode: boolean }) {
  return (
    <header className="app-header">
      <a className="brand" href={import.meta.env.BASE_URL} aria-label="HETERSCAN — דף הבית">HETERSCAN</a>
      <div className="header-actions">
        {localMode ? <span className="dev-mode">מצב פיילוט להדגמה</span> : null}
        <span className="operator"><UserRound size={18} /> מפעיל מורשה</span>
        <button className="quiet-button" type="button" onClick={() => void supabaseClient?.auth.signOut()}><LogOut size={17} /> יציאה</button>
      </div>
    </header>
  )
}
