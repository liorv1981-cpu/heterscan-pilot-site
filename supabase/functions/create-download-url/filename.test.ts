import { strict as assert } from 'node:assert'
import { test } from 'node:test'
import { reportDownloadFilename } from '../_shared/report_filename.ts'

test('download uses Hebrew city and Israel issue date independently of its ASCII storage key', () => {
  assert.equal(reportDownloadFilename({ id: 'run', cityName: 'ראשון לציון',
    dateFrom: '2026-01-01', dateTo: '2026-01-31' }, '2026-10-03T22:00:00Z'),
  'HETERSCAN_ראשון-לציון_2026-01-01_2026-01-31_הופק-2026-10-04_run.xlsx')
})

test('empty city cannot silently create an unidentified report', () => {
  assert.throws(() => reportDownloadFilename({ id: 'run', cityName: ' ',
    dateFrom: '2026-01-01', dateTo: '2026-01-31' }, '2026-10-03T22:00:00Z'))
})
