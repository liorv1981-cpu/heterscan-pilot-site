-- Add verification meaning without rewriting immutable historical snapshots.
alter table public.runs
  add column coverage_verification text not null default 'not_verified'
  check (coverage_verification in (
    'not_verified', 'zero_not_verified', 'partial', 'verified_zero', 'verified_nonzero'
  ));

alter table public.applications
  add column permit_verification text not null default 'unknown'
  check (permit_verification in ('unknown', 'verified_issued', 'verified_not_issued'));

-- The ordinary public search displayed Eilat 20260001 on 2026-10-01, while
-- the direct detail route returned an unavailable-information page.
update public.cities
set adapter_config = adapter_config ||
  '{"public_search_url":"https://eilat.complot.co.il/iturbakashot/"}'::jsonb
where id = '2600' and adapter_name = 'complot';

-- The pre-existing views are security invoker views. Append columns so clients
-- using their previous column order keep working.
create or replace view public.run_overview with (security_invoker = true) as
select r.id, r.city_id, r.requested_by, r.date_from, r.date_to, r.status,
  r.configuration_snapshot, r.units_total, r.units_completed,
  r.applications_found, r.permits_found, r.heartbeat_at, r.lock_owner,
  r.lock_expires_at, r.workflow_reference, r.report_path, r.error_message,
  r.created_at, r.started_at, r.completed_at, c.name_he as city_name,
  case when r.applications_found = 0 and r.coverage_verification = 'not_verified'
    then 'zero_not_verified' else r.coverage_verification end as coverage_verification
from public.runs r join public.cities c on c.id = r.city_id;

create or replace view public.permit_results with (security_invoker = true) as
select a.id, ra.run_id, c.name_he as city_name, a.address, a.application_number,
  a.permit_number, a.permit_issue_date, a.permit_status_original, a.source_url,
  a.permit_confidence, a.is_permit_issued, a.is_approved,
  case when not coalesce(a.details_available, true) then 'פרטים חלקיים — נדרשת בדיקה'
       when a.is_permit_issued then coalesce(nullif(a.permit_status_original, ''), 'היתר הופק')
       when a.is_approved then coalesce(nullif(a.permit_status_original, ''), 'אושר — מצב היתר לא אומת')
       else coalesce(nullif(a.permit_status_original, ''), 'סטטוס לא אומת') end as display_status,
  a.submission_date, coalesce(a.details_available, true) as details_available,
  case when a.is_permit_issued then 'verified_issued'
       else coalesce(a.permit_verification, 'unknown') end as permit_verification
from public.run_applications ra join public.runs r on r.id = ra.run_id
cross join lateral pg_catalog.jsonb_populate_record(null::public.applications, ra.result_snapshot) a
join public.cities c on c.id = a.city_id
where a.submission_date >= r.date_from and a.submission_date <= r.date_to;
