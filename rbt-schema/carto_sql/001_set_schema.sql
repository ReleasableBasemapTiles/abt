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
-- Label points — one rule for every point label layer made from polygons:
--   * one point per feature, on its largest part (LabelPoint). The point used
--     to go on whichever part ST_PointOnSurface picked, or, for ports and
--     cemeteries, one point per part, which styles thinned with the v1.0
--     rank/contained/area_part fields.
--   * area: the feature's Web Mercator area in m², which is its area on
--     screen at any latitude.
--   * min_label: the zoom, to 0.1, at which that area is 32 px across
--     (MinLabel), so a style filter is just zoom >= min_label. Polygon
--     layers carry it too, for fills and outlines drawn from a smaller size
--     (min_label - k: each zoom of k halves the on-screen width).
-- Their PostGIS calls are schema-qualified for the reason given at
-- lifecycle_type below: PostgreSQL 17+ runs function bodies with search_path
-- locked to pg_catalog while it builds a materialized view.
-- -----------------------------------------------------------------------------

BEGIN;
-- Web Mercator area in m². Polygons reaching past Web Mercator's latitude
-- limit (Antarctic ice reaches 90°S) are clipped to it first, since the poles
-- have no Mercator y.
CREATE OR REPLACE FUNCTION public.MercatorArea(g public.geometry)
RETURNS double precision
LANGUAGE SQL IMMUTABLE PARALLEL SAFE
AS $func$
SELECT CASE
    WHEN g IS NULL THEN NULL
    WHEN public.ST_YMax(g) > 85.0511 OR public.ST_YMin(g) < -85.0511
        THEN public.ST_Area(public.ST_Transform(public.ST_Intersection(
                 g, public.ST_MakeEnvelope(-180, -85.0511, 180, 85.0511, 4326)), 3857))
    ELSE public.ST_Area(public.ST_Transform(g, 3857))
END;
$func$;

-- The largest polygon part of a (multi)polygon in EPSG:4326, by Web Mercator
-- area. NULL if it has no polygon part.
CREATE OR REPLACE FUNCTION public.LargestPart(g public.geometry)
RETURNS public.geometry
LANGUAGE SQL IMMUTABLE PARALLEL SAFE
AS $func$
SELECT d.geom
FROM public.ST_Dump(public.ST_CollectionExtract(g, 3)) AS d
ORDER BY public.MercatorArea(d.geom) DESC NULLS LAST
LIMIT 1;
$func$;

-- Where a feature's label goes: a point inside its largest part. A point
-- geometry is returned unchanged.
CREATE OR REPLACE FUNCTION public.LabelPoint(g public.geometry)
RETURNS public.geometry
LANGUAGE SQL IMMUTABLE PARALLEL SAFE
AS $func$
SELECT public.ST_PointOnSurface(COALESCE(public.LargestPart(g), g));
$func$;

-- The zoom at which a feature of this Web Mercator area is 32 px across on
-- 512 px tiles: sqrt(area) / ZRes(z + 1) = 32, where ZRes(z + 1) is the m/px
-- of a 512 px tile at zoom z. A 1 km² feature reaches 32 px at z11.3.
-- It's kept to one decimal, not rounded to a whole zoom, so a style can shift
-- it by a fraction of a zoom: the hand-tuned size curves in the styles fall
-- 4x per zoom like this one but sit between whole zooms (a fill drawn from
-- about 7 px is min_label - 2.27), and a whole-zoom min_label would move a
-- band of features a zoom early or late. Each zoom of offset is 4x the area.
-- 0 for no area (a feature mapped as a point) and for anything that big at
-- z0. There's no upper cap: tiles stop at z13, but styles overzoom them, so
-- a feature that reaches 32 px only at z15 labels from z15.
-- The DROP is for databases built while it returned integer: CREATE OR REPLACE
-- can't change a return type. CASCADE takes the views that call it, which
-- carto rebuilds after this script anyway.
DROP FUNCTION IF EXISTS public.MinLabel(double precision) CASCADE;
CREATE OR REPLACE FUNCTION public.MinLabel(area double precision)
RETURNS real
LANGUAGE SQL IMMUTABLE PARALLEL SAFE
AS $func$
SELECT CASE
    WHEN area IS NULL OR area <= 0 THEN 0
    ELSE round(GREATEST(0, ln(32 * 40075016.6855785 / (512 * sqrt(area))) / ln(2))::numeric, 1)::real
END;
$func$;
COMMIT;


-- -----------------------------------------------------------------------------
-- Lifecycle — one scheme for every line layer that has one (road_line,
-- rail_line, powerline_line, runway_line):
--   * lifecycle_type is the OSM lifecycle state: one of lifecycle_states(), or
--     'intact'. railway=ruins counts as 'abandoned'.
--   * 'proposed' and 'planned' are detected only so the line layers can drop
--     them; they never reach the tiles. Keep them in lifecycle_states().
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
