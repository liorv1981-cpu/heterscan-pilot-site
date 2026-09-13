import { CalendarDays, Play, RotateCcw } from 'lucide-react'
import { useEffect, useId, useRef, useState, type FormEvent, type KeyboardEvent } from 'react'
import { daysAgoIso, todayIso, validateDateRange } from '../lib/date'
import { cityScanNote } from '../lib/cityNotes'
import type { City, Run, StartRunInput } from '../types'

interface RunFormProps {
  cities: City[]
  disabled: boolean
  disabledLabel?: string
  displayedRun: Run | null
  onSubmit(input: StartRunInput): Promise<void>
  onReset(): void
}

interface DatePickerFieldProps {
  label: string
  value: string
  min?: string
  max?: string
  disabled: boolean
  onChange(value: string): void
  onValidityChange(valid: boolean): void
}

function formatPickerDate(value: string): string {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value)
  return match ? `${match[3]}/${match[2]}/${match[1]}` : ''
}

function formatPickerDraft(value: string): string {
  const digits = value.replace(/\D/g, '').slice(0, 8)
  return [digits.slice(0, 2), digits.slice(2, 4), digits.slice(4, 8)].filter(Boolean).join('/')
}

function parsePickerDate(value: string): string | null {
  const match = /^(\d{2})\/(\d{2})\/(\d{4})$/.exec(value)
  if (!match) return null
  const [, day, month, year] = match
  const date = new Date(Date.UTC(Number(year), Number(month) - 1, Number(day)))
  if (
    date.getUTCFullYear() !== Number(year)
    || date.getUTCMonth() !== Number(month) - 1
    || date.getUTCDate() !== Number(day)
  ) return null
  return `${year}-${month}-${day}`
}

function dateFromIso(value: string): Date {
  const [year, month, day] = value.split('-').map(Number)
  return new Date(Date.UTC(year, month - 1, day))
}

function dateToIso(date: Date): string {
  const year = date.getUTCFullYear()
  const month = String(date.getUTCMonth() + 1).padStart(2, '0')
  const day = String(date.getUTCDate()).padStart(2, '0')
  return `${year}-${month}-${day}`
}

function DatePickerField({ label, value, min, max, disabled, onChange, onValidityChange }: DatePickerFieldProps) {
  const inputId = useId()
  const fieldRef = useRef<HTMLDivElement>(null)
  const toggleRef = useRef<HTMLButtonElement>(null)
  const [draft, setDraft] = useState(() => formatPickerDate(value))
  const [isValid, setIsValid] = useState(true)
  const [calendarOpen, setCalendarOpen] = useState(false)
  const [focusedDate, setFocusedDate] = useState(value)
  const [visibleMonth, setVisibleMonth] = useState(() => {
    const initial = dateFromIso(value)
    return new Date(Date.UTC(initial.getUTCFullYear(), initial.getUTCMonth(), 1))
  })

  useEffect(() => {
    if (!calendarOpen) return
    fieldRef.current?.querySelector<HTMLButtonElement>(`[data-day="${focusedDate}"]`)?.focus()
  }, [calendarOpen, focusedDate])

  useEffect(() => {
    if (!calendarOpen) return
    const closeOutside = (event: PointerEvent) => {
      if (!fieldRef.current?.contains(event.target as Node)) setCalendarOpen(false)
    }
    document.addEventListener('pointerdown', closeOutside)
    return () => document.removeEventListener('pointerdown', closeOutside)
  }, [calendarOpen])

  function focusDay(date: Date) {
    let iso = dateToIso(date)
    if (min && iso < min) iso = min
    if (max && iso > max) iso = max
    const clamped = dateFromIso(iso)
    setFocusedDate(iso)
    setVisibleMonth(new Date(Date.UTC(clamped.getUTCFullYear(), clamped.getUTCMonth(), 1)))
  }

  function changeMonth(delta: number) {
    const nextMonth = new Date(Date.UTC(visibleMonth.getUTCFullYear(), visibleMonth.getUTCMonth() + delta, 1))
    focusDay(nextMonth)
  }

  function handleDayKey(event: KeyboardEvent<HTMLButtonElement>, date: Date) {
    const next = new Date(date)
    const offsets: Record<string, number> = { ArrowLeft: 1, ArrowRight: -1, ArrowUp: -7, ArrowDown: 7, Home: -date.getUTCDay(), End: 6 - date.getUTCDay() }
    if (event.key in offsets) next.setUTCDate(next.getUTCDate() + offsets[event.key])
    else if (event.key === 'PageUp' || event.key === 'PageDown') {
      const month = next.getUTCMonth() + (event.key === 'PageUp' ? -1 : 1)
      const lastDay = new Date(Date.UTC(next.getUTCFullYear(), month + 1, 0)).getUTCDate()
      next.setUTCDate(1)
      next.setUTCMonth(month)
      next.setUTCDate(Math.min(date.getUTCDate(), lastDay))
    } else return
    event.preventDefault()
    focusDay(next)
  }

  function updateValidity(valid: boolean) {
    setIsValid(valid)
    onValidityChange(valid)
  }

  function handleTextChange(rawValue: string) {
    const nextDraft = formatPickerDraft(rawValue)
    const nextValue = parsePickerDate(nextDraft)
    const valid = Boolean(nextValue && (!min || nextValue >= min) && (!max || nextValue <= max))
    setDraft(nextDraft)
    updateValidity(valid)
    if (valid && nextValue) onChange(nextValue)
  }

  function handleCalendarChange(nextValue: string) {
    if (!nextValue) return
    setDraft(formatPickerDate(nextValue))
    updateValidity(true)
    onChange(nextValue)
    setCalendarOpen(false)
    toggleRef.current?.focus()
  }

  function toggleCalendar() {
    if (disabled) return
    if (!calendarOpen) {
      const selected = dateFromIso(value)
      setFocusedDate(value)
      setVisibleMonth(new Date(Date.UTC(selected.getUTCFullYear(), selected.getUTCMonth(), 1)))
    }
    setCalendarOpen((open) => !open)
  }

  const firstDay = new Date(Date.UTC(visibleMonth.getUTCFullYear(), visibleMonth.getUTCMonth(), 1))
  const calendarStart = new Date(firstDay)
  calendarStart.setUTCDate(1 - firstDay.getUTCDay())
  const calendarDays = Array.from({ length: 42 }, (_, index) => {
    const date = new Date(calendarStart)
    date.setUTCDate(calendarStart.getUTCDate() + index)
    return date
  })
  const monthTitle = new Intl.DateTimeFormat('he-IL', { month: 'long', year: 'numeric', timeZone: 'UTC' }).format(firstDay)

  return (
    <div className="date-picker-field" ref={fieldRef} onBlur={(event) => {
      if (!event.currentTarget.contains(event.relatedTarget as Node | null)) setCalendarOpen(false)
    }} onKeyDown={(event) => {
      if (event.key === 'Escape' && calendarOpen) {
        event.preventDefault()
        setCalendarOpen(false)
        toggleRef.current?.focus()
      }
    }}>
      <label htmlFor={inputId}><span>{label}</span></label>
      <span className={`date-entry-shell${disabled ? ' date-entry-shell--disabled' : ''}${isValid ? '' : ' date-entry-shell--invalid'}`}>
        <input
          className="date-text-input"
          id={inputId}
          type="text"
          aria-label={label}
          aria-invalid={!isValid}
          inputMode="numeric"
          autoComplete="off"
          placeholder="DD/MM/YYYY"
          maxLength={10}
          dir="ltr"
          value={draft}
          onFocus={(event) => event.currentTarget.select()}
          onChange={(event) => handleTextChange(event.target.value)}
          disabled={disabled}
        />
        <button
          className="date-calendar-control"
          ref={toggleRef}
          type="button"
          aria-label={`פתיחת לוח שנה: ${label}`}
          aria-haspopup="dialog"
          aria-expanded={calendarOpen}
          onClick={toggleCalendar}
          disabled={disabled}
        >
          <CalendarDays size={19} />
        </button>
        {calendarOpen && !disabled ? (
          <span className="calendar-popover" role="dialog" aria-label={`בחירת תאריך: ${label}`}>
            <span className="calendar-header">
              <button
                type="button"
                aria-label="החודש הבא"
                disabled={Boolean(max && dateToIso(new Date(Date.UTC(visibleMonth.getUTCFullYear(), visibleMonth.getUTCMonth() + 1, 1))) > max)}
                onClick={() => changeMonth(1)}
              >‹</button>
              <strong>{monthTitle}</strong>
              <button
                type="button"
                aria-label="החודש הקודם"
                onClick={() => changeMonth(-1)}
              >›</button>
            </span>
            <span className="calendar-weekdays" aria-hidden="true">
              {['א', 'ב', 'ג', 'ד', 'ה', 'ו', 'ש'].map((day) => <span key={day}>{day}</span>)}
            </span>
            <span className="calendar-grid">
              {calendarDays.map((date) => {
                const isoDate = dateToIso(date)
                const outsideMonth = date.getUTCMonth() !== visibleMonth.getUTCMonth()
                const unavailable = Boolean((min && isoDate < min) || (max && isoDate > max))
                return (
                  <button
                    key={isoDate}
                    data-day={isoDate}
                    tabIndex={isoDate === focusedDate ? 0 : -1}
                    type="button"
                    className={`${outsideMonth ? 'calendar-day--outside ' : ''}${isoDate === value ? 'calendar-day--selected' : ''}`.trim()}
                    aria-label={formatPickerDate(isoDate)}
                    aria-pressed={isoDate === value}
                    disabled={unavailable}
                    onClick={() => handleCalendarChange(isoDate)}
                    onKeyDown={(event) => handleDayKey(event, date)}
                  >{date.getUTCDate()}</button>
                )
              })}
            </span>
          </span>
        ) : null}
      </span>
    </div>
  )
}

export function RunForm({ cities, disabled, disabledLabel, displayedRun, onSubmit, onReset }: RunFormProps) {
  const [cityId, setCityId] = useState(displayedRun?.cityId ?? '7900')
  const [dateFrom, setDateFrom] = useState(displayedRun?.dateFrom ?? daysAgoIso(30))
  const [dateTo, setDateTo] = useState(displayedRun?.dateTo ?? todayIso())
  const [dateFromValid, setDateFromValid] = useState(true)
  const [dateToValid, setDateToValid] = useState(true)
  const [error, setError] = useState<string | null>(null)

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (disabled) return
    if (!dateFromValid || !dateToValid) return setError('יש להזין תאריך תקין בפורמט יום/חודש/שנה.')
    const validationError = validateDateRange(dateFrom, dateTo)
    if (validationError) return setError(validationError)
    setError(null)
    await onSubmit({ cityId, dateFrom, dateTo })
  }

  return (
    <form className="run-form" onSubmit={handleSubmit} aria-label="הפעלת סריקה חדשה">
      <label>
        <span>עיר</span>
        <select value={cityId} onChange={(event) => setCityId(event.target.value)} disabled={disabled}>
          {cities.map((city) => <option key={city.id} value={city.id}>{city.name} ({cityScanNote(city.id)})</option>)}
        </select>
      </label>
      <DatePickerField label="מתאריך" value={dateFrom} max={todayIso()} onChange={setDateFrom} onValidityChange={setDateFromValid} disabled={disabled} />
      <DatePickerField label="עד תאריך" value={dateTo} max={todayIso()} onChange={setDateTo} onValidityChange={setDateToValid} disabled={disabled} />
      <div className="run-form-actions">
        <button className="primary-button" type="submit" disabled={disabled || cities.length === 0}>
          <Play size={18} fill="currentColor" />
          {disabled ? disabledLabel ?? 'הסריקה פועלת' : 'הפעלת סריקה'}
        </button>
        <button className="reset-button" type="button" onClick={onReset} disabled={disabled}>
          <RotateCcw size={17} />
          איפוס
        </button>
      </div>
      {error ? <p className="form-error" role="alert">{error}</p> : null}
    </form>
  )
}
