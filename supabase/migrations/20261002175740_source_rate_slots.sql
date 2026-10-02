-- A service-only origin gate keeps cooldowns and one in-flight request per host
-- across worker restarts and concurrent runs. No response data is stored.
create table if not exists public.source_rate_slots (
  origin text primary key,
  next_request_at timestamptz not null default now(),
  blocked_until timestamptz not null default now(),
  lease_token uuid,
  lease_until timestamptz,
  updated_at timestamptz not null default now()
);

alter table public.source_rate_slots enable row level security;
revoke all on public.source_rate_slots from public, anon, authenticated;
grant select, insert, update on public.source_rate_slots to service_role;

create or replace function public.acquire_source_slot(p_origin text, p_interval_seconds double precision)
returns jsonb language plpgsql security invoker set search_path = '' as $$
declare
  slot public.source_rate_slots%rowtype;
  delay_seconds double precision;
  new_token uuid;
begin
  if p_origin !~ '^[a-z0-9.-]{1,253}$' or p_interval_seconds <= 0 or p_interval_seconds > 60 then
    raise exception 'Invalid source slot arguments';
  end if;
  insert into public.source_rate_slots(origin) values (p_origin) on conflict do nothing;
  select * into slot from public.source_rate_slots where origin = p_origin for update;
  if slot.blocked_until > now() then
    return jsonb_build_object('acquired', false, 'blocked', true,
                              'retry_after_seconds', extract(epoch from slot.blocked_until - now()));
  end if;
  delay_seconds := greatest(
    0,
    extract(epoch from slot.next_request_at - now()),
    extract(epoch from coalesce(slot.lease_until, now()) - now())
  );
  if delay_seconds > 0 then
    return jsonb_build_object('acquired', false, 'blocked', false, 'retry_after_seconds', delay_seconds);
  end if;
  new_token := gen_random_uuid();
  update public.source_rate_slots
  set next_request_at = now() + (interval '1 second' * p_interval_seconds),
      lease_token = new_token, lease_until = now() + interval '90 seconds', updated_at = now()
  where origin = p_origin;
  return jsonb_build_object('acquired', true, 'token', new_token);
end;
$$;

create or replace function public.release_source_slot(p_origin text, p_token uuid)
returns void language plpgsql security invoker set search_path = '' as $$
begin
  update public.source_rate_slots
  set lease_token = null, lease_until = null, updated_at = now()
  where origin = p_origin and lease_token = p_token;
end;
$$;

create or replace function public.penalize_source(p_origin text, p_cooldown_seconds double precision)
returns void language plpgsql security invoker set search_path = '' as $$
begin
  if p_cooldown_seconds < 0 or p_cooldown_seconds > 315360000 then
    raise exception 'Invalid source cooldown';
  end if;
  insert into public.source_rate_slots(origin, blocked_until)
  values (p_origin, now() + (interval '1 second' * p_cooldown_seconds))
  on conflict (origin) do update
  set blocked_until = greatest(public.source_rate_slots.blocked_until, excluded.blocked_until),
      updated_at = now();
end;
$$;

revoke all on function public.acquire_source_slot(text, double precision) from public, anon, authenticated;
revoke all on function public.release_source_slot(text, uuid) from public, anon, authenticated;
revoke all on function public.penalize_source(text, double precision) from public, anon, authenticated;
grant execute on function public.acquire_source_slot(text, double precision) to service_role;
grant execute on function public.release_source_slot(text, uuid) to service_role;
grant execute on function public.penalize_source(text, double precision) to service_role;
