create or replace view public.permit_results
with (security_invoker = true) as
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
  end as display_status
from public.run_applications ra
join public.applications a on a.id = ra.application_id
join public.cities c on c.id = a.city_id;

grant select on public.permit_results to authenticated;
