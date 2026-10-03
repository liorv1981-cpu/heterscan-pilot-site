import { describe, expect, it } from 'vitest'
import { collectionModeFor } from '../../../supabase/functions/start-run/collection'

describe('start-run collection policy', () => {
  it('preserves the existing detail mode for an omitted request', () => {
    expect(collectionModeFor('complot', undefined)).toBe('full_details')
    expect(collectionModeFor('jerusalem', undefined)).toBe('full_details')
  })
  it('accepts public summaries only for their supported source family', () => {
    expect(collectionModeFor('complot', 'public_summary')).toBe('public_summary')
    expect(() => collectionModeFor('jerusalem', 'public_summary')).toThrow()
    expect(() => collectionModeFor('tel_aviv', 'public_summary')).toThrow()
  })
  it.each([null, true, {}, 'captcha_solver', ''])('rejects invalid policy %s before a run can be inserted', (policy) => {
    expect(() => collectionModeFor('complot', policy)).toThrow()
  })
})
