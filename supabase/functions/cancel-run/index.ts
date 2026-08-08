import { corsHeaders, errorResponse, json } from '../_shared/http.ts'
import { requireAdmin, serviceClient } from '../_shared/clients.ts'

const activeStatuses = ['created', 'dispatching', 'running', 'safely_stopped']

Deno.serve(async (request) => {
  if (request.method === 'OPTIONS') return new Response('ok', { headers: corsHeaders })
  try {
    const user = await requireAdmin(request)
    const { runId } = await request.json() as { runId?: string }
    if (!runId) throw new Error('חסר מזהה הרצה.')

    const db = serviceClient()
    const { data: existing, error: findError } = await db
      .from('runs')
      .select('id,status,cancel_requested_at')
      .eq('id', runId)
      .eq('requested_by', user.id)
      .single()
    if (findError || !existing) throw new Error('ההרצה לא נמצאה.')

    if (!activeStatuses.includes(existing.status)) {
      throw new Error('לא ניתן לעצור הרצה שכבר הסתיימה.')
    }

    const now = new Date().toISOString()
    const { error: updateError } = await db
      .from('runs')
      .update({
        status: 'cancelled',
        cancel_requested_at: existing.cancel_requested_at ?? now,
        completed_at: now,
        heartbeat_at: now,
        lock_owner: null,
        lock_expires_at: null,
      })
      .eq('id', runId)
      .eq('requested_by', user.id)
      .in('status', activeStatuses)
    if (updateError) throw updateError

    const { data: run, error: readError } = await db
      .from('run_overview')
      .select('*')
      .eq('id', runId)
      .single()
    if (readError || !run) throw new Error('לא ניתן לעדכן את מצב ההרצה.')
    return json({ run })
  } catch (cause) {
    return errorResponse(cause, 400)
  }
})
