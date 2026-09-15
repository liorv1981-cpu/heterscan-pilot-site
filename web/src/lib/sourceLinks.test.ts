import { describe, expect, it } from 'vitest'
import { stableSourceUrl } from './sourceLinks'

const old = 'https://gisn.tel-aviv.gov.il/ArcGIS/rest/services/IView2/MapServer/772/4223'
describe('stable municipal source links', () => {
  it('uses each snapshot request number even when the same OID was recycled', () => {
    for (const number of ['20260016', '20260053']) {
      const url = new URL(stableSourceUrl(old, number))
      expect(url.pathname.endsWith('/query')).toBe(true)
      expect(url.searchParams.get('where')).toBe(`request_num = ${number}`)
    }
  })
  it('does not create a broad or injectable query without a numeric identity', () => {
    for (const number of [null, '', '1 OR 1=1']) expect(stableSourceUrl(old, number)).toBe('')
  })
  it('preserves unrelated and malformed sources', () => {
    for (const url of ['https://example.test/4223', 'https://[bad', old.replace('.gov.il/', '.gov.il.evil.test/')]) {
      expect(stableSourceUrl(url, '20260016')).toBe(url)
    }
  })
})
