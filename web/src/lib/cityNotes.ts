// Verified against scan history and source probes on 2026-09-09.
// These describe observed reliability, not a live availability guarantee.
const limitedCities = new Set(['6100', '7900', '8300', '8400'])
const completedScanCities = new Set(['3000', '5000'])
const sourceCheckedCities = new Set([
  '2600', '7100', '9000', '2610', '6200', '6400', '6600', '4000',
  '2660', '6900', '1200', '6800', '2630', '1161', '8600', '2650',
])

export function cityScanNote(cityId: string): string {
  if (limitedCities.has(cityId)) return 'זמינות מוגבלת — ייתכנו עיכובים'
  if (completedScanCities.has(cityId)) return 'סריקה מלאה נבדקה'
  if (sourceCheckedCities.has(cityId)) return 'גישה למקור נבדקה'
  return 'טרם אומתה סריקה מלאה'
}
