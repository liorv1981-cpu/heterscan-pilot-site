// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import '@testing-library/jest-dom/vitest'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { Run } from '../types'
import { RunForm } from './RunForm'

const displayedRun: Run = {
  id: 'run-1', cityId: '7900', cityName: 'פתח תקווה', dateFrom: '2026-01-01', dateTo: '2026-01-31',
  status: 'completed', createdAt: '2026-02-01T08:00:00Z', unitsTotal: 1, unitsCompleted: 1,
  applicationsFound: 0, permitsFound: 0,
}

afterEach(cleanup)

describe('RunForm date display', () => {
  it('moves keyboard focus across days and restores the trigger on Escape', () => {
    render(<RunForm cities={[{ id: '7900', name: 'פתח תקווה' }]} disabled={false} displayedRun={displayedRun} onSubmit={vi.fn()} onReset={vi.fn()} />)
    const trigger = screen.getByRole('button', { name: 'פתיחת לוח שנה: מתאריך' })
    fireEvent.click(trigger)
    const first = screen.getByRole('button', { name: '01/01/2026' })
    expect(first).toHaveFocus()
    fireEvent.keyDown(first, { key: 'ArrowLeft' })
    const next = screen.getByRole('button', { name: '02/01/2026' })
    expect(next).toHaveFocus()
    fireEvent.keyDown(next, { key: 'PageDown' })
    const february = screen.getByRole('button', { name: '02/02/2026' })
    expect(february).toHaveFocus()
    fireEvent.keyDown(february, { key: 'Escape' })
    expect(screen.queryByRole('dialog')).toBeNull()
    expect(trigger).toHaveFocus()
  })
  it('shows the previous range in editable DD/MM/YYYY fields', () => {
    render(
      <RunForm
        cities={[{ id: '7900', name: 'פתח תקווה' }]}
        disabled={false}
        displayedRun={displayedRun}
        onSubmit={vi.fn()}
        onReset={vi.fn()}
      />,
    )

    expect(screen.getByLabelText('מתאריך')).toHaveAttribute('type', 'text')
    expect(screen.getByLabelText('מתאריך')).toBeVisible()
    expect(screen.getByLabelText('מתאריך')).toHaveValue('01/01/2026')
    expect(screen.getByLabelText('עד תאריך')).toHaveValue('31/01/2026')
  })

  it('updates the formatted value and submits the selected ISO range', async () => {
    const onSubmit = vi.fn().mockResolvedValue(undefined)
    render(
      <RunForm
        cities={[{ id: '7900', name: 'פתח תקווה' }]}
        disabled={false}
        displayedRun={displayedRun}
        onSubmit={onSubmit}
        onReset={vi.fn()}
      />,
    )

    fireEvent.change(screen.getByLabelText('מתאריך'), { target: { value: '15012026' } })
    fireEvent.change(screen.getByLabelText('עד תאריך'), { target: { value: '31/01/2026' } })
    expect(screen.getByLabelText('מתאריך')).toHaveValue('15/01/2026')
    expect(screen.getByLabelText('עד תאריך')).toHaveValue('31/01/2026')

    fireEvent.click(screen.getByRole('button', { name: 'הפעלת סריקה' }))
    await waitFor(() => expect(onSubmit).toHaveBeenCalledWith({
      cityId: '7900', dateFrom: '2026-01-15', dateTo: '2026-01-31',
    }))
  })

  it('allows moving the range to another year in either order', () => {
    render(
      <RunForm
        cities={[{ id: '7900', name: 'פתח תקווה' }]}
        disabled={false}
        displayedRun={displayedRun}
        onSubmit={vi.fn()}
        onReset={vi.fn()}
      />,
    )

    fireEvent.change(screen.getByLabelText('עד תאריך'), { target: { value: '31/12/2024' } })
    fireEvent.change(screen.getByLabelText('מתאריך'), { target: { value: '01/01/2024' } })
    expect(screen.getByLabelText('מתאריך')).toHaveValue('01/01/2024')
    expect(screen.getByLabelText('עד תאריך')).toHaveValue('31/12/2024')
  })

  it('blocks submission when a typed calendar date is invalid', async () => {
    const onSubmit = vi.fn()
    render(
      <RunForm
        cities={[{ id: '7900', name: 'פתח תקווה' }]}
        disabled={false}
        displayedRun={displayedRun}
        onSubmit={onSubmit}
        onReset={vi.fn()}
      />,
    )

    fireEvent.change(screen.getByLabelText('מתאריך'), { target: { value: '31/02/2024' } })
    fireEvent.click(screen.getByRole('button', { name: 'הפעלת סריקה' }))

    expect(await screen.findByRole('alert')).toHaveTextContent('יש להזין תאריך תקין בפורמט יום/חודש/שנה.')
    expect(onSubmit).not.toHaveBeenCalled()
  })

  it('offers a reset action after a completed run', () => {
    const onReset = vi.fn()
    render(
      <RunForm
        cities={[{ id: '7900', name: 'פתח תקווה' }]}
        disabled={false}
        displayedRun={displayedRun}
        onSubmit={vi.fn()}
        onReset={onReset}
      />,
    )

    fireEvent.click(screen.getByRole('button', { name: 'איפוס' }))
    expect(onReset).toHaveBeenCalledOnce()
  })

  it('keeps the reset action visible on a clean screen', () => {
    const onReset = vi.fn()
    render(
      <RunForm
        cities={[{ id: '7900', name: 'פתח תקווה' }]}
        disabled={false}
        displayedRun={null}
        onSubmit={vi.fn()}
        onReset={onReset}
      />,
    )

    fireEvent.click(screen.getByRole('button', { name: 'איפוס' }))
    expect(onReset).toHaveBeenCalledOnce()
  })

  it('opens the in-app calendar and selects a date', () => {
    render(
      <RunForm
        cities={[{ id: '7900', name: 'פתח תקווה' }]}
        disabled={false}
        displayedRun={null}
        onSubmit={vi.fn()}
        onReset={vi.fn()}
      />,
    )

    fireEvent.click(screen.getByRole('button', { name: 'פתיחת לוח שנה: מתאריך' }))
    expect(screen.getByRole('dialog', { name: 'בחירת תאריך: מתאריך' })).toBeVisible()
    fireEvent.click(screen.getByRole('button', { name: '01/08/2026' }))
    expect(screen.getByLabelText('מתאריך')).toHaveValue('01/08/2026')
    expect(screen.queryByRole('dialog', { name: 'בחירת תאריך: מתאריך' })).toBeNull()
  })
})
