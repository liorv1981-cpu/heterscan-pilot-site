import { FunctionsFetchError, FunctionsHttpError, FunctionsRelayError } from '@supabase/supabase-js'

export async function functionError(error: unknown): Promise<Error> {
  if (error instanceof FunctionsHttpError) {
    const response = error.context as Response
    let message: unknown
    try {
      const body = await response.clone().json()
      message = body.error ?? body.message
    } catch { /* Gateways can return a non-JSON error page. */ }
    if (typeof message === 'string' && /[\u0590-\u05ff]/.test(message)) return new Error(message)
    if (response.status === 401) return new Error('ההתחברות פגה או אינה תקפה. יש לצאת ולהתחבר מחדש.')
    if (response.status === 403) return new Error('אין הרשאה לבצע את הפעולה. יש להתחבר עם משתמש מורשה.')
    return new Error(`השרת לא הצליח לבצע את הפעולה (קוד ${response.status}). נא לנסות שוב בעוד כמה דקות.`)
  }
  if (error instanceof FunctionsFetchError || error instanceof FunctionsRelayError) {
    return new Error('לא ניתן להתחבר לשרת כרגע. יש לבדוק את החיבור לאינטרנט ולנסות שוב.')
  }
  return error instanceof Error ? error : new Error('לא ניתן לבצע את הפעולה כרגע.')
}
