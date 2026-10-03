import { afterEach, beforeEach, expect, it, vi } from 'vitest'

beforeEach(() => {
  vi.resetModules()
  vi.stubEnv('VITE_USE_LOCAL_BACKEND', 'true')
  vi.useFakeTimers()
  vi.setSystemTime(new Date('2026-10-03T00:00:00Z'))
})
afterEach(() => { vi.useRealTimers(); vi.unstubAllEnvs() })

it('demo summary mode preserves matching rows as unknown and never serves the full demo workbook', async () => {
  const { api } = await import('./api')
  const run = await api.startRun({ cityId: '7900', dateFrom: '2024-04-01', dateTo: '2024-04-30', collectionMode: 'public_summary' })
  vi.advanceTimersByTime(3000)
  const finished = await api.getRun(run.id)
  const rows = await api.listPermits(run.id)
  expect(finished.status).toBe('requires_review')
  expect(finished.applicationsFound).toBe(rows.length)
  expect(finished.permitsFound).toBe(0)
  expect(finished.reportPath).toBeUndefined()
  expect(rows).toHaveLength(4)
  expect(rows.every(row => row.permitVerification === 'unknown' && !row.isPermitIssued && !row.permitIssueDate)).toBe(true)
})

it('demo summaries outside the selected range remain an unverified zero', async () => {
  const { api } = await import('./api')
  const run = await api.startRun({ cityId: '7900', dateFrom: '2026-01-01', dateTo: '2026-01-31', collectionMode: 'public_summary' })
  vi.advanceTimersByTime(3000)
  const finished = await api.getRun(run.id)
  expect(finished.applicationsFound).toBe(0)
  expect(finished.coverageVerification).toBe('zero_not_verified')
  expect(finished.status).toBe('requires_review')
  expect(await api.listPermits(run.id)).toEqual([])
})

it('demo rejects unsupported summary sources before creating a run', async () => {
  const { api } = await import('./api')
  await expect(api.startRun({ cityId: '3000', dateFrom: '2024-04-01', dateTo: '2024-04-30', collectionMode: 'public_summary' })).rejects.toThrow()
  expect(await api.getActiveRun()).toBeNull()
})
