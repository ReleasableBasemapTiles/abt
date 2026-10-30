-- =============================================================================
-- SCHEMA SETUP
-- Schema:        export
-- =============================================================================


-- -----------------------------------------------------------------------------
-- osm.ZRes — tile resolution in map units per pixel at zoom level z
-- -----------------------------------------------------------------------------

BEGIN;
CREATE OR REPLACE FUNCTION public.ZRes(z integer)
RETURNS float
LANGUAGE SQL IMMUTABLE STRICT PARALLEL SAFE
AS $func$
SELECT (40075016.6855785 / (256 * 2^z));
$func$;
COMMIT;


-- -----------------------------------------------------------------------------
-- Lifecycle — one scheme for every line layer that has one (road_line,
-- rail_line, powerline_line, runway_line):
--   * lifecycle_type is the OSM lifecycle state: one of lifecycle_states(), or
--     'intact'. railway=ruins counts as 'abandoned'.
--   * subclass is what the feature is (primary, rail, line, runway), never a
--     lifecycle word; lifecycle_subject() resolves it.
-- OSM records a lifecycle in three ways, all detected, in this order:
--   1. prefix key only:  abandoned:aeroway=runway (imported under that key,
--                        so it arrives as osm_key)
--   2. lifecycle value:  highway=construction (+ construction=primary)
--   3. prefix tag:       railway=rail + disused:railway=rail
--   4. bare flag:        aeroway=runway + disused=yes. Any value but 'no'
--                        counts (disused=runway is a disused runway). Only the
--                        states whose bare key is a flag; construction=minor
--                        marks road works on a usable road, so construction=*
--                        and proposed=* don't count.
-- Before this, each script had its own rules: roads missed disused=yes and
-- rail missed prefix tags, and runways had no lifecycle at all.
-- -----------------------------------------------------------------------------

BEGIN;
CREATE OR REPLACE FUNCTION public.lifecycle_states()
RETURNS text[]
LANGUAGE SQL IMMUTABLE PARALLEL SAFE
AS $func$
SELECT ARRAY['construction', 'proposed', 'planned', 'disused', 'abandoned',
             'destroyed', 'demolished', 'razed', 'removed'];
$func$;

-- osm_key / osm_value: the imposm mapping key and value (the class and
-- subclass columns); base_key: the feature's own key ('highway', 'railway',
-- 'power', 'aeroway').
--
-- The hstore lookups are written tags OPERATOR(public.->) key, not tags -> key.
-- PostgreSQL 17+ plans CREATE MATERIALIZED VIEW with search_path locked to
-- pg_catalog, pg_temp, and these bodies are inlined at plan time, so a bare ->
-- fails with "operator does not exist: public.hstore -> text" (hstore lives
-- in public; see setup_ubuntu.sh). A SET search_path clause would also fix it
-- but stops PostgreSQL inlining the function, making it a call per row.
CREATE OR REPLACE FUNCTION public.lifecycle_type(osm_key text, osm_value text, tags hstore, base_key text)
RETURNS text
LANGUAGE SQL IMMUTABLE PARALLEL SAFE
AS $func$
SELECT COALESCE(
    CASE WHEN split_part(lower(osm_key), ':', 2) = lower(base_key)
          AND split_part(lower(osm_key), ':', 1) = ANY (public.lifecycle_states())
         THEN split_part(lower(osm_key), ':', 1)
    END,
    CASE WHEN lower(trim(osm_value)) = 'ruins' THEN 'abandoned'
         WHEN lower(trim(osm_value)) = ANY (public.lifecycle_states()) THEN lower(trim(osm_value))
    END,
    (SELECT u.s FROM unnest(public.lifecycle_states()) WITH ORDINALITY AS u(s, o)
     WHERE NULLIF(trim(tags OPERATOR(public.->) (u.s || ':' || base_key)), '') IS NOT NULL
     ORDER BY u.o LIMIT 1),
    (SELECT u.s FROM unnest(ARRAY['disused', 'abandoned', 'destroyed', 'demolished', 'razed', 'removed'])
                     WITH ORDINALITY AS u(s, o)
     WHERE lower(trim(tags OPERATOR(public.->) u.s)) NOT IN ('', 'no')
     ORDER BY u.o LIMIT 1),
    'intact'
);
$func$;

-- What the feature is, whatever its lifecycle: the value of a prefix-only
-- key (abandoned:aeroway=runway -> runway), the type a lifecycle value points
-- at (highway=construction + construction=primary -> primary; railway=disused
-- + disused:railway=rail -> rail), else fallback. Any other value is returned
-- unchanged, so callers keep their own normalization of ordinary values.
CREATE OR REPLACE FUNCTION public.lifecycle_subject(osm_key text, osm_value text, tags hstore,
                                                    base_key text, fallback text)
RETURNS text
LANGUAGE SQL IMMUTABLE PARALLEL SAFE
AS $func$
SELECT CASE
    WHEN split_part(lower(osm_key), ':', 2) = lower(base_key)
     AND split_part(lower(osm_key), ':', 1) = ANY (public.lifecycle_states())
        THEN lower(trim(osm_value))
    WHEN lower(trim(osm_value)) = 'ruins' OR lower(trim(osm_value)) = ANY (public.lifecycle_states())
        THEN COALESCE(
            NULLIF(NULLIF(lower(trim(tags OPERATOR(public.->) lower(trim(osm_value)))), ''), 'yes'),
            NULLIF(NULLIF(lower(trim(tags OPERATOR(public.->) (lower(trim(osm_value)) || ':' || base_key))), ''), 'yes'),
            fallback
        )
    ELSE osm_value
END;
$func$;
COMMIT;


-- -----------------------------------------------------------------------------
-- SCHEMA
-- -----------------------------------------------------------------------------

BEGIN;
DROP SCHEMA IF EXISTS export CASCADE;
CREATE SCHEMA IF NOT EXISTS export;
COMMIT;
