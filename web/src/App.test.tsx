// @vitest-environment jsdom

import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import '@testing-library/jest-dom/vitest'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { PilotApi, Run } from './types'

const mocked = vi.hoisted(() => ({
  api: {
    listCities: vi.fn(),
    getActiveRun: vi.fn(),
    listRuns: vi.fn(),
    startRun: vi.fn(),
    cancelRun: vi.fn(),
    getRun: vi.fn(),
    listPermits: vi.fn(),
    downloadReport: vi.fn(),
  },
}))

vi.mock('./lib/api', () => ({
  api: mocked.api as unknown as PilotApi,
  isLocalBackend: false,
  supabaseClient: null,
}))

import App from './App'

const cancelledRun: Run = {
  id: 'cancelled-run',
  cityId: '3000',
  cityName: 'ירושלים',
  dateFrom: '2025-07-01',
  dateTo: '2025-07-31',
  status: 'cancelled',
  createdAt: '2026-08-03T20:00:00Z',
  completedAt: '2026-08-03T20:05:00Z',
  cancelRequestedAt: '2026-08-03T20:04:00Z',
  unitsTotal: 3758,
  unitsCompleted: 40,
  permitsFound: 1,
  applicationsFound: 3,
  reportPath: 'cancelled-run/report.xlsx',
}

const runningRun: Run = {
  ...cancelledRun,
  id: 'running-run',
  status: 'running',
  completedAt: undefined,
  cancelRequestedAt: undefined,
  reportPath: undefined,
}

describe('App cancellation reset', () => {
  afterEach(cleanup)

  beforeEach(() => {
    vi.resetAllMocks()
    mocked.api.getActiveRun.mockResolvedValue(null)
    mocked.api.getRun.mockResolvedValue(runningRun)
    mocked.api.listCities.mockResolvedValue([
      { id: '3000', name: 'ירושלים' },
      { id: '7900', name: 'פתח תקווה' },
    ])
    mocked.api.listRuns.mockResolvedValue([cancelledRun])
    mocked.api.listPermits.mockResolvedValue([])
  })

  it('opens on a clean screen without loading the previous run', async () => {
    render(<App />)

    await screen.findByRole('button', { name: 'הפעלת סריקה' })
    expect(screen.getByText('לאחר הפעלת הסריקה יוצגו כאן ההתקדמות והתוצאות.')).toBeTruthy()
    expect(screen.queryByText('הסריקה בוטלה')).toBeNull()
    expect(screen.getByRole('button', { name: 'איפוס' })).toBeEnabled()
    expect(mocked.api.listRuns).not.toHaveBeenCalled()
    expect(mocked.api.listPermits).not.toHaveBeenCalled()
  })

  it('waits for server acceptance before claiming cancellation', async () => {
    let acceptStop!: (run: Run) => void
    mocked.api.startRun.mockResolvedValue(runningRun)
    mocked.api.cancelRun.mockReturnValue(new Promise<Run>((resolve) => { acceptStop = resolve }))
    mocked.api.getRun.mockReturnValue(new Promise(() => undefined))
    mocked.api.listPermits.mockResolvedValue([])
    render(<App />)

    fireEvent.click(await screen.findByRole('button', { name: 'הפעלת סריקה' }))
    fireEvent.click(await screen.findByRole('button', { name: 'עצירת הסריקה' }))
    fireEvent.click(screen.getByRole('button', { name: 'כן, עצור את הסריקה' }))

    expect(screen.getByRole('combobox', { name: 'עיר' })).toBeDisabled()
    expect(screen.queryByText('הסריקה בוטלה')).toBeNull()
    await act(async () => acceptStop({ ...runningRun, status: 'cancelled' }))
    await waitFor(() => expect(screen.getByRole('button', { name: 'הפעלת סריקה' })).toBeEnabled())
    expect(screen.getByText('הסריקה בוטלה')).toBeTruthy()
    expect(screen.getByRole('button', { name: 'הורדת Excel חלקי' })).toBeDisabled()
    expect(mocked.api.cancelRun).toHaveBeenCalledWith(runningRun.id)
  })

  it('clears a finished run from the screen without changing saved data', async () => {
    mocked.api.startRun.mockResolvedValue(cancelledRun)
    render(<App />)

    fireEvent.click(await screen.findByRole('button', { name: 'הפעלת סריקה' }))
    await screen.findByText('הסריקה בוטלה')
    fireEvent.click(screen.getByRole('button', { name: 'איפוס' }))

    expect(screen.getByText('לאחר הפעלת הסריקה יוצגו כאן ההתקדמות והתוצאות.')).toBeTruthy()
    expect(screen.queryByText('הסריקה בוטלה')).toBeNull()
    expect(screen.getByRole('combobox', { name: 'עיר' })).toHaveValue('7900')
    expect(mocked.api.cancelRun).not.toHaveBeenCalled()
    expect(mocked.api.startRun).toHaveBeenCalledOnce()
  })

  it('loads history only on request and opens a selected scan', async () => {
    render(<App />)

    const historyButton = await screen.findByRole('button', { name: 'סריקות קודמות' })
    expect(mocked.api.listRuns).not.toHaveBeenCalled()
    fireEvent.click(historyButton)

    expect(await screen.findByRole('heading', { name: 'סריקות קודמות' })).toBeTruthy()
    expect(mocked.api.listRuns).toHaveBeenCalledOnce()
    expect(screen.getByText('ירושלים')).toBeTruthy()
    expect(screen.getByText('בוטלה')).toBeTruthy()

    fireEvent.click(screen.getByRole('button', { name: 'הצגה' }))
    await waitFor(() => expect(mocked.api.listPermits).toHaveBeenCalledWith(cancelledRun.id))
    expect(screen.getByText('הסריקה בוטלה')).toBeTruthy()
  })
})
