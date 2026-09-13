// @vitest-environment jsdom

import { render, screen } from '@testing-library/react'
import '@testing-library/jest-dom/vitest'
import { describe, expect, it, vi } from 'vitest'
import type { Permit, Run } from '../types'
import { PermitsTable } from './PermitsTable'

const run: Run = {
  id: 'run-1', cityId: '7900', cityName: 'פתח תקווה', dateFrom: '2025-12-01', dateTo: '2025-12-31',
  status: 'completed', createdAt: '2026-08-08T08:00:00Z', completedAt: '2026-08-08T09:00:00Z',
  unitsTotal: 1166, unitsCompleted: 1166, permitsFound: 1, applicationsFound: 2, reportPath: 'run-1/report.xlsx',
}

const results: Permit[] = [
  {
    id: 'permit-1', runId: 'run-1', cityName: 'פתח תקווה', address: 'רוטשילד 9',
    applicationNumber: '20250001', submissionDate: '2025-12-01', permitNumber: '2025-100', permitIssueDate: '2025-12-15',
    statusOriginal: 'היתר הופק', sourceUrl: 'https://example.test/issued', confidence: 'high',
    isPermitIssued: true, isApproved: true,
  },
  {
    id: 'pending-1', runId: 'run-1', cityName: 'פתח תקווה', address: 'חיים עוזר 12',
    applicationNumber: '20250002', submissionDate: '2025-12-31', permitNumber: 'טרם הופק', statusOriginal: 'טרם אושר',
    sourceUrl: 'https://example.test/pending', isPermitIssued: false, isApproved: false,
  },
]

describe('PermitsTable', () => {
  it('shows pending applications together with issued permits and keeps the source link', () => {
    render(<PermitsTable run={run} permits={results} onDownload={vi.fn()} />)

    expect(screen.getByRole('heading', { name: 'בקשות והיתרים שנמצאו' })).toBeInTheDocument()
    expect(screen.getByText('2 בקשות, מתוכן 1 היתרים שהופקו')).toBeInTheDocument()
    expect(screen.getByText('טרם אושר')).toBeInTheDocument()
    expect(screen.getByText('טרם הופק')).toBeInTheDocument()
    expect(screen.getByText('01.12.2025')).toBeInTheDocument()
    expect(screen.getByText('31.12.2025')).toBeInTheDocument()
    expect(screen.getByText('15.12.2025')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'פתיחת מקור עבור בקשה 20250002' }))
      .toHaveAttribute('href', 'https://example.test/pending')
  })

  it('keeps the partial download even when a cancelled scan has no result rows', () => {
    const { container } = render(
      <PermitsTable run={{ ...run, status: 'cancelled' }} permits={[]} onDownload={vi.fn()} />,
    )

    expect(container.querySelector('table')).toBeNull()
    expect(screen.getByRole('button', { name: 'הורדת Excel חלקי' })).toBeEnabled()
  })

  it('opens Yavne requests through the public search route instead of the session-bound source URL', () => {
    const yavneResult: Permit = {
      ...results[0],
      id: 'yavne-1',
      cityName: 'יבנה',
      applicationNumber: '20260008',
      sourceUrl: 'https://handasi.complot.co.il/magicscripts/mgrqispi.dll?appname=cixpa&prgname=GetBakashaFile&siteid=87&b=20260008',
    }

    render(<PermitsTable run={{ ...run, cityName: 'יבנה' }} permits={[yavneResult]} onDownload={vi.fn()} />)

    expect(screen.getByRole('link', { name: 'פתיחת מקור עבור בקשה 20260008' }))
      .toHaveAttribute(
        'href',
        'https://yavne.complot.co.il/iturbakashot2/#search/GetBakashotByNumber&siteid=87&grp=0&t=0&b=20260008&l=true&arguments=siteId,grp,t,b,l',
      )
    expect(screen.getByText('איתור באתר יבנה')).toBeInTheDocument()
  })
})
