-- Keep scan history independent of later updates to the same application.
alter table public.run_applications
  add column if not exists result_snapshot jsonb,
  add column if not exists result_snapshot_at timestamptz,
  add column if not exists result_snapshot_source text;

create or replace function public.capture_run_result_snapshot()
returns trigger
language plpgsql
security invoker
set search_path = ''
as $$
begin
  if new.result_snapshot is null then
    select pg_catalog.to_jsonb(a) into new.result_snapshot
    from public.applications a where a.id = new.application_id;
    if new.result_snapshot is null then
      raise exception 'Application must exist before a run result can be captured';
    end if;
    new.result_snapshot_at := pg_catalog.now();
    new.result_snapshot_source := 'captured';
  end if;
  return new;
end;
$$;
revoke all on function public.capture_run_result_snapshot() from public, anon, authenticated;
grant execute on function public.capture_run_result_snapshot() to service_role;

create or replace trigger capture_run_result_snapshot
before insert on public.run_applications
for each row execute function public.capture_run_result_snapshot();

-- Preserve the currently visible values until legacy published reports are recovered.
-- Explicit provenance prevents claiming these are the original historical observations.
update public.run_applications ra
set result_snapshot = pg_catalog.to_jsonb(a),
    result_snapshot_at = pg_catalog.now(),
    result_snapshot_source = 'legacy_current'
from public.applications a
where a.id = ra.application_id and ra.result_snapshot is null;

alter table public.run_applications alter column result_snapshot set not null;

create or replace view public.permit_results with (security_invoker = true) as
select
  a.id,
  ra.run_id,
  c.name_he as city_name,
  a.address,
  a.application_number,
  a.permit_number,
  a.permit_issue_date,
  a.permit_status_original,
  a.source_url,
  a.permit_confidence,
  a.is_permit_issued,
  a.is_approved,
  case
    when a.is_permit_issued then coalesce(nullif(a.permit_status_original, ''), 'היתר הופק')
    when a.is_approved then 'אושר — טרם הופק היתר'
    else 'טרם אושר'
  end as display_status,
  a.submission_date
from public.run_applications ra
join public.runs r on r.id = ra.run_id
cross join lateral pg_catalog.jsonb_populate_record(null::public.applications, ra.result_snapshot) a
join public.cities c on c.id = a.city_id
where a.submission_date >= r.date_from and a.submission_date <= r.date_to;

create or replace function public.get_run_progress(p_run_id uuid)
returns table (
  units_completed integer, applications_found integer, permits_found integer,
  units_failed integer, units_requires_review integer
)
language sql stable security invoker set search_path = '' as $$
select
  (select count(*)::integer from public.run_units where run_id = p_run_id
    and status in ('completed','failed','requires_review')),
  (select count(*)::integer from public.permit_results where run_id = p_run_id),
  (select count(*)::integer from public.permit_results where run_id = p_run_id and is_permit_issued),
  (select count(*)::integer from public.run_units where run_id = p_run_id and status = 'failed'),
  (select count(*)::integer from public.run_units where run_id = p_run_id and status = 'requires_review');
$$;
revoke all on function public.get_run_progress(uuid) from public, anon, authenticated;
grant execute on function public.get_run_progress(uuid) to service_role;

comment on column public.run_applications.result_snapshot is
'Normalized per-run application data. captured = first observation; legacy_current = migration-time fallback; published_report = reconstructed visible fields from the preserved published XLSX.';

-- Service-only, atomic restoration from an already published workbook. Never
-- overwrite observations captured by the new trigger or modify an active scan.
create or replace function public.recover_published_run_snapshots(
  p_run_id uuid, p_rows jsonb, p_report_path text,
  p_applications integer, p_permits integer
) returns integer
language plpgsql security invoker set search_path = '' as $$
declare
  original public.runs;
  recovered integer;
  actual_applications integer;
  actual_permits integer;
begin
  select * into original from public.runs where id = p_run_id for update;
  if not found or original.status in ('created','dispatching','running','safely_stopped') then
    raise exception 'Only terminal scans can be recovered';
  end if;
  if pg_catalog.jsonb_typeof(p_rows) <> 'array'
     or p_report_path is distinct from original.report_path then
    raise exception 'Invalid recovery input or report pointer changed';
  end if;
  update public.run_applications ra
  set result_snapshot = x.snapshot,
      result_snapshot_at = pg_catalog.now(),
      result_snapshot_source = 'published_report'
  from pg_catalog.jsonb_to_recordset(p_rows) as x(application_id uuid, snapshot jsonb)
  where ra.run_id = p_run_id and ra.application_id = x.application_id
    and ra.result_snapshot_source = 'legacy_current'
    and x.snapshot->>'id' = ra.application_id::text
    and x.snapshot->>'city_id' = original.city_id;
  get diagnostics recovered = row_count;
  if recovered <> pg_catalog.jsonb_array_length(p_rows) then
    raise exception 'Recovery rows changed or do not belong to this scan';
  end if;
  select count(*)::integer, count(*) filter (where is_permit_issued)::integer
    into actual_applications, actual_permits
  from public.permit_results where run_id = p_run_id;
  if actual_applications <> p_applications or actual_permits <> p_permits then
    raise exception 'Recovered results do not reconcile with published workbook';
  end if;
  update public.runs set applications_found = actual_applications, permits_found = actual_permits
  where id = p_run_id;
  insert into public.run_logs(run_id,level,event,context)
  values (p_run_id,'info','historical_snapshot_recovered',pg_catalog.jsonb_build_object(
    'report_path',p_report_path,'recovered_rows',recovered,
    'previous_applications',original.applications_found,'previous_permits',original.permits_found,
    'applications',actual_applications,'permits',actual_permits));
  return recovered;
end;
$$;
revoke all on function public.recover_published_run_snapshots(uuid,jsonb,text,integer,integer) from public,anon,authenticated;
grant execute on function public.recover_published_run_snapshots(uuid,jsonb,text,integer,integer) to service_role;
