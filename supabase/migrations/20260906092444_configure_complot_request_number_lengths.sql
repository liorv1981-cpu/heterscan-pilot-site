-- Complot identifiers are source-owned strings. Keep them exactly as returned;
-- never pad them with zeroes. Haifa uses ten digits, while Petah Tikva and
-- Rishon LeZion use eight digits.
with expected(city_id, request_number_length) as (
  values
    ('4000', 10),
    ('7900', 8),
    ('8300', 8)
)
update public.cities as city
set adapter_config = coalesce(city.adapter_config, '{}'::jsonb)
  || jsonb_build_object('request_number_length', expected.request_number_length)
from expected
where city.id = expected.city_id
  and city.adapter_name = 'complot';

do $$
declare
  invalid_cities text;
begin
  select string_agg(expected.city_id, ', ' order by expected.city_id)
  into invalid_cities
  from (
    values
      ('4000', 10),
      ('7900', 8),
      ('8300', 8)
  ) as expected(city_id, request_number_length)
  left join public.cities as city
    on city.id = expected.city_id
   and city.adapter_name = 'complot'
   and (city.adapter_config->>'request_number_length')::integer = expected.request_number_length
  where city.id is null;

  if invalid_cities is not null then
    raise exception 'Complot request-number configuration failed for cities: %', invalid_cities;
  end if;
end;
$$;
