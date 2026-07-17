-- =============================================================================
-- LAYER: Sports and Recreation
-- Schema:        export
-- Sources:       osm.osm_builtup_area
--                osm.osm_park_polygon
-- =============================================================================


-- -----------------------------------------------------------------------------
-- export.stadium_polygon — stadium and sports centre polygons
-- -----------------------------------------------------------------------------

BEGIN;
DROP MATERIALIZED VIEW IF EXISTS export.stadium_polygon CASCADE;
CREATE MATERIALIZED VIEW export.stadium_polygon AS
SELECT
    osm_id,
    NULLIF(name, '')                                                    AS name,
    NULLIF(name_en, '')                                                 AS name_en,
    class,
    subclass,
    ST_Area(ST_Transform(geometry, 3857))::real                         AS area,
    geometry
FROM osm.osm_builtup_area
WHERE subclass IN ('sports_centre','stadium');

CREATE INDEX idx_stadium_surface_geometry ON export.stadium_polygon USING gist(geometry);
COMMIT;


-- -----------------------------------------------------------------------------
-- export.stadium_label — label points for stadiums and sports centres
-- -----------------------------------------------------------------------------

BEGIN;
DROP MATERIALIZED VIEW IF EXISTS export.stadium_label CASCADE;
CREATE MATERIALIZED VIEW export.stadium_label AS
SELECT
    osm_id,
    name,
    name_en,
    class,
    subclass,
    ST_Area(ST_Transform(geometry, 3857))::real                         AS area,
    ST_PointOnSurface(geometry)::geometry(Point, 4326)                  AS geometry
FROM export.stadium_polygon;

CREATE INDEX idx_stadium_labels_geometry ON export.stadium_label USING gist(geometry);
COMMIT;


-- -----------------------------------------------------------------------------
-- export.sports_ground — sports pitch polygons
-- -----------------------------------------------------------------------------

BEGIN;
DROP MATERIALIZED VIEW IF EXISTS export.sports_ground CASCADE;
CREATE MATERIALIZED VIEW export.sports_ground AS
SELECT
    osm_id,
    NULLIF(name, '')                                                    AS name,
    NULLIF(name_en, '')                                                 AS name_en,
    NULLIF(landuse, '')                                                 AS landuse,
    NULLIF(surface, '')                                                 AS surface,
    NULLIF(ownership, '')                                               AS ownership,
    NULLIF(owner, '')                                                   AS owner,
    NULLIF(operator, '')                                                AS operator,
    NULLIF(access, '')                                                  AS access,
    class,
    subclass,
    ST_Area(ST_Transform(geometry, 3857))::real                         AS area,
    tags,
    geometry
FROM osm.osm_park_polygon
WHERE subclass = 'pitch'

UNION ALL

SELECT
    osm_id,
    NULLIF(name, '')                                                    AS name,
    NULLIF(name_en, '')                                                 AS name_en,
    NULL::text                                                          AS landuse,
    NULLIF(tags -> 'surface', '')                                       AS surface,
    NULLIF(tags -> 'ownership', '')                                     AS ownership,
    NULLIF(tags -> 'owner', '')                                         AS owner,
    NULLIF(tags -> 'operator', '')                                      AS operator,
    NULLIF(access, '')                                                  AS access,
    class,
    subclass,
    ST_Area(ST_Transform(geometry, 3857))::real                         AS area,
    tags,
    geometry
FROM osm.osm_landuse_polygon
WHERE subclass = 'pitch';

CREATE INDEX idx_sports_ground_geometry ON export.sports_ground USING gist(geometry);
COMMIT;


-- -----------------------------------------------------------------------------
-- export.golf_course — golf course polygons
-- -----------------------------------------------------------------------------

BEGIN;
DROP MATERIALIZED VIEW IF EXISTS export.golf_course CASCADE;
CREATE MATERIALIZED VIEW export.golf_course AS
SELECT
    osm_id,
    NULLIF(name, '')                                                    AS name,
    NULLIF(name_en, '')                                                 AS name_en,
    NULLIF(landuse, '')                                                 AS landuse,
    NULLIF(surface, '')                                                 AS surface,
    NULLIF(ownership, '')                                               AS ownership,
    NULLIF(owner, '')                                                   AS owner,
    NULLIF(operator, '')                                                AS operator,
    NULLIF(access, '')                                                  AS access,
    class,
    subclass,
    ST_Area(ST_Transform(geometry, 3857))::real                         AS area,
    tags,
    geometry
FROM osm.osm_park_polygon
WHERE subclass = 'golf_course'

UNION ALL

SELECT
    osm_id,
    NULLIF(name, '')                                                    AS name,
    NULLIF(name_en, '')                                                 AS name_en,
    NULL::text                                                          AS landuse,
    NULL::text                                                          AS surface,
    NULL::text                                                          AS ownership,
    NULL::text                                                          AS owner,
    NULL::text                                                          AS operator,
    NULLIF(access, '')                                                  AS access,
    class,
    subclass,
    ST_Area(ST_Transform(geometry, 3857))::real                         AS area,
    tags,
    geometry
FROM osm.osm_park_polygon
WHERE subclass IN ('bunker', 'green', 'fairway');

CREATE INDEX idx_golf_course_geometry ON export.golf_course USING gist(geometry);
COMMIT;
