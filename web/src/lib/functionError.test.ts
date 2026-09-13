import { describe, expect, it } from 'vitest'
import { FunctionsFetchError, FunctionsHttpError } from '@supabase/supabase-js'
import { functionError } from './functionError'

describe('function error messages', () => {
  it('shows the actual Hebrew reason without consuming the original response', async () => {
    const response = new Response(JSON.stringify({ error: 'כבר קיימת סריקה פעילה. יש להמתין לסיומה.' }), { status: 400 })
    expect((await functionError(new FunctionsHttpError(response))).message).toContain('כבר קיימת סריקה פעילה')
    expect(response.bodyUsed).toBe(false)
  })
  it('translates gateway authentication failures', async () => {
    const response = new Response(JSON.stringify({ message: 'Invalid JWT' }), { status: 401 })
    expect((await functionError(new FunctionsHttpError(response))).message).toContain('להתחבר מחדש')
  })
  it('handles HTML server errors without leaking their content', async () => {
    const response = new Response('<html>upstream error</html>', { status: 502 })
    expect((await functionError(new FunctionsHttpError(response))).message).toContain('קוד 502')
  })
  it('explains network failures in Hebrew', async () => {
    expect((await functionError(new FunctionsFetchError('offline'))).message).toContain('החיבור לאינטרנט')
  })
})
