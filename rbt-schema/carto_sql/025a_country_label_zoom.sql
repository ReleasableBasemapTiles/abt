-- =============================================================================
-- COUNTRY LABEL ZOOM — the zoom each country label starts at, and its rank
-- Schema:        aux_data
-- Sources:       aux_data.fieldmaps_adm0_polygon
--                aux_data.ne_10m_admin_0_countries
-- Used by:       026_places.sql (capitals wait for their country's label)
--                027_admin.sql  (export.adm0_label min_label and label_rank)
-- =============================================================================
--
-- Country labels used to be switched on by area steps in the styles, and every
-- national capital ranked 2 whatever the size of its country. Small territories
-- labeled late and flickered, and their capitals showed first: Hamilton from
-- z3, before Bermuda. This table gives each Fieldmaps adm0 one label zoom and
-- one rank, so a country label and its capital are tuned in one place.
--
-- Both scripts read this table, so it is built before them (see
-- execution_plan.yml; at -n 1 the 025a prefix sorts it before 026).


-- -----------------------------------------------------------------------------
-- aux_data.adm0_label_override — hand-set values per Fieldmaps adm0
-- -----------------------------------------------------------------------------
-- Keyed on the Fieldmaps adm0_id without its version suffix (BES_1, not
-- BES_1-20250729), so a Fieldmaps refresh doesn't orphan rows.
--   ne_adm0_a3: the Natural Earth adm0_a3 when it isn't the Fieldmaps code
--   min_label:  label zoom, overriding Natural Earth and the area fallback
--   label_rank: 1 (most prominent) to 10, overriding Natural Earth
-- Leave a column NULL to keep the derived value. This is the table to edit when
-- a country label comes in too early or too late.

BEGIN;
DROP TABLE IF EXISTS aux_data.adm0_label_override CASCADE;
CREATE TABLE aux_data.adm0_label_override (
    adm0_key   varchar PRIMARY KEY,
    ne_adm0_a3 varchar,
    min_label  real,
    label_rank integer,
    note       text NOT NULL
);

INSERT INTO aux_data.adm0_label_override (adm0_key, ne_adm0_a3, min_label, label_rank, note) VALUES
-- Natural Earth codes that differ from Fieldmaps (checked against the 20261105 build)
('XKX',   'KOS', NULL, NULL, 'Kosovo'),
('CPT',   'CLP', NULL, NULL, 'Clipperton Island'),
('XUK_1', 'WSB', NULL, NULL, 'Akrotiri'),
('XUK_2', 'ESB', NULL, NULL, 'Dhekelia'),
('CXR',   'IOA', NULL, NULL, 'Christmas Island: NE groups it with Cocos as Indian Ocean Ter.'),
('CCK',   'IOA', NULL, NULL, 'Cocos (Keeling) Islands: see Christmas Island');

COMMIT;


-- -----------------------------------------------------------------------------
-- aux_data.adm0_label_zoom — min_label and label_rank per Fieldmaps adm0
-- -----------------------------------------------------------------------------
-- min_label is the first of:
--   1. the override above
--   2. Natural Earth MIN_LABEL, which is hand-tuned for small island states
--      (Bermuda 4, Tuvalu 5) where an area rule labels them far too late
--   3. MinLabel(area), the zoom where the polygon is 32 px across, as the
--      other polygon labels use (001_set_schema.sql)
-- label_rank is the override, else Natural Earth LABELRANK, else derived from
-- min_label on NE's own scale (NE ranks run about two above MIN_LABEL).
--
-- Natural Earth is matched on adm0_a3, then iso_a3, against the Fieldmaps
-- code. Sub-entries (AUS_2, BES_1, SJM_1, ...) are separate territories that
-- share their parent's code, so they're matched only through an override;
-- otherwise Ashmore and Cartier would inherit Australia's z1.7. NE folds the
-- French overseas departments into France, so they use the area fallback.

BEGIN;
DROP TABLE IF EXISTS aux_data.adm0_label_zoom CASCADE;
CREATE TABLE aux_data.adm0_label_zoom AS
WITH adm0 AS (
    SELECT
        p.adm0_id,
        split_part(p.adm0_id, '-', 1)                                   AS adm0_key,
        ST_Area(ST_Transform(p.geometry, 3857))                         AS area
    FROM aux_data.fieldmaps_adm0_polygon p
)
SELECT
    a.adm0_id,
    n.adm0_a3                                                           AS ne_adm0_a3,
    z.min_label,
    COALESCE(o.label_rank, n.labelrank,
             LEAST(10, GREATEST(2, round(z.min_label)::integer + 2)))   AS label_rank
FROM adm0 a
LEFT JOIN aux_data.adm0_label_override o
    ON o.adm0_key = a.adm0_key
LEFT JOIN LATERAL (
    SELECT n.adm0_a3, n.min_label, n.labelrank
    FROM aux_data.ne_10m_admin_0_countries n
    CROSS JOIN LATERAL (
        SELECT CASE
            WHEN o.ne_adm0_a3 IS NOT NULL     THEN o.ne_adm0_a3
            WHEN strpos(a.adm0_key, '_') = 0  THEN LEFT(a.adm0_key, 3)
        END AS code
    ) c
    WHERE n.adm0_a3 = c.code OR n.iso_a3 = c.code
    ORDER BY (n.adm0_a3 = c.code) IS TRUE DESC
    LIMIT 1
) n ON true
CROSS JOIN LATERAL (
    SELECT COALESCE(
        o.min_label,
        n.min_label,
        public.MinLabel(a.area)
    )::real AS min_label
) z;

CREATE UNIQUE INDEX idx_adm0_label_zoom_adm0_id ON aux_data.adm0_label_zoom (adm0_id);
COMMIT;
