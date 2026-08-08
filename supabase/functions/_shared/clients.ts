import { createClient, type SupabaseClient, type User } from 'https://esm.sh/@supabase/supabase-js@2.111.0'

export function serviceClient(): SupabaseClient {
  return createClient(
    Deno.env.get('SUPABASE_URL')!,
    Deno.env.get('SUPABASE_SERVICE_ROLE_KEY')!,
    { auth: { persistSession: false, autoRefreshToken: false } },
  )
}

export async function requireAdmin(request: Request): Promise<User> {
  const authorization = request.headers.get('Authorization')
  if (!authorization) throw new Error('נדרשת התחברות.')
  const client = createClient(
    Deno.env.get('SUPABASE_URL')!,
    Deno.env.get('SUPABASE_ANON_KEY')!,
    { global: { headers: { Authorization: authorization } }, auth: { persistSession: false } },
  )
  const { data: { user }, error } = await client.auth.getUser()
  if (error || !user) throw new Error('ההתחברות אינה תקפה.')
  const { data: isAdmin, error: adminError } = await client.rpc('is_admin')
  if (adminError || !isAdmin) throw new Error('המשתמש אינו מורשה להפעיל את הפיילוט.')
  return user
}
