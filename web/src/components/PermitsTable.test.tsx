// @vitest-environment jsdom

import { cleanup, render, screen } from '@testing-library/react'
import '@testing-library/jest-dom/vitest'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { Permit, Run } from '../types'
import { PermitsTable } from './PermitsTable'

afterEach(cleanup)

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
  it('counts unknown permits separately and does not count verified absence as unknown', () => {
    const { getByText } = render(<PermitsTable run={run} permits={[
      { ...results[1], id: 'unknown', permitVerification: 'unknown', permitNumber: 'לא ידוע' },
      { ...results[1], id: 'negative', permitVerification: 'verified_not_issued' },
      results[0],
    ]} onDownload={vi.fn()} />)
    expect(getByText(/מצב ההיתר לא ידוע עבור בקשה אחת/)).toBeVisible()
    expect(getByText(/אין להסיק מכך שלא הוצא לה היתר/)).toBeVisible()
  })
  it('shows pending applications together with issued permits and keeps the source link', () => {
    render(<PermitsTable run={run} permits={results} onDownload={vi.fn()} />)

    expect(screen.getByRole('heading', { name: 'בקשות והיתרים שנמצאו' })).toBeInTheDocument()
    expect(screen.getByText('2 בקשות שנמצאו, 1 היתר שאומת בהרצה')).toBeInTheDocument()
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

  it('labels an old completed zero as a partial unverified result', () => {
    const { container, getByText } = render(
      <PermitsTable run={{ ...run, applicationsFound: 0, permitsFound: 0, coverageVerification: 'zero_not_verified' }} permits={[]} onDownload={vi.fn()} />,
    )
    expect(container.querySelector('table')).toBeNull()
    expect(getByText(/תוצאת האפס לא אומתה עצמאית/)).toBeInTheDocument()
    expect(container.querySelector('button')).toHaveTextContent('הורדת Excel חלקי')
    expect(container.querySelector('button')).toBeEnabled()
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
