-- =============================================================================
-- LAYER: Park
-- Schema:        export
-- Sources:       osm.osm_park_polygon
--                osm.osm_landuse_polygon
-- =============================================================================


-- -----------------------------------------------------------------------------
-- export.park_polygon — protected areas and recreational park polygons
-- -----------------------------------------------------------------------------

BEGIN;
DROP MATERIALIZED VIEW IF EXISTS export.park_polygon CASCADE;
CREATE MATERIALIZED VIEW export.park_polygon AS
SELECT
    osm_id,
    NULLIF(access, '')                                                  AS access,
    NULLIF(class, '')                                                   AS class,
    COALESCE(
        CASE WHEN leisure IN ('park','nature_reserve','golf_course','dog_park','recreation_ground','garden') THEN leisure END,
        NULLIF(subclass, '')
    )                                                                   AS subclass,
    NULLIF(iucn_level, '')                                              AS iucn_level,
    COALESCE(NULLIF(name_en, ''), NULLIF(name, ''))                     AS name,
    NULLIF(protect_class, '')                                           AS protect_class,
    ST_Area(ST_Transform(geometry, 3857))::real                         AS area,
    MinLabel(ST_Area(ST_Transform(geometry, 3857)))                     AS min_label,
    geometry
FROM osm.osm_park_polygon
WHERE subclass IN (
    'District', 'Regional', 'aboriginal_lands', 'bunker', 'city_park',
    'community', 'county_park', 'dog_park', 'fairway', 'golf_course', 'green',
    'national_park', 'natural_area', 'nature_reserve',
    'neighbourhood', 'park', 'pitch', 'private_park',
    'protected_area', 'recreation_ground', 'regional',
    'special', 'state_beach', 'state_historic_park', 'state_park'
)

UNION ALL

-- leisure=pitch imports to osm_landuse_polygon, not osm_park_polygon
SELECT
    osm_id,
    NULLIF(access, '')                                                  AS access,
    NULLIF(class, '')                                                   AS class,
    NULLIF(subclass, '')                                                AS subclass,
    NULL::text                                                          AS iucn_level,
    COALESCE(NULLIF(name_en, ''), NULLIF(name, ''))                     AS name,
    NULL::text                                                          AS protect_class,
    ST_Area(ST_Transform(geometry, 3857))::real                         AS area,
    MinLabel(ST_Area(ST_Transform(geometry, 3857)))                     AS min_label,
    geometry
FROM osm.osm_landuse_polygon
WHERE subclass = 'pitch';

CREATE INDEX idx_park_geometry      ON export.park_polygon USING gist(geometry);
CREATE INDEX idx_park_osm_id        ON export.park_polygon USING btree(osm_id);
CREATE INDEX idx_park_class         ON export.park_polygon USING btree(class);
CREATE INDEX idx_park_subclass      ON export.park_polygon USING btree(subclass);
CREATE INDEX idx_park_area          ON export.park_polygon USING btree(area);
CREATE INDEX idx_park_iucn_level    ON export.park_polygon USING btree(iucn_level) WHERE iucn_level IS NOT NULL;
CREATE INDEX idx_park_protect_class ON export.park_polygon USING btree(protect_class) WHERE protect_class IS NOT NULL;
CREATE INDEX idx_park_name          ON export.park_polygon USING btree(name) WHERE name IS NOT NULL;
COMMIT;


-- -----------------------------------------------------------------------------
-- export.park_label — label points for named parks, spaced apart on screen
-- (see "Label points" in 001_set_schema.sql). Styles used to label
-- park_polygon itself, which repeats the name on every part and in every tile
-- the park crosses.
--
-- Same-name parks that touch or nearly touch are one group: a reserve is
-- often mapped as several adjacent areas (the sections of Mauna Kea Ice Age
-- Natural Area Reserve), and each drew its own name. ST_ClusterDBSCAN with
-- minpoints 1 groups a park with every same-name park within eps, and eps
-- is in degrees: 0.001° is about 110 m, or less east-west away from the
-- equator. area is the group's total.
--
-- The group's largest part is labelled from the group's min_label, as before.
-- One label per group was too sparse for parks made of many separate blocks
-- (Manistee National Forest, Sterling Forest State Park): zoomed in on one
-- block, the only label could be 10 km away. So every part big enough to be
-- labelled itself also gets a point, from the zoom at which it's at least
-- spacing_px from every larger part's point in the group. Measuring against
-- every larger part, whether or not its point shows yet, means no two points
-- of a group are ever drawn closer than spacing_px; a point can show later
-- than strictly needed when the larger one near it isn't showing yet.
-- Labelling each part from its own size alone would bring the repetition
-- back: Sterling Forest has about 15 parts of 1-10 km² packed together.
--
-- Distances are Web Mercator metres, which are screen pixels at any latitude.
-- A point a zoom past spacing_zoom is twice as far apart on screen. Extra
-- points stop at min_label 16: style filters show everything from z17-18
-- (zoom >= min(min_label - k, Z)), and that cap would ignore the spacing.
--
-- Cost: the parts were already split (LargestPart dumps every part to find
-- the biggest); the extra work is a point per labellable part and, per group,
-- a distance from each part to each larger part, a self-join on the group
-- key that grows with the square of a group's labellable parts.
-- -----------------------------------------------------------------------------

BEGIN;
DROP MATERIALIZED VIEW IF EXISTS export.park_label CASCADE;
CREATE MATERIALIZED VIEW export.park_label AS
WITH settings AS (
    SELECT 400.0::double precision AS spacing_px,   -- 512 px tiles, i.e. CSS px
           14.0::double precision  AS part_max_ml,  -- parts smaller than this never get their own point
           16.0::double precision  AS extra_max_ml  -- extra points past this would only show from the style cap
),
clustered AS (
    SELECT
        osm_id,
        name,
        class,
        subclass,
        protect_class,
        iucn_level,
        area,
        geometry,
        ST_ClusterDBSCAN(geometry, eps := 0.001, minpoints := 1)
            OVER (PARTITION BY name)                                    AS cluster_id
    FROM export.park_polygon
    WHERE name IS NOT NULL
),
grouped AS (
    SELECT c.*, sum(c.area) OVER (PARTITION BY c.name, c.cluster_id)    AS group_area
    FROM clustered c
),
-- every polygon part of every park in the group, largest first (rn 1 = the
-- part the group's main label goes on); a park with no polygon part keeps
-- its whole geometry, as LabelPoint does
ranked AS (
    SELECT
        g.osm_id, g.name, g.class, g.subclass, g.protect_class, g.iucn_level,
        g.cluster_id, g.group_area,
        COALESCE(d.geom, g.geometry)                                    AS part,
        MercatorArea(d.geom)                                            AS part_area,
        row_number() OVER (PARTITION BY g.name, g.cluster_id
                           ORDER BY MercatorArea(d.geom) DESC NULLS LAST, g.osm_id) AS rn
    FROM grouped g
    LEFT JOIN LATERAL ST_Dump(ST_CollectionExtract(g.geometry, 3)) d ON true
),
-- the parts that may carry a point: the main one, and any big enough to be
-- labelled by their own size before part_max_ml
candidates AS (
    SELECT
        r.*,
        MinLabel(r.part_area)                                           AS part_ml,
        p.pt,
        ST_Transform(p.pt, 3857)                                        AS pt_3857
    FROM ranked r
    CROSS JOIN settings s
    CROSS JOIN LATERAL (SELECT ST_PointOnSurface(r.part) AS pt) p
    WHERE r.rn = 1 OR MinLabel(r.part_area) <= s.part_max_ml
),
-- each extra point's distance to the nearest point of a larger part
spacing AS (
    SELECT a.name, a.cluster_id, a.rn,
           min(ST_Distance(a.pt_3857, b.pt_3857))                       AS dist
    FROM candidates a
    JOIN candidates b ON b.name = a.name AND b.cluster_id = a.cluster_id AND b.rn < a.rn
    WHERE a.rn > 1
    GROUP BY a.name, a.cluster_id, a.rn
),
labelled AS (
    SELECT
        c.*,
        CASE WHEN c.rn = 1 THEN MinLabel(c.group_area)
             -- zoom at which dist is spacing_px on 512 px tiles: dist / ZRes(z + 1) = spacing_px
             ELSE round(GREATEST(MinLabel(c.group_area), c.part_ml,
                                 ln(s.spacing_px * 40075016.6855785 / (512 * GREATEST(sp.dist, 1))) / ln(2)
                        )::numeric, 1)::real
        END                                                             AS label_ml
    FROM candidates c
    CROSS JOIN settings s
    LEFT JOIN spacing sp USING (name, cluster_id, rn)
)
SELECT
    l.osm_id,
    l.name,
    l.class,
    l.subclass,
    l.protect_class,
    l.iucn_level,
    l.group_area::real                                                  AS area,
    l.label_ml                                                          AS min_label,
    l.pt::geometry(Point, 4326)                                         AS geometry
FROM labelled l, settings s
WHERE l.rn = 1 OR l.label_ml <= s.extra_max_ml;

CREATE INDEX idx_park_label_geometry ON export.park_label USING gist(geometry);
CREATE INDEX idx_park_label_subclass ON export.park_label USING btree(subclass);
CREATE INDEX idx_park_label_name     ON export.park_label USING btree(name);
COMMIT;
