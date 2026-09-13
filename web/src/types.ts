export type RunStatus =
  | 'created'
  | 'dispatching'
  | 'running'
  | 'safely_stopped'
  | 'dispatch_failed'
  | 'dispatch_timeout'
  | 'cancelled'
  | 'completed'
  | 'completed_with_errors'
  | 'requires_review'
  | 'failed'

export interface City {
  id: string
  name: string
}

export interface Run {
  id: string
  cityId: string
  cityName: string
  dateFrom: string
  dateTo: string
  status: RunStatus
  createdAt: string
  startedAt?: string
  completedAt?: string
  cancelRequestedAt?: string
  unitsTotal: number
  unitsCompleted: number
  permitsFound: number
  applicationsFound: number
  reportPath?: string
  errorMessage?: string
}

export interface Permit {
  id: string
  runId: string
  cityName: string
  address: string
  applicationNumber: string
  submissionDate?: string
  permitNumber: string
  permitIssueDate?: string
  statusOriginal: string
  sourceUrl: string
  confidence?: 'high' | 'medium' | 'low'
  isPermitIssued: boolean
  isApproved: boolean
}

export interface StartRunInput {
  cityId: string
  dateFrom: string
  dateTo: string
}

export interface PilotApi {
  listCities(): Promise<City[]>
  getActiveRun(): Promise<Run | null>
  listRuns(): Promise<Run[]>
  startRun(input: StartRunInput): Promise<Run>
  cancelRun(runId: string): Promise<Run>
  getRun(runId: string): Promise<Run>
  listPermits(runId: string): Promise<Permit[]>
  downloadReport(run: Run, permits: Permit[]): Promise<void>
}
