-- Add only Complot cities that passed an end-to-end public-source probe:
-- request-number discovery, detail-page parsing, and submission-date extraction.
insert into public.cities (
  id,
  name_he,
  adapter_name,
  adapter_config,
  is_active,
  display_order
)
values
  ('8400', 'רחובות', 'complot', '{"site_id":"22","locality_code":"8400","request_number_length":8}'::jsonb, true, 6),
  ('6600', 'חולון', 'complot', '{"site_id":"34","locality_code":"6600","request_number_length":8}'::jsonb, true, 7),
  ('6200', 'בת ים', 'complot', '{"site_id":"81","locality_code":"6200","request_number_length":8}'::jsonb, true, 8),
  ('6100', 'בני ברק', 'complot', '{"site_id":"75","locality_code":"6100","request_number_length":9}'::jsonb, true, 9),
  ('8600', 'רמת גן', 'complot', '{"site_id":"3","locality_code":"8600","request_number_length":9}'::jsonb, true, 10),
  ('6900', 'כפר סבא', 'complot', '{"site_id":"13","locality_code":"6900","request_number_length":8}'::jsonb, true, 11),
  ('6400', 'הרצליה', 'complot', '{"site_id":"121","locality_code":"6400","request_number_length":8}'::jsonb, true, 12),
  ('2650', 'רמת השרון', 'complot', '{"site_id":"118","locality_code":"2650","request_number_length":8}'::jsonb, true, 13),
  ('1200', 'מודיעין-מכבים-רעות', 'complot', '{"site_id":"82","locality_code":"1200","request_number_length":8}'::jsonb, true, 14),
  ('2660', 'יבנה', 'complot', '{"site_id":"87","locality_code":"2660","request_number_length":8}'::jsonb, true, 15),
  ('2610', 'בית שמש', 'complot', '{"site_id":"93","locality_code":"2610","request_number_length":8}'::jsonb, true, 16),
  ('6800', 'קרית אתא', 'complot', '{"site_id":"32","locality_code":"6800","request_number_length":8}'::jsonb, true, 17),
  ('7100', 'אשקלון', 'complot', '{"site_id":"95","locality_code":"7100","request_number_length":8}'::jsonb, true, 18),
  ('9000', 'באר שבע', 'complot', '{"site_id":"105","locality_code":"9000","request_number_length":8}'::jsonb, true, 19),
  ('2630', 'קרית גת', 'complot', '{"site_id":"46","locality_code":"2630","request_number_length":8}'::jsonb, true, 20),
  ('2600', 'אילת', 'complot', '{"site_id":"56","locality_code":"2600","request_number_length":8}'::jsonb, true, 21),
  ('1161', 'רהט', 'complot', '{"site_id":"97","locality_code":"1161","request_number_length":8}'::jsonb, true, 22)
on conflict (id) do update
set
  name_he = excluded.name_he,
  adapter_name = excluded.adapter_name,
  adapter_config = excluded.adapter_config,
  is_active = excluded.is_active,
  display_order = excluded.display_order;

