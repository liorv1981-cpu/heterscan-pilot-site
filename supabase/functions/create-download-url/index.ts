import { corsHeaders, errorResponse, json } from '../_shared/http.ts'
import { requireAdmin, serviceClient } from '../_shared/clients.ts'
import { reportDownloadFilename } from '../_shared/report_filename.ts'

Deno.serve(async (request) => {
  if (request.method === 'OPTIONS') return new Response('ok', { headers: corsHeaders })
  try {
    const user = await requireAdmin(request)
    const { runId } = await request.json() as { runId?: string }
    if (!runId) throw new Error('חסר מזהה הרצה.')
    const db = serviceClient()
    const { data: run } = await db.from('runs')
      .select('id,requested_by,status,configuration_snapshot,date_from,date_to')
      .eq('id', runId).eq('requested_by', user.id).single()
    if (!run || !['completed', 'completed_with_errors', 'requires_review', 'cancelled', 'failed'].includes(run.status)) {
      throw new Error('הדוח עדיין אינו זמין.')
    }
    const { data: report, error } = await db.from('reports').select('storage_path,created_at').eq('run_id', runId).single()
    if (error || !report) throw new Error('קובץ הדוח לא נמצא.')
    const filename = reportDownloadFilename({ id: run.id,
      cityName: run.configuration_snapshot?.city?.name_he ?? '',
      dateFrom: run.date_from, dateTo: run.date_to }, report.created_at)
    const { data, error: signError } = await db.storage.from('reports').createSignedUrl(report.storage_path, 60)
    if (signError || !data) throw signError ?? new Error('לא ניתן ליצור קישור לדוח.')
    const url = new URL(data.signedUrl)
    url.searchParams.set('download', filename)
    return json({ url: url.toString(), expiresIn: 60 })
  } catch (cause) { return errorResponse(cause, 400) }
})
