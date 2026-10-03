export function reportDownloadFilename(run: {
  id: string; cityName: string; dateFrom: string; dateTo: string
}, generatedAt: string): string {
  const city = run.cityName.normalize('NFKC').replace(/[^\p{L}\p{N}_-]+/gu, '-').replace(/^-+|-+$/g, '')
  if (!city) throw new Error('חסר שם רשות לדוח.')
  const parts = new Intl.DateTimeFormat('en', {
    timeZone: 'Asia/Jerusalem', year: 'numeric', month: '2-digit', day: '2-digit',
  }).formatToParts(new Date(generatedAt))
  const part = (type: string) => parts.find((item) => item.type === type)?.value ?? ''
  return `HETERSCAN_${city}_${run.dateFrom}_${run.dateTo}_הופק-${part('year')}-${part('month')}-${part('day')}_${run.id}.xlsx`
}
