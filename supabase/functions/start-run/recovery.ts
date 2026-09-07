import type { serviceClient } from '../_shared/clients.ts'

interface WorkflowRun { display_title: string; status: string; conclusion: string | null }

export function workflowHasStopped(runs: WorkflowRun[], runId: string): boolean {
  const matches = runs.filter((run) => run.display_title === `HETERSCAN ${runId}`)
  return matches.length > 0 && matches.every((run) => run.status === 'completed' && run.conclusion !== null)
}

// Invoked only by a manual start request. Never resume or dispatch an old scan.
export async function recoverAbandonedRuns(
  db: ReturnType<typeof serviceClient>, repository: string, workflow: string, token: string,
) {
  const cutoff = new Date(Date.now() - 15 * 60 * 1000).toISOString()
  const { data: staleRuns, error } = await db.from('runs')
    .select('id,status,heartbeat_at,lock_expires_at')
    .in('status', ['running', 'safely_stopped'])
    .lt('heartbeat_at', cutoff)
    .or(`lock_expires_at.is.null,lock_expires_at.lt.${cutoff}`)
  if (error) throw error
  if (!staleRuns?.length) return

  const response = await fetch(`https://api.github.com/repos/${repository}/actions/workflows/${workflow}/runs?per_page=100`, {
    headers: { Authorization: `Bearer ${token}`, Accept: 'application/vnd.github+json', 'X-GitHub-Api-Version': '2022-11-28' },
  })
  if (!response.ok) throw new Error('לא ניתן לבדוק אם הסריקה הקודמת הסתיימה. נא לנסות שוב בעוד כמה דקות.')
  const payload = await response.json() as { workflow_runs: WorkflowRun[] }
  for (const run of staleRuns) {
    // Missing history or a queued continuation is not evidence that work stopped.
    if (!workflowHasStopped(payload.workflow_runs, run.id)) continue
    const { error: updateError } = await db.from('runs').update({
      status: 'failed', completed_at: new Date().toISOString(), lock_owner: null, lock_expires_at: null,
      error_message: 'הסריקה הקודמת נקטעה ומנוע הסריקה סיים את פעולתו. התוצאות החלקיות נשמרו; ניתן להפעיל סריקה חדשה.',
    }).eq('id', run.id).eq('status', run.status).eq('heartbeat_at', run.heartbeat_at)
      .or(`lock_expires_at.is.null,lock_expires_at.lt.${cutoff}`)
    if (updateError) throw updateError
  }
}
