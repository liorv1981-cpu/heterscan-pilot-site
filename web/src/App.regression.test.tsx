// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import '@testing-library/jest-dom/vitest'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import type { Permit, Run } from './types'

const mocked = vi.hoisted(() => ({ api: {
  listCities: vi.fn(), getActiveRun: vi.fn(), listRuns: vi.fn(), startRun: vi.fn(),
  cancelRun: vi.fn(), getRun: vi.fn(), listPermits: vi.fn(), downloadReport: vi.fn(),
} }))
vi.mock('./lib/api', () => ({ api: mocked.api, isLocalBackend: false }))
import App from './App'

const running: Run = { id: 'live', cityId: '7900', cityName: 'פתח תקווה', dateFrom: '2026-01-01', dateTo: '2026-01-31',
  status: 'running', createdAt: '2026-09-13T05:00:00Z', unitsTotal: 100, unitsCompleted: 5, applicationsFound: 1, permitsFound: 0 }
const finished: Run = { ...running, id: 'old', status: 'completed', reportPath: 'old/report.xlsx' }
function row(runId: string, applicationNumber: string): Permit {
  return { id: applicationNumber, runId, applicationNumber, cityName: 'פתח תקווה', address: 'בדיקה',
    permitNumber: 'טרם הופק', statusOriginal: 'טרם אושר', sourceUrl: 'https://example.test', isPermitIssued: false, isApproved: false }
}
function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((done) => { resolve = done })
  return { promise, resolve }
}
afterEach(cleanup)
beforeEach(() => {
  vi.resetAllMocks()
  mocked.api.listCities.mockResolvedValue([{ id: '7900', name: 'פתח תקווה' }])
  mocked.api.getActiveRun.mockResolvedValue(null)
  mocked.api.listRuns.mockResolvedValue([finished])
  mocked.api.listPermits.mockResolvedValue([])
  mocked.api.getRun.mockResolvedValue(running)
})

it('recovers live work on startup and keeps it locked while viewing history', async () => {
  mocked.api.getActiveRun.mockResolvedValue(running)
  render(<App />)
  await screen.findByText('הסריקה מתבצעת')
  fireEvent.click(screen.getByRole('button', { name: 'סריקות קודמות' }))
  fireEvent.click(await screen.findByRole('button', { name: 'הצגה' }))
  await screen.findByText('הסריקה הושלמה')
  expect(screen.getByRole('combobox', { name: 'עיר' })).toBeDisabled()
  expect(screen.getByRole('button', { name: 'איפוס' })).toBeDisabled()
  fireEvent.submit(screen.getByRole('form', { name: 'הפעלת סריקה חדשה' }))
  expect(mocked.api.startRun).not.toHaveBeenCalled()
  fireEvent.click(screen.getByRole('button', { name: 'חזרה לסריקה הפעילה' }))
  await screen.findByText('הסריקה מתבצעת')
})

it('blocks double submission while startup is pending', async () => {
  const start = deferred<Run>()
  mocked.api.startRun.mockReturnValue(start.promise)
  render(<App />)
  fireEvent.click(await screen.findByRole('button', { name: 'הפעלת סריקה' }))
  fireEvent.submit(screen.getByRole('form', { name: 'הפעלת סריקה חדשה' }))
  expect(mocked.api.startRun).toHaveBeenCalledOnce()
  expect(screen.getByRole('button', { name: 'מפעיל סריקה…' })).toBeDisabled()
  await act(async () => start.resolve(running))
})

it('shows loading and discards responses from an older historical selection', async () => {
  const oldResults = deferred<Permit[]>()
  mocked.api.listRuns.mockResolvedValue([finished, { ...finished, id: 'second' }])
  mocked.api.listPermits.mockImplementation((id: string) => id === 'old' ? oldResults.promise : Promise.resolve([row('second', 'NEW')]))
  render(<App />)
  fireEvent.click(await screen.findByRole('button', { name: 'סריקות קודמות' }))
  await waitFor(() => expect(screen.getAllByRole('button', { name: 'הצגה' })).toHaveLength(2))
  fireEvent.click(screen.getAllByRole('button', { name: 'הצגה' })[0])
  await screen.findByText('טוען תוצאות…')
  expect(screen.queryByText('לא נמצאו בקשות או היתרים בטווח שנבחר.')).toBeNull()
  fireEvent.click(screen.getAllByRole('button', { name: 'הצגה' })[1])
  await screen.findByText('NEW')
  await act(async () => oldResults.resolve([row('old', 'OLD')]))
  expect(screen.queryByText('OLD')).toBeNull()
  expect(screen.getByText('NEW')).toBeVisible()
})

it('retains the results request when polling changes the status to completed', async () => {
  const response = deferred<Permit[]>()
  mocked.api.startRun.mockResolvedValue(running)
  mocked.api.getRun.mockResolvedValue({ ...finished, id: running.id })
  mocked.api.listPermits.mockReturnValue(response.promise)
  render(<App />)
  fireEvent.click(await screen.findByRole('button', { name: 'הפעלת סריקה' }))
  await screen.findByText('הסריקה הושלמה', {}, { timeout: 4000 })
  await act(async () => response.resolve([row(running.id, 'AFTER-POLL')]))
  expect(await screen.findByText('AFTER-POLL')).toBeVisible()
})

it('offers retry on a results failure without claiming an empty scan', async () => {
  mocked.api.listPermits.mockRejectedValueOnce(new Error('offline')).mockResolvedValue([row('old', 'RETRIED')])
  render(<App />)
  fireEvent.click(await screen.findByRole('button', { name: 'סריקות קודמות' }))
  fireEvent.click(await screen.findByRole('button', { name: 'הצגה' }))
  fireEvent.click(await screen.findByRole('button', { name: 'ניסיון נוסף' }))
  expect(await screen.findByText('RETRIED')).toBeVisible()
})

it('keeps the run active if the stop request fails', async () => {
  mocked.api.startRun.mockResolvedValue(running)
  mocked.api.cancelRun.mockRejectedValue(new Error('השרת לא זמין'))
  render(<App />)
  fireEvent.click(await screen.findByRole('button', { name: 'הפעלת סריקה' }))
  fireEvent.click(await screen.findByRole('button', { name: 'עצירת הסריקה' }))
  fireEvent.click(screen.getByRole('button', { name: 'כן, עצור את הסריקה' }))
  await screen.findByText('השרת לא זמין')
  expect(screen.queryByText('הסריקה בוטלה')).toBeNull()
  expect(screen.getByRole('combobox', { name: 'עיר' })).toBeDisabled()
})

it('waits for the partial report even if cancellation happened before worker startup', async () => {
  const cancelled: Run = { ...running, status: 'cancelled', applicationsFound: 0, reportPath: undefined, startedAt: undefined }
  mocked.api.startRun.mockResolvedValue(running)
  mocked.api.cancelRun.mockResolvedValue(cancelled)
  mocked.api.getRun.mockResolvedValue({ ...cancelled, reportPath: 'run/partial.xlsx' })
  render(<App />)
  fireEvent.click(await screen.findByRole('button', { name: 'הפעלת סריקה' }))
  fireEvent.click(await screen.findByRole('button', { name: 'עצירת הסריקה' }))
  fireEvent.click(screen.getByRole('button', { name: 'כן, עצור את הסריקה' }))
  await screen.findByText('הסריקה בוטלה')
  await waitFor(() => expect(screen.getByRole('button', { name: 'הורדת Excel חלקי' })).toBeEnabled(), { timeout: 4000 })
})
