// @vitest-environment jsdom

import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import type { Run } from '../types'
import { RunStatusPanel } from './RunStatusPanel'

const activeRun: Run = {
  id: 'run-1',
  cityId: '3000',
  cityName: 'ירושלים',
  dateFrom: '2025-07-01',
  dateTo: '2025-07-31',
  status: 'running',
  createdAt: '2026-08-03T20:00:00Z',
  startedAt: '2026-08-03T20:00:00Z',
  unitsTotal: 3758,
  unitsCompleted: 40,
  permitsFound: 1,
  applicationsFound: 3,
}

describe('RunStatusPanel cancellation controls', () => {
  it('requires an explicit second click before requesting cancellation', () => {
    const onStop = vi.fn().mockResolvedValue(undefined)
    render(<RunStatusPanel run={activeRun} isStopping={false} onStop={onStop} />)

    fireEvent.click(screen.getByRole('button', { name: 'עצירת הסריקה' }))
    expect(onStop).not.toHaveBeenCalled()
    expect(screen.getByText(/לאחר אישור העצירה בשרת/)).toBeTruthy()

    fireEvent.click(screen.getByRole('button', { name: 'כן, עצור את הסריקה' }))
    expect(onStop).toHaveBeenCalledOnce()
  })

  it('shows the persistent safe-stop message after the request is stored', () => {
    render(
      <RunStatusPanel
        run={{ ...activeRun, cancelRequestedAt: '2026-08-03T20:01:00Z' }}
        isStopping={false}
        onStop={vi.fn()}
      />,
    )

    expect(screen.getByText('בקשת העצירה התקבלה')).toBeTruthy()
    expect(screen.queryByRole('button', { name: 'עצירת הסריקה' })).toBeNull()
  })

  it('states that nothing was found when an empty run is cancelled', () => {
    render(
      <RunStatusPanel
        run={{ ...activeRun, status: 'cancelled', applicationsFound: 0, permitsFound: 0 }}
        isStopping={false}
        onStop={vi.fn()}
      />,
    )

    expect(screen.getByText(/עד העצירה לא נמצאו תוצאות/)).toBeTruthy()
    expect(screen.queryByText(/התוצאות שנמצאו עד העצירה מוצגות למטה/)).toBeNull()
  })

  it('never calls a zero-result review scan successful', () => {
    render(<RunStatusPanel run={{ ...activeRun, status: 'requires_review', applicationsFound: 0 }} isStopping={false} onStop={vi.fn()} />)
    expect(screen.queryByText(/הסריקה הסתיימה בהצלחה/)).toBeNull()
    expect(screen.getByText(/אין בכך אישור שאין בקשות בטווח/)).toBeTruthy()
  })
})
