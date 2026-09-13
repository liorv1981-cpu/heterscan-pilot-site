export function todayIso(): string {
  return new Intl.DateTimeFormat('en-CA', {
    timeZone: 'Asia/Jerusalem',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  }).format(new Date())
}

export function daysAgoIso(days: number): string {
  const date = new Date()
  date.setDate(date.getDate() - days)
  return new Intl.DateTimeFormat('en-CA', {
    timeZone: 'Asia/Jerusalem',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  }).format(date)
}

export function validateDateRange(dateFrom: string, dateTo: string): string | null {
  if (!dateFrom || !dateTo) return 'יש לבחור תאריך התחלה ותאריך סיום.'
  if (dateFrom > dateTo) return 'תאריך ההתחלה חייב להיות מוקדם מתאריך הסיום.'
  if (dateTo > todayIso()) return 'לא ניתן לסרוק תאריכים עתידיים.'
  return null
}

export function formatIsoDate(value?: string): string {
  if (!value) return '—'
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value.slice(0, 10))
  if (!match) return '—'
  return `${match[3]}.${match[2]}.${match[1]}`
}

export function formatDate(value?: string): string {
  if (!value) return '—'
  if (value.length === 10) return formatIsoDate(value)
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return '—'
  const parts = new Intl.DateTimeFormat('en-GB', {
    year: 'numeric', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit', hourCycle: 'h23',
    timeZone: 'Asia/Jerusalem',
  }).formatToParts(date)
  const part = (type: Intl.DateTimeFormatPartTypes) => parts.find((item) => item.type === type)?.value ?? ''
  return `${part('day')}.${part('month')}.${part('year')}, ${part('hour')}:${part('minute')}`
}

export function formatDuration(runStartedAt?: string, runCompletedAt?: string): string {
  if (!runStartedAt) return '—'
  const end = runCompletedAt ? new Date(runCompletedAt) : new Date()
  const seconds = Math.max(0, Math.floor((end.getTime() - new Date(runStartedAt).getTime()) / 1000))
  const hours = Math.floor(seconds / 3600)
  const minutes = Math.floor((seconds % 3600) / 60)
  const remainder = seconds % 60
  return [hours, minutes, remainder].map((part) => String(part).padStart(2, '0')).join(':')
}
