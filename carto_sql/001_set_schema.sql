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
-- SCHEMA
-- -----------------------------------------------------------------------------

BEGIN;
DROP SCHEMA IF EXISTS export CASCADE;
CREATE SCHEMA IF NOT EXISTS export;
COMMIT;
