--
-- PostgreSQL database dump
--

\restrict LVIsJoFRoQDB8qBgcPPpfmii5GHPVQYDbkUHleh8i5nvrlS4Vvk8t0ha7ISgdCp

-- Dumped from database version 16.14 (Ubuntu 16.14-0ubuntu0.24.04.1)
-- Dumped by pg_dump version 16.14 (Ubuntu 16.14-0ubuntu0.24.04.1)

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

--
-- Data for Name: oil_spills; Type: TABLE DATA; Schema: public; Owner: oil_spill
--

INSERT INTO public.oil_spills (id, detected_at, centroid_latitude, centroid_longitude, area, confidence, created_at, geometry_geojson, crs, region_count) VALUES ('8fcf55a3-51d1-4cab-9bfc-7ea9c4a20fc2', '2026-09-05 15:42:00+05:30', 38.33, -9.66, 245000, 0.91, '2026-09-12 04:56:31.423273+05:30', '{"type": "Polygon", "coordinates": [[[-9.76, 38.23], [-9.56, 38.23], [-9.56, 38.43], [-9.76, 38.43], [-9.76, 38.23]]]}', 'EPSG:4326', 1);
INSERT INTO public.oil_spills (id, detected_at, centroid_latitude, centroid_longitude, area, confidence, created_at, geometry_geojson, crs, region_count) VALUES ('73dbf059-734f-4767-b07b-64846cab983d', '2026-09-05 15:14:01+05:30', 38.5, -9.5, 850000, 0.93, '2026-09-12 05:02:14.622149+05:30', '{"type": "Polygon", "coordinates": [[[-9.6, 38.4], [-9.4, 38.4], [-9.4, 38.6], [-9.6, 38.6], [-9.6, 38.4]]]}', 'EPSG:4326', 1);
INSERT INTO public.oil_spills (id, detected_at, centroid_latitude, centroid_longitude, area, confidence, created_at, geometry_geojson, crs, region_count) VALUES ('d7e0491e-569b-4e19-bf0d-6846bb01f393', '2026-09-05 15:14:01+05:30', 38.5, -9.5, 850000, 0.93, '2026-09-12 05:05:12.914776+05:30', '{"type": "Polygon", "coordinates": [[[-9.6, 38.4], [-9.4, 38.4], [-9.4, 38.6], [-9.6, 38.6], [-9.6, 38.4]]]}', 'EPSG:4326', 1);


--
-- Data for Name: attribution_results; Type: TABLE DATA; Schema: public; Owner: oil_spill
--

INSERT INTO public.attribution_results (id, spill_id, mmsi, distance_km, time_difference_minutes, score, rank, created_at, evidence) VALUES (137, '8fcf55a3-51d1-4cab-9bfc-7ea9c4a20fc2', 205221000, 0.32, 4, 0.95, 1, '2026-09-12 04:56:31.423273+05:30', '["Vessel passed within 0.32 km of the detected spill", "Positioned 4 minutes before detection with a steady heading", "High observation density consistent with slow tanker traffic"]');
INSERT INTO public.attribution_results (id, spill_id, mmsi, distance_km, time_difference_minutes, score, rank, created_at, evidence) VALUES (138, '8fcf55a3-51d1-4cab-9bfc-7ea9c4a20fc2', 244123456, 4.75, 31, 0.57, 2, '2026-09-12 04:56:31.423273+05:30', '["Vessel passed within 4.75 km of the detected spill", "Present inside the 10 km search radius in the last 60 min"]');
INSERT INTO public.attribution_results (id, spill_id, mmsi, distance_km, time_difference_minutes, score, rank, created_at, evidence) VALUES (139, '73dbf059-734f-4767-b07b-64846cab983d', 111000001, 0.48, 6, 0.93, 1, '2026-09-12 05:02:14.622149+05:30', '["Vessel passed within 0.48 km of the detected spill", "Positioned 6 minutes before detection, heading directly through the spill region at 13 knots", "Consistent course (70 deg) across 4 AIS observations"]');
INSERT INTO public.attribution_results (id, spill_id, mmsi, distance_km, time_difference_minutes, score, rank, created_at, evidence) VALUES (140, '73dbf059-734f-4767-b07b-64846cab983d', 111000008, 2.1, 22, 0.64, 2, '2026-09-12 05:02:14.622149+05:30', '["Vessel passed within 2.10 km of the detected spill", "Present inside the 10 km search radius in the last 60 min"]');
INSERT INTO public.attribution_results (id, spill_id, mmsi, distance_km, time_difference_minutes, score, rank, created_at, evidence) VALUES (141, 'd7e0491e-569b-4e19-bf0d-6846bb01f393', 111000001, 0.48, 6, 0.93, 1, '2026-09-12 05:05:12.914776+05:30', '["Vessel passed within 0.48 km of the detected spill", "Positioned 6 minutes before detection, heading directly through the spill region at 13 knots", "Consistent course (70 deg) across 4 AIS observations"]');
INSERT INTO public.attribution_results (id, spill_id, mmsi, distance_km, time_difference_minutes, score, rank, created_at, evidence) VALUES (142, 'd7e0491e-569b-4e19-bf0d-6846bb01f393', 111000008, 2.1, 22, 0.64, 2, '2026-09-12 05:05:12.914776+05:30', '["Vessel passed within 2.10 km of the detected spill", "Present inside the 10 km search radius in the last 60 min"]');


--
-- Name: attribution_results_id_seq; Type: SEQUENCE SET; Schema: public; Owner: oil_spill
--

SELECT pg_catalog.setval('public.attribution_results_id_seq', 142, true);


--
-- PostgreSQL database dump complete
--

\unrestrict LVIsJoFRoQDB8qBgcPPpfmii5GHPVQYDbkUHleh8i5nvrlS4Vvk8t0ha7ISgdCp

