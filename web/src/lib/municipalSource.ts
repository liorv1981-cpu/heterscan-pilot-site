import type { Permit } from '../types'

const YAVNE_SEARCH_BASE_URL = 'https://yavne.complot.co.il/iturbakashot2/#search/GetBakashotByNumber'

export interface MunicipalSourceLink {
  href: string
  label: string
}

export function getMunicipalSourceLink(permit: Permit): MunicipalSourceLink {
  if (permit.cityName.trim() === 'יבנה' && /^\d+$/.test(permit.applicationNumber.trim())) {
    const requestNumber = encodeURIComponent(permit.applicationNumber.trim())
    return {
      href: `${YAVNE_SEARCH_BASE_URL}&siteid=87&grp=0&t=0&b=${requestNumber}&l=true&arguments=siteId,grp,t,b,l`,
      label: 'איתור באתר יבנה',
    }
  }

  return {
    href: permit.sourceUrl,
    label: 'אתר עירוני',
  }
}
