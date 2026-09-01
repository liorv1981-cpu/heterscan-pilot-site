create or replace function public.claim_run(
  p_run_id uuid,
  p_worker_id text,
  p_ttl_minutes integer default 10
)
returns boolean
language plpgsql security definer set search_path = '' as $$
declare claimed boolean;
begin
  update public.runs set
    lock_owner = p_worker_id,
    lock_expires_at = now() + make_interval(mins => greatest(1, least(p_ttl_minutes, 30))),
    heartbeat_at = now(),
    status = case when status in ('created', 'dispatching', 'safely_stopped') then 'running' else status end,
    started_at = coalesce(started_at, now())
  where id = p_run_id
    and status in ('created', 'dispatching', 'running', 'safely_stopped')
    and (lock_expires_at is null or lock_expires_at < now() or lock_owner = p_worker_id)
  returning true into claimed;

  if coalesce(claimed, false) then
    update public.run_units
    set status = 'pending', claimed_by = null, claimed_at = null
    where run_id = p_run_id
      and status = 'processing'
      and claimed_by is distinct from p_worker_id;
  end if;

  return coalesce(claimed, false);
end;
$$;

revoke all on function public.claim_run(uuid, text, integer) from public, anon, authenticated;
grant execute on function public.claim_run(uuid, text, integer) to service_role;
