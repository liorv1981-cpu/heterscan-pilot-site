import type { Run } from '../types'

export const activeStatuses: Run['status'][] = ['created', 'dispatching', 'running', 'safely_stopped']
export function isActiveRun(run: Pick<Run, 'status'> | null): boolean {
  return Boolean(run && activeStatuses.includes(run.status))
}
