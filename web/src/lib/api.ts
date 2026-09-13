import { createClient, type SupabaseClient } from '@supabase/supabase-js'
import type { City, Permit, PilotApi, Run, StartRunInput } from '../types'
import { functionError } from './functionError'
import { activeStatuses, isActiveRun } from './run'
import { readAllPages } from './pagination'

const citySeed: City[] = [
  { id: '3000', name: 'ירושלים' },
  { id: '5000', name: 'תל אביב-יפו' },
  { id: '4000', name: 'חיפה' },
  { id: '7900', name: 'פתח תקווה' },
  { id: '8300', name: 'ראשון לציון' },
]

const demoPermits: Omit<Permit, 'runId'>[] = [
  {
    id: 'demo-1', cityName: 'פתח תקווה', address: 'רוטשילד 9', applicationNumber: '2024-003210',
    submissionDate: '2024-04-01', permitNumber: '2024-04888', permitIssueDate: '2024-04-07', statusOriginal: 'היתר בתוקף',
    sourceUrl: 'https://handasi.complot.co.il/', confidence: 'high', isPermitIssued: true, isApproved: true,
  },
  {
    id: 'demo-2', cityName: 'פתח תקווה', address: 'העצמאות 101', applicationNumber: '2024-004321',
    submissionDate: '2024-04-02', permitNumber: '2024-05102', permitIssueDate: '2024-04-11', statusOriginal: 'היתר בתוקף',
    sourceUrl: 'https://handasi.complot.co.il/', confidence: 'high', isPermitIssued: true, isApproved: true,
  },
  {
    id: 'demo-3', cityName: 'פתח תקווה', address: 'דרך זאב ליפקיס 3', applicationNumber: '2024-005432',
    submissionDate: '2024-04-03', permitNumber: '2024-05321', permitIssueDate: '2024-04-15', statusOriginal: 'היתר בתוקף',
    sourceUrl: 'https://handasi.complot.co.il/', confidence: 'high', isPermitIssued: true, isApproved: true,
  },
  {
    id: 'demo-4', cityName: 'פתח תקווה', address: 'חיים עוזר 12', applicationNumber: '2024-006543',
    submissionDate: '2024-04-04', permitNumber: 'טרם הופק', statusOriginal: 'טרם אושר', sourceUrl: 'https://handasi.complot.co.il/',
    isPermitIssued: false, isApproved: false,
  },
]

const demoRuns = new Map<string, Run>()

function createLocalApi(): PilotApi {
  return {
    async listCities() { return citySeed },
    async getActiveRun() { return [...demoRuns.values()].find(isActiveRun) ?? null },
    async listRuns() { return [...demoRuns.values()].sort((a, b) => b.createdAt.localeCompare(a.createdAt)) },
    async startRun(input: StartRunInput) {
      if ([...demoRuns.values()].some(isActiveRun)) throw new Error('כבר קיימת סריקה פעילה.')
      const city = citySeed.find((item) => item.id === input.cityId)
      if (!city) throw new Error('הרשות שנבחרה אינה זמינה בפיילוט.')
      const id = crypto.randomUUID()
      const now = new Date().toISOString()
      const run: Run = {
        id, cityId: city.id, cityName: city.name, dateFrom: input.dateFrom, dateTo: input.dateTo,
        status: 'running', createdAt: now, startedAt: now, unitsTotal: 100, unitsCompleted: 18,
        permitsFound: 0, applicationsFound: 0,
      }
      demoRuns.set(id, run)
      return run
    },
    async cancelRun(runId: string) {
      const run = demoRuns.get(runId)
      if (!run) throw new Error('ההרצה לא נמצאה.')
      if (!['created', 'dispatching', 'running', 'safely_stopped'].includes(run.status)) {
        throw new Error('לא ניתן לעצור הרצה שכבר הסתיימה.')
      }
      const now = new Date().toISOString()
      run.cancelRequestedAt ??= now
      run.status = 'cancelled'
      run.completedAt = now
      run.reportPath = `local/${runId}.xlsx`
      return { ...run }
    },
    async getRun(runId: string) {
      const run = demoRuns.get(runId)
      if (!run) throw new Error('ההרצה לא נמצאה.')
      const elapsed = Date.now() - new Date(run.startedAt ?? run.createdAt).getTime()
      if (run.cancelRequestedAt && run.status === 'running') {
        Object.assign(run, {
          status: 'cancelled', completedAt: new Date().toISOString(), reportPath: `local/${runId}.xlsx`,
        } satisfies Partial<Run>)
      } else if (elapsed > 2600 && run.status === 'running') {
        Object.assign(run, {
          status: 'completed', completedAt: new Date().toISOString(), unitsCompleted: 100,
          permitsFound: demoPermits.filter((result) => result.isPermitIssued).length,
          applicationsFound: demoPermits.length, reportPath: `local/${runId}.xlsx`,
        } satisfies Partial<Run>)
      } else if (run.status === 'running') {
        run.unitsCompleted = Math.min(92, run.unitsCompleted + 22)
      }
      return { ...run }
    },
    async listPermits(runId: string) {
      const run = demoRuns.get(runId)
      return run?.status === 'completed'
        ? demoPermits.filter((permit) => permit.submissionDate && permit.submissionDate >= run.dateFrom && permit.submissionDate <= run.dateTo)
          .map((permit) => ({ ...permit, runId }))
        : []
    },
    async downloadReport(run) {
      const link = document.createElement('a')
      link.href = `${import.meta.env.BASE_URL}HETERSCAN_DEMO_RESULTS.xlsx`
      link.download = `HETERSCAN_DEMO_${run.cityName}_${run.dateFrom}_${run.dateTo}.xlsx`
      document.body.append(link)
      link.click()
      link.remove()
    },
  }
}

function mapRun(row: Record<string, unknown>): Run {
  return {
    id: String(row.id), cityId: String(row.city_id), cityName: String(row.city_name ?? ''),
    dateFrom: String(row.date_from), dateTo: String(row.date_to), status: row.status as Run['status'],
    createdAt: String(row.created_at), startedAt: row.started_at ? String(row.started_at) : undefined,
    completedAt: row.completed_at ? String(row.completed_at) : undefined,
    cancelRequestedAt: row.cancel_requested_at ? String(row.cancel_requested_at) : undefined,
    unitsTotal: Number(row.units_total ?? 0), unitsCompleted: Number(row.units_completed ?? 0),
    permitsFound: Number(row.permits_found ?? 0), applicationsFound: Number(row.applications_found ?? 0),
    reportPath: row.report_path ? String(row.report_path) : undefined,
    errorMessage: row.error_message ? String(row.error_message) : undefined,
  }
}

function createSupabaseApi(client: SupabaseClient): PilotApi {
  return {
    async listCities() {
      const { data, error } = await client.from('cities').select('id,name_he').eq('is_active', true).order('display_order')
      if (error) throw error
      const rows = (data ?? []) as unknown as Array<{ id: string; name_he: string }>
      return rows.map((row) => ({ id: String(row.id), name: row.name_he }))
    },
    async listRuns() {
      const rows = await readAllPages<Record<string, unknown>>(async (from, to) => {
        const { data, error } = await client.from('run_overview').select('*')
          .order('created_at', { ascending: false }).order('id').range(from, to)
        if (error) throw error
        return (data ?? []) as Array<Record<string, unknown>>
      })
      return rows.map(mapRun)
    },
    async getActiveRun() {
      const { data, error } = await client.from('run_overview').select('*').in('status', activeStatuses)
        .order('created_at', { ascending: false }).limit(1).maybeSingle()
      if (error) throw error
      return data ? mapRun(data as Record<string, unknown>) : null
    },
    async startRun(input) {
      const { data, error } = await client.functions.invoke('start-run', { body: input })
      if (error) throw await functionError(error)
      return mapRun(data.run)
    },
    async cancelRun(runId) {
      const { data, error } = await client.functions.invoke('cancel-run', { body: { runId } })
      if (error) throw await functionError(error)
      return mapRun(data.run)
    },
    async getRun(runId) {
      const { data, error } = await client.from('run_overview').select('*').eq('id', runId).single()
      if (error) throw error
      return mapRun(data as Record<string, unknown>)
    },
    async listPermits(runId) {
      const rows = await readAllPages<Record<string, unknown>>(async (from, to) => {
        const { data, error } = await client.from('permit_results').select('*').eq('run_id', runId)
          .order('is_permit_issued', { ascending: false })
          .order('permit_issue_date', { ascending: false, nullsFirst: false })
          .order('application_number', { ascending: false }).order('id').range(from, to)
        if (error) throw error
        return (data ?? []) as Array<Record<string, unknown>>
      })
      return rows.map((row) => ({
        id: String(row.id), runId: String(row.run_id), cityName: String(row.city_name), address: String(row.address ?? 'לא ידוע'),
        applicationNumber: String(row.application_number ?? 'לא ידוע'),
        submissionDate: row.submission_date ? String(row.submission_date) : undefined,
        permitIssueDate: row.permit_issue_date ? String(row.permit_issue_date) : undefined,
        permitNumber: String(row.permit_number || (row.is_permit_issued ? 'לא ידוע' : 'טרם הופק')),
        statusOriginal: String(row.display_status ?? 'טרם אושר'),
        sourceUrl: String(row.source_url), confidence: row.permit_confidence as Permit['confidence'],
        isPermitIssued: Boolean(row.is_permit_issued), isApproved: Boolean(row.is_approved),
      }))
    },
    async downloadReport(run) {
      const { data, error } = await client.functions.invoke('create-download-url', { body: { runId: run.id } })
      if (error) throw await functionError(error)
      window.location.assign(data.url)
    },
  }
}

const supabaseUrl = import.meta.env.VITE_SUPABASE_URL as string | undefined
const supabaseAnonKey = import.meta.env.VITE_SUPABASE_ANON_KEY as string | undefined
export const isLocalBackend = import.meta.env.VITE_USE_LOCAL_BACKEND === 'true' || !supabaseUrl || !supabaseAnonKey
export const supabaseClient = !isLocalBackend ? createClient(supabaseUrl!, supabaseAnonKey!) : null
export const api: PilotApi = isLocalBackend ? createLocalApi() : createSupabaseApi(supabaseClient!)
