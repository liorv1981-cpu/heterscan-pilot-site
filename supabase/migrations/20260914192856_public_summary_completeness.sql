alter table public.applications add column if not exists details_available boolean not null default true;
-- Public search entry verified from the municipality's archive page.
update public.cities set adapter_config = adapter_config ||
  '{"public_search_url":"https://rechovot.complot.co.il/iturbakashot/"}'::jsonb
where id = '8400';
create or replace view public.permit_results with (security_invoker = true) as
select a.id, ra.run_id, c.name_he as city_name, a.address, a.application_number,
 a.permit_number, a.permit_issue_date, a.permit_status_original, a.source_url, a.permit_confidence,
 a.is_permit_issued, a.is_approved,
 case when not coalesce(a.details_available,true) then 'פרטים חלקיים — נדרשת בדיקה'
      when a.is_permit_issued then coalesce(nullif(a.permit_status_original,''),'היתר הופק')
      when a.is_approved then 'אושר — טרם הופק היתר' else 'טרם אושר' end as display_status,
 a.submission_date, coalesce(a.details_available,true) as details_available
from public.run_applications ra join public.runs r on r.id=ra.run_id
cross join lateral pg_catalog.jsonb_populate_record(null::public.applications,ra.result_snapshot) a
join public.cities c on c.id=a.city_id
where a.submission_date>=r.date_from and a.submission_date<=r.date_to;
