-- =============================================================================
-- LAYER: Admin Boundaries and Labels
-- Schema:        export
-- Sources:       aux_data.fieldmaps_adm0_lines              (adm0 boundary lines)
--                aux_data.fieldmaps_adm0_points            (adm0 label points — edge-matched)
--                aux_data.fieldmaps_adm0_polygon           (adm0 polygons — area calc only)
--                aux_data.fieldmaps_adm1_lines             (adm1 boundary lines)
--                aux_data.fieldmaps_adm1_points            (adm1 label points — edge-matched)
--                aux_data.fieldmaps_adm2_lines             (adm2 boundary lines)
--                aux_data.fieldmaps_adm2_points            (adm2 label points — edge-matched)
--                aux_data.ne_10m_admin_0_countries         (adm0 label enrichment)
--                aux_data.nga_geonames_administrative_regions (adm0 label enrichment)
-- =============================================================================


-- -----------------------------------------------------------------------------
-- export.adm0_line — country boundary lines (Fieldmaps)
-- -----------------------------------------------------------------------------

--- use Fieldmaps adjusted geometries but align with LSIB positions

BEGIN;
DROP MATERIALIZED VIEW IF EXISTS export.adm0_line CASCADE;
CREATE MATERIALIZED VIEW export.adm0_line AS
SELECT
    NULLIF(f.cc1, '')                                                   AS cc1,
    NULLIF(f.cc2, '')                                                   AS cc2,
    NULLIF(f.country1, '')                                              AS country1,
    NULLIF(f.country2, '')                                              AS country2,
    NULLIF(f.label, '')                                                 AS label,
    NULLIF(f.notes, '')                                                 AS notes,
    f.rank,
    NULLIF(f.status, '')                                                AS status,
    f.geometry
FROM aux_data.fieldmaps_adm0_lines f
WHERE EXISTS (
    SELECT 1
    FROM aux_data.dos_lsib l
    WHERE LEAST(f.cc1, f.cc2)    = LEAST(l.cc1, l.cc2)
      AND GREATEST(f.cc1, f.cc2) = GREATEST(l.cc1, l.cc2)
);

CREATE INDEX idx_adm0_line_geometry ON export.adm0_line USING gist(geometry);
COMMIT;


-- -----------------------------------------------------------------------------
-- export.adm0_label — country label points (Fieldmaps + NE + GeoNames)
-- -----------------------------------------------------------------------------

BEGIN;
DROP MATERIALIZED VIEW IF EXISTS export.adm0_label CASCADE;
CREATE MATERIALIZED VIEW export.adm0_label AS

-- Resolve the best short/conventional name per country from GeoNames.
-- Priority: main country (PCLI) over sub-units (PCLIX), conventional (C) over approved (N).
-- ATF excluded — French Southern Territories is a collection of separate islands
-- Terminated records excluded via empty string check (term_dt_f is varchar, not date).
WITH gns_short AS (
    SELECT DISTINCT ON (cc_ft)
        cc_ft,
        full_nm_nd
    FROM aux_data.nga_geonames_administrative_regions
    WHERE name_rank::text = '1'
      AND desig_cd IN ('PCLI','PCLD','PCLF','PCLS','PCL','PCLIX')
      AND (term_dt_f IS NULL OR term_dt_f = '')
      AND cc_ft != 'ATF'
    ORDER BY cc_ft,
        CASE desig_cd WHEN 'PCLI' THEN 1 WHEN 'PCLD' THEN 2 ELSE 3 END,
        CASE nt       WHEN 'C'    THEN 1 WHEN 'N'    THEN 2 ELSE 3 END
)
SELECT
    a.adm0_id,
    NULLIF(a.adm0_name, '')                                             AS adm0_name,
    NULLIF(a.adm0_name1, '')                                            AS adm0_name1,
    a.status_cd,
    NULLIF(a.status_nm, '')                                             AS status_nm,
    -- Short display name
    COALESCE(s.full_nm_nd, NULLIF(a.adm0_name1, ''))                   AS gns_short_name,
    -- Full GeoNames match on name for additional metadata
    NULLIF(g.full_nm_nd, '')                                            AS gns_full_name,
    g.name_rank                                                         AS gns_name_rank,
    NULLIF(g.desig_cd, '')                                              AS gns_desig_cd,
    -- Natural Earth attributes for supplemental name variants
    NULLIF(n.abbrev, '')                                                AS ne_abbrev,
    NULLIF(n.formal_en, '')                                             AS ne_formal_en,
    NULLIF(n.name, '')                                                  AS ne_name,
    NULLIF(n.name_en, '')                                               AS ne_name_en,
    NULLIF(n.name_long, '')                                             AS ne_name_long,
    ST_Area(ST_Transform(poly.geometry, 3857))::real                    AS area,
    a.geometry                                                              AS geometry
FROM aux_data.fieldmaps_adm0_points a
LEFT JOIN aux_data.fieldmaps_adm0_polygon poly
    ON poly.adm0_id = a.adm0_id
LEFT JOIN gns_short s
    ON s.cc_ft = a.iso_3
LEFT JOIN aux_data.nga_geonames_administrative_regions g
    ON g.full_nm_nd = a.adm0_name1
LEFT JOIN aux_data.ne_10m_admin_0_countries n
    ON n.name = a.adm0_name1
WHERE a.geometry IS NOT NULL
  -- Exclude entities whose land borders were entirely removed by the LSIB filter.
  -- Logic: if a polygon has land borders in the fieldmaps source but none survived into export.adm0_line, DOS does not recognize it as a distinct entity.
  AND NOT (
      EXISTS (
          SELECT 1 FROM aux_data.fieldmaps_adm0_lines l
          WHERE l.cc1 = a.iso_2 OR l.cc2 = a.iso_2
      )
      AND NOT EXISTS (
          SELECT 1 FROM export.adm0_line l
          WHERE l.cc1 = a.iso_2 OR l.cc2 = a.iso_2
      )
  );

CREATE INDEX idx_adm0_label_geometry ON export.adm0_label USING gist(geometry);
CREATE INDEX idx_adm0_label_adm0_id  ON export.adm0_label USING btree(adm0_id);
COMMIT;

-- -----------------------------------------------------------------------------
-- export.adm1_line — region boundary lines (Fieldmaps)
-- -----------------------------------------------------------------------------

BEGIN;
DROP MATERIALIZED VIEW IF EXISTS export.adm1_line CASCADE;
CREATE MATERIALIZED VIEW export.adm1_line AS
SELECT
    iso_3,
    geometry
FROM aux_data.fieldmaps_adm1_lines
WHERE NOT (
    EXISTS (
        SELECT 1 FROM aux_data.fieldmaps_adm0_lines l
        WHERE l.cc1 = iso_2 OR l.cc2 = iso_2
    )
    AND NOT EXISTS (
        SELECT 1 FROM export.adm0_line l
        WHERE l.cc1 = iso_2 OR l.cc2 = iso_2
    )
);

CREATE INDEX idx_adm1_line_geometry ON export.adm1_line USING gist(geometry);
CREATE INDEX idx_adm1_line_iso_3    ON export.adm1_line USING btree(iso_3);
COMMIT;


-- -----------------------------------------------------------------------------
-- export.adm1_label — region label points (Fieldmaps)
-- -----------------------------------------------------------------------------

BEGIN;
DROP MATERIALIZED VIEW IF EXISTS export.adm1_label CASCADE;
CREATE MATERIALIZED VIEW export.adm1_label AS
SELECT
    adm1_id,
    NULLIF(adm1_name, '')                                               AS adm1_name,
    NULLIF(adm1_name1, '')                                              AS adm1_name1,
    iso_3,
    NULLIF(src_lang, '')                                                AS src_lang,
    NULLIF(src_lang1, '')                                               AS src_lang1,
    geometry                                                                AS geometry
FROM aux_data.fieldmaps_adm1_points
WHERE geometry IS NOT NULL
  AND NOT (
      EXISTS (
          SELECT 1 FROM aux_data.fieldmaps_adm0_lines l
          WHERE l.cc1 = iso_2 OR l.cc2 = iso_2
      )
      AND NOT EXISTS (
          SELECT 1 FROM export.adm0_line l
          WHERE l.cc1 = iso_2 OR l.cc2 = iso_2
      )
  );

CREATE INDEX idx_adm1_label_geometry ON export.adm1_label USING gist(geometry);
CREATE INDEX idx_adm1_label_iso_3    ON export.adm1_label USING btree(iso_3);
CREATE INDEX idx_adm1_label_adm1_id  ON export.adm1_label USING btree(adm1_id);
COMMIT;


-- -----------------------------------------------------------------------------
-- export.adm2_line — county boundary lines (Fieldmaps)
-- -----------------------------------------------------------------------------

BEGIN;
DROP MATERIALIZED VIEW IF EXISTS export.adm2_line CASCADE;
CREATE MATERIALIZED VIEW export.adm2_line AS
SELECT
    iso_3,
    geometry
FROM aux_data.fieldmaps_adm2_lines
WHERE NOT (
    EXISTS (
        SELECT 1 FROM aux_data.fieldmaps_adm0_lines l
        WHERE l.cc1 = iso_2 OR l.cc2 = iso_2
    )
    AND NOT EXISTS (
        SELECT 1 FROM export.adm0_line l
        WHERE l.cc1 = iso_2 OR l.cc2 = iso_2
    )
);

CREATE INDEX idx_adm2_line_geometry ON export.adm2_line USING gist(geometry);
CREATE INDEX idx_adm2_line_iso_3    ON export.adm2_line USING btree(iso_3);
COMMIT;


-- -----------------------------------------------------------------------------
-- export.adm2_label — county label points (Fieldmaps)
-- -----------------------------------------------------------------------------

BEGIN;
DROP MATERIALIZED VIEW IF EXISTS export.adm2_label CASCADE;
CREATE MATERIALIZED VIEW export.adm2_label AS
SELECT
    adm2_id,
    NULLIF(adm2_name, '')                                               AS adm2_name,
    NULLIF(adm2_name1, '')                                              AS adm2_name1,
    iso_3,
    NULLIF(src_lang, '')                                                AS src_lang,
    NULLIF(src_lang1, '')                                               AS src_lang1,
    geometry                                                                AS geometry
FROM aux_data.fieldmaps_adm2_points
WHERE geometry IS NOT NULL
  AND NOT (
      EXISTS (
          SELECT 1 FROM aux_data.fieldmaps_adm0_lines l
          WHERE l.cc1 = iso_2 OR l.cc2 = iso_2
      )
      AND NOT EXISTS (
          SELECT 1 FROM export.adm0_line l
          WHERE l.cc1 = iso_2 OR l.cc2 = iso_2
      )
  );

CREATE INDEX idx_adm2_label_geometry ON export.adm2_label USING gist(geometry);
CREATE INDEX idx_adm2_label_iso_3    ON export.adm2_label USING btree(iso_3);
CREATE INDEX idx_adm2_label_adm2_id  ON export.adm2_label USING btree(adm2_id);
COMMIT;
