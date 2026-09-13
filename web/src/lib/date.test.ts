import { describe, expect, it } from 'vitest'
import { formatDate, formatIsoDate, validateDateRange } from './date'

describe('date display', () => {
  it('always renders dates as DD.MM.YYYY', () => {
    expect(formatIsoDate('2026-01-31')).toBe('31.01.2026')
    expect(formatDate('2026-01-31')).toBe('31.01.2026')
  })

  it('keeps the same date order when a time is present', () => {
    expect(formatDate('2026-01-31T12:34:00+02:00')).toBe('31.01.2026, 12:34')
  })
})

describe('validateDateRange', () => {
  it('rejects a reversed range', () => {
    expect(validateDateRange('2025-02-01', '2025-01-01')).toContain('תאריך ההתחלה')
  })

  it('accepts a valid historic range', () => {
    expect(validateDateRange('2024-01-01', '2024-01-31')).toBeNull()
  })
})
