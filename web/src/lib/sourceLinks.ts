// ArcGIS object IDs are reassigned during municipal imports; never use them as permalinks.
export function stableSourceUrl(sourceUrl: unknown, applicationNumber: unknown): string {
  const original = String(sourceUrl ?? '')
  try {
    const url = new URL(original)
    if (url.hostname === 'gisn.tel-aviv.gov.il'
      && /^\/ArcGIS\/rest\/services\/IView2\/MapServer\/772\/(?:[0-9]+|query)$/.test(url.pathname)) {
      const number = String(applicationNumber ?? '')
      if (!/^[0-9]+$/.test(number)) return ''
      const params = new URLSearchParams({
        where: `request_num = ${number}`,
        outFields: 'request_num,addresses,permission_num,permission_date,open_request,building_stage',
        returnGeometry: 'false', f: 'html',
      })
      return `https://gisn.tel-aviv.gov.il/ArcGIS/rest/services/IView2/MapServer/772/query?${params}`
    }
  } catch { /* Keep malformed evidence; the table already renders unsafe URLs as text. */ }
  return original
}
