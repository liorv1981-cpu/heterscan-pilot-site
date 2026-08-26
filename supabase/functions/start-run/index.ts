import { corsHeaders, errorResponse, json } from '../_shared/http.ts'
import { requireAdmin, serviceClient } from '../_shared/clients.ts'

interface StartRunBody { cityId: string; dateFrom: string; dateTo: string }
interface JerusalemStreet { municipal_code: string; municipal_name: string }
interface GitHubRunner {
  status: string
  busy: boolean
  labels: Array<{ name: string }>
}

const localRunnerLabel = 'jerusalem-local'

async function expireAbandonedDispatches(db: ReturnType<typeof serviceClient>) {
  const staleCutoff = new Date(Date.now() - 10 * 60 * 1000).toISOString()
  const now = new Date().toISOString()
  const { error } = await db
    .from('runs')
    .update({
      status: 'dispatch_failed',
      completed_at: now,
      error_message: 'מנוע הסריקה לא התחיל את ההרצה בזמן שהוקצב.',
      lock_owner: null,
      lock_expires_at: null,
    })
    .eq('status', 'dispatching')
    .is('started_at', null)
    .is('heartbeat_at', null)
    .lt('created_at', staleCutoff)
  if (error) throw error
}

async function requireOnlineRunner(repository: string, token: string, runnerLabel: string) {
  if (runnerLabel !== localRunnerLabel) return

  const response = await fetch(`https://api.github.com/repos/${repository}/actions/runners?per_page=100`, {
    headers: {
      Authorization: `Bearer ${token}`,
      Accept: 'application/vnd.github+json',
      'X-GitHub-Api-Version': '2022-11-28',
    },
  })
  if (!response.ok) throw new Error('לא ניתן לבדוק את זמינות מנוע הסריקה כרגע.')

  const payload = await response.json() as { runners?: GitHubRunner[] }
  const runner = (payload.runners ?? []).find((candidate) =>
    candidate.labels.some((label) => label.name === runnerLabel)
  )
  if (!runner || runner.status !== 'online') {
    throw new Error('מנוע הסריקה אינו זמין כרגע. נא לנסות שוב בעוד כמה דקות.')
  }
}

function assertDateRange(body: StartRunBody) {
  const isoDate = /^\d{4}-\d{2}-\d{2}$/
  if (!isoDate.test(body.dateFrom) || !isoDate.test(body.dateTo)) throw new Error('טווח התאריכים אינו תקין.')
  if (body.dateFrom > body.dateTo) throw new Error('תאריך ההתחלה חייב להיות מוקדם מתאריך הסיום.')
  const today = new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Jerusalem' }).format(new Date())
  if (body.dateTo > today) throw new Error('לא ניתן לסרוק תאריכים עתידיים.')
}

Deno.serve(async (request) => {
  let createdRunId: string | undefined
  if (request.method === 'OPTIONS') return new Response('ok', { headers: corsHeaders })
  if (request.method !== 'POST') return json({ error: 'Method not allowed' }, 405)
  try {
    const user = await requireAdmin(request)
    const body = await request.json() as StartRunBody
    assertDateRange(body)
    const db = serviceClient()
    const { data: city, error: cityError } = await db.from('cities').select('*').eq('id', body.cityId).eq('is_active', true).single()
    if (cityError || !city) throw new Error('הרשות שנבחרה אינה פעילה בפיילוט.')

    await expireAbandonedDispatches(db)

    const repository = Deno.env.get('GITHUB_REPOSITORY') ?? 'liorv1981-cpu/heterscan-pilot-site'
    const { data: token, error: tokenError } = await db.rpc('read_app_secret', { p_name: 'github_pat' })
    const workflow = Deno.env.get('GITHUB_WORKFLOW_FILE') ?? 'heter-scan-manual-worker.yml'
    if (tokenError || !token) throw new Error('GitHub Actions טרם הוגדר בסביבת הפיילוט.')
    const runnerLabel = city.adapter_name === 'tel_aviv' ? 'ubuntu-latest' : localRunnerLabel
    await requireOnlineRunner(repository, token, runnerLabel)

    const snapshot = { city, dateFrom: body.dateFrom, dateTo: body.dateTo, createdAt: new Date().toISOString() }
    const { data: run, error: runError } = await db.from('runs').insert({
      city_id: city.id, requested_by: user.id, date_from: body.dateFrom, date_to: body.dateTo,
      configuration_snapshot: snapshot,
    }).select('*, cities!inner(name_he)').single()
    if (runError) {
      if (runError.code === '23505') throw new Error('כבר קיימת סריקה פעילה. יש להמתין לסיומה.')
      throw runError
    }
    createdRunId = run.id

    const streets: Array<{ id: string; street_code: string; official_name: string }> = []
    let jerusalemStreets: JerusalemStreet[] = []
    if (city.adapter_name === 'jerusalem') {
      const pageSize = 1000
      for (let offset = 0; ; offset += pageSize) {
        const { data: page, error: streetsError } = await db.from('municipal_streets')
          .select('municipal_code,municipal_name')
          .eq('city_id', city.id)
          .order('id')
          .range(offset, offset + pageSize - 1)
        if (streetsError) throw streetsError
        jerusalemStreets.push(...((page ?? []) as JerusalemStreet[]))
        if ((page?.length ?? 0) < pageSize) break
      }
    } else if (city.adapter_name !== 'tel_aviv') {
      const pageSize = 1000
      for (let offset = 0; ; offset += pageSize) {
        const { data: page, error: streetsError } = await db.from('official_streets')
          .select('id,street_code,official_name')
          .eq('city_id', city.id)
          .order('id')
          .range(offset, offset + pageSize - 1)
        if (streetsError) throw streetsError
        streets.push(...((page ?? []) as typeof streets))
        if ((page?.length ?? 0) < pageSize) break
      }
    }
    const units = city.adapter_name === 'tel_aviv'
      ? [{ run_id: run.id, sequence: 1, unit_key: 'city-wide', unit_payload: { mode: 'city-wide' } }]
      : city.adapter_name === 'jerusalem'
      ? jerusalemStreets.map((street, index) => ({
          run_id: run.id, sequence: index + 1,
          unit_key: `municipal-street:${street.municipal_code}`,
          unit_payload: { streetCode: street.municipal_code, streetName: street.municipal_name },
        }))
      : (streets ?? []).map((street, index) => ({
          run_id: run.id, sequence: index + 1, official_street_id: street.id,
          unit_key: `street:${street.street_code}`,
          unit_payload: { streetCode: street.street_code, streetName: street.official_name },
        }))
    if (!units.length) {
      await db.from('runs').update({ status: 'failed', error_message: 'לא נמצאו רחובות מיובאים לרשות.' }).eq('id', run.id)
      throw new Error('לא נמצאו רחובות מיובאים לרשות. יש להריץ תחילה את importer.')
    }
    const insertBatchSize = 500
    for (let offset = 0; offset < units.length; offset += insertBatchSize) {
      const { error: unitsError } = await db.from('run_units').insert(units.slice(offset, offset + insertBatchSize))
      if (unitsError) throw unitsError
    }
    await db.from('runs').update({ status: 'dispatching', units_total: units.length }).eq('id', run.id)

    const dispatch = await fetch(`https://api.github.com/repos/${repository}/actions/workflows/${workflow}/dispatches`, {
      method: 'POST',
      headers: { Authorization: `Bearer ${token}`, Accept: 'application/vnd.github+json', 'X-GitHub-Api-Version': '2022-11-28' },
      body: JSON.stringify({
        ref: 'main',
        inputs: {
          run_id: run.id,
          // Complot consistently times out from GitHub-hosted IP ranges, while
          // the trusted local runner reaches the same public source reliably.
          runner_label: runnerLabel,
        },
      }),
    })
    if (!dispatch.ok) {
      const detail = (await dispatch.text()).slice(0, 500)
      await db.from('runs').update({ status: 'dispatch_failed', error_message: `GitHub dispatch ${dispatch.status}: ${detail}` }).eq('id', run.id)
      throw new Error('לא ניתן להפעיל את תהליך הסריקה.')
    }
    return json({ run: { ...run, city_name: run.cities.name_he, status: 'dispatching', units_total: units.length } }, 201)
  } catch (cause) {
    if (createdRunId) {
      await serviceClient().from('runs').update({
        status: 'dispatch_failed',
        error_message: cause instanceof Error ? cause.message.slice(0, 2000) : 'Start run failed',
        completed_at: new Date().toISOString(),
      }).eq('id', createdRunId).in('status', ['created', 'dispatching'])
    }
    return errorResponse(cause, 400)
  }
})
