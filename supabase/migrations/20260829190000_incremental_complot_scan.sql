create index if not exists applications_city_submission_number_idx
on public.applications (city_id, submission_date, application_number)
where application_number is not null and submission_date is not null;

create or replace function public.enqueue_run_units(p_run_id uuid, p_units jsonb)
returns integer
language plpgsql security definer set search_path = '' as $$
declare
  next_sequence integer;
  inserted_count integer;
begin
  if jsonb_typeof(p_units) is distinct from 'array' then
    raise exception 'p_units must be a JSON array';
  end if;

  -- Lock the run row so sequence assignment and units_total stay consistent.
  perform 1 from public.runs where id = p_run_id for update;
  if not found then
    raise exception 'Run % not found', p_run_id;
  end if;

  select coalesce(max(sequence), 0)
  into next_sequence
  from public.run_units
  where run_id = p_run_id;

  with input as (
    select
      value->>'unit_key' as unit_key,
      coalesce(value->'unit_payload', '{}'::jsonb) as unit_payload,
      ordinality::integer as position
    from jsonb_array_elements(p_units) with ordinality
    where nullif(value->>'unit_key', '') is not null
  )
  insert into public.run_units (run_id, sequence, unit_key, unit_payload)
  select p_run_id, next_sequence + position, unit_key, unit_payload
  from input
  on conflict do nothing;

  get diagnostics inserted_count = row_count;
  update public.runs
  set units_total = units_total + inserted_count
  where id = p_run_id;
  return inserted_count;
end;
$$;

revoke all on function public.enqueue_run_units(uuid, jsonb) from public, anon, authenticated;
grant execute on function public.enqueue_run_units(uuid, jsonb) to service_role;

create or replace function public.finish_run_units(p_updates jsonb)
returns integer
language plpgsql security definer set search_path = '' as $$
declare updated_count integer;
begin
  if jsonb_typeof(p_updates) is distinct from 'array' then
    raise exception 'p_updates must be a JSON array';
  end if;

  with updates as (
    select
      (value->>'id')::uuid as id,
      value->>'status' as status,
      greatest(0, coalesce((value->>'result_count')::integer, 0)) as result_count,
      left(value->>'error_message', 2000) as error_message
    from jsonb_array_elements(p_updates)
  )
  update public.run_units unit
  set
    status = case updates.status
      when 'completed' then 'completed'
      when 'failed' then 'failed'
      when 'requires_review' then 'requires_review'
      else unit.status
    end,
    result_count = updates.result_count,
    error_message = updates.error_message,
    completed_at = now()
  from updates
  where unit.id = updates.id
    and unit.status = 'processing'
    and updates.status is not null;

  get diagnostics updated_count = row_count;
  return updated_count;
end;
$$;

revoke all on function public.finish_run_units(jsonb) from public, anon, authenticated;
grant execute on function public.finish_run_units(jsonb) to service_role;
