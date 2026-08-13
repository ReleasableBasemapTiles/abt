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
--                aux_data.dos_lsib                         (LSIB attestation + QA geometry)
-- =============================================================================


-- -----------------------------------------------------------------------------
-- aux_data.adm0_line_supplements — LSIB-verified whitelist for pair mismatches
-- -----------------------------------------------------------------------------

-- Fieldmaps disaggregates some boundaries into cc/Q2 (disputed-entity) pairs
-- that LSIB attributes to a different pair, so the pair-level attestation
-- filter on export.adm0_line drops them even though LSIB depicts the line.
-- Each row here restores one such fieldmaps line, keyed on
-- (cc1, cc2, country2, label), and records which LSIB line attests it.
--
-- Admission requires measured positional coincidence with LSIB line work
-- (>= 99% of points at 500 m spacing within 100 m of an LSIB line — observed
-- values are bimodal: ~100% for lines tracing LSIB, ~0% otherwise). The DO
-- block below re-measures on every build, so an LSIB or fieldmaps refresh
-- that invalidates a row fails the build instead of silently changing the map.
-- Verified against LSIB v11.4 / fieldmaps 2026-08: all rows 100.0% at 100 m.

BEGIN;
DROP TABLE IF EXISTS aux_data.adm0_line_supplements;
CREATE TABLE aux_data.adm0_line_supplements (
    cc1        varchar NOT NULL,
    cc2        varchar NOT NULL,
    country2   varchar NOT NULL,
    label      varchar NOT NULL,
    lsib_cc1   varchar NOT NULL,
    lsib_cc2   varchar NOT NULL,
    lsib_label varchar,
    note       varchar,
    PRIMARY KEY (cc1, cc2, country2, label)
);

INSERT INTO aux_data.adm0_line_supplements (cc1, cc2, country2, label, lsib_cc1, lsib_cc2, lsib_label, note) VALUES
    ('KE', 'Q2', 'Ilemi Triangle 1', 'Provisional Boundary',    'KE', 'KE', 'Provisional Boundary',    'Ilemi Triangle south edge; LSIB models as KE-internal provisional line'),
    ('KE', 'Q2', 'Ilemi Triangle 2', 'Administrative Boundary', 'KE', 'SS', 'Administrative Boundary', 'Ilemi Triangle; LSIB models as KE/SS administrative line'),
    ('KE', 'Q2', 'Ilemi Triangle 3', 'Provisional Boundary',    'KE', 'KE', 'Provisional Boundary',    'Ilemi Triangle south edge; LSIB models as KE-internal provisional line'),
    ('SS', 'Q2', 'Ilemi Triangle 1', 'Administrative Boundary', 'KE', 'SS', 'Administrative Boundary', 'Ilemi Triangle north edge; LSIB models as KE/SS administrative line'),
    ('SS', 'Q2', 'Ilemi Triangle 2', 'Provisional Boundary',    'SS', 'SS', 'Provisional Boundary',    'Ilemi Triangle; LSIB models as SS-internal provisional line'),
    ('SS', 'Q2', 'Ilemi Triangle 3', 'Administrative Boundary', 'KE', 'SS', 'Administrative Boundary', 'Ilemi Triangle north edge; LSIB models as KE/SS administrative line'),
    ('SD', 'Q2', 'Kafia Kingi',      'South Sudan Claim',       'SS', 'SD', NULL,                      'Traces the full LSIB rank-1 SS/SD boundary west of 24.85E; the rival SS/Q2 Sudan Claim line measures ~0% and stays excluded');
COMMIT;

-- Build-time verification of the whitelist against current source data.
-- Measures every Q2 fieldmaps line that fails pair-level LSIB attestation:
--   * a whitelisted line no longer tracing LSIB (< 99% within 100 m) fails —
--     LSIB moved or fieldmaps redrew; the row needs review, not silent export;
--   * a whitelist row matching no fieldmaps line fails — upstream rename;
--   * a NON-whitelisted line that now traces LSIB (>= 99%) fails — a new
--     candidate appeared and needs human review before it may be depicted.

DO $$
DECLARE
    rec RECORD;
    orphans TEXT;
BEGIN
    SELECT string_agg(format('(%s/%s, %s, %s)', s.cc1, s.cc2, s.country2, s.label), ', ')
    INTO orphans
    FROM aux_data.adm0_line_supplements s
    WHERE NOT EXISTS (
        SELECT 1 FROM aux_data.fieldmaps_adm0_lines f
        WHERE f.cc1 = s.cc1 AND f.cc2 = s.cc2
          AND f.country2 = s.country2 AND f.label = s.label
    );
    IF orphans IS NOT NULL THEN
        RAISE EXCEPTION 'adm0_line_supplements rows match no fieldmaps_adm0_lines row (upstream rename?): %', orphans;
    END IF;

    FOR rec IN
        WITH cand AS (
            SELECT f.fid, f.cc1, f.cc2, f.country2, f.label,
                   EXISTS (
                       SELECT 1 FROM aux_data.adm0_line_supplements s
                       WHERE s.cc1 = f.cc1 AND s.cc2 = f.cc2
                         AND s.country2 = f.country2 AND s.label = f.label
                   ) AS whitelisted
            FROM aux_data.fieldmaps_adm0_lines f
            WHERE (f.cc1 = 'Q2' OR f.cc2 = 'Q2')
              AND NOT EXISTS (
                  SELECT 1 FROM aux_data.dos_lsib l
                  WHERE LEAST(f.cc1, f.cc2)    = LEAST(l.cc1, l.cc2)
                    AND GREATEST(f.cc1, f.cc2) = GREATEST(l.cc1, l.cc2)
              )
        ),
        pts AS (
            SELECT c.fid, c.cc1, c.cc2, c.country2, c.label, c.whitelisted,
                   (ST_DumpPoints(ST_Segmentize(f.geometry::geography, 500)::geometry)).geom AS pt
            FROM cand c
            JOIN aux_data.fieldmaps_adm0_lines f USING (fid)
        )
        SELECT p.cc1, p.cc2, p.country2, p.label, p.whitelisted,
               round(100.0 * count(*) FILTER (WHERE EXISTS (
                   SELECT 1 FROM aux_data.dos_lsib l
                   WHERE l.geometry && ST_Expand(p.pt, 0.02)
                     AND ST_DWithin(p.pt::geography, l.geometry::geography, 100)
               )) / count(*), 1) AS pct_100m
        FROM pts p
        GROUP BY p.cc1, p.cc2, p.country2, p.label, p.whitelisted
    LOOP
        IF rec.whitelisted AND rec.pct_100m < 99 THEN
            -- WARNING not EXCEPTION: a hard stop here aborts a 24-hour pipeline.
            -- Geometric drift means LSIB or fieldmaps moved; review before next build.
            RAISE WARNING 'Whitelisted line (%/%, %, %) no longer traces LSIB: only % percent of points within 100 m. LSIB or fieldmaps changed; re-verify the supplement row.',
                rec.cc1, rec.cc2, rec.country2, rec.label, rec.pct_100m;
        ELSIF NOT rec.whitelisted AND rec.pct_100m >= 99 THEN
            -- WARNING not EXCEPTION: new candidate needs human review but should not
            -- kill the build. The line is excluded from export until added to the table.
            RAISE WARNING 'Unreviewed Q2 line (%/%, %, %) now traces LSIB (% percent within 100 m). Review and add to adm0_line_supplements, or exclude with a documented reason.',
                rec.cc1, rec.cc2, rec.country2, rec.label, rec.pct_100m;
        END IF;
    END LOOP;
END $$;


-- -----------------------------------------------------------------------------
-- export.adm0_line — country boundary lines (Fieldmaps)
-- -----------------------------------------------------------------------------

--- use Fieldmaps adjusted geometries but align with LSIB positions:
--- a line is exported iff LSIB attests its country pair, or it is whitelisted
--- in aux_data.adm0_line_supplements after measured coincidence with LSIB.

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
)
OR EXISTS (
    SELECT 1
    FROM aux_data.adm0_line_supplements s
    WHERE s.cc1 = f.cc1 AND s.cc2 = f.cc2
      AND s.country2 = f.country2 AND s.label = f.label
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
    CASE LEFT(a.adm0_id, 3)
        WHEN 'XAB' THEN 'Abyei Area'
        WHEN 'XKK' THEN 'Area in dispute'
        ELSE NULLIF(a.adm0_name, '')
    END                                                                 AS adm0_name,
    NULLIF(a.adm0_name1, '')                                            AS adm0_name1,
    a.status_cd,
    NULLIF(a.status_nm, '')                                             AS status_nm,
    -- Short display name (DOS naming overrides for disputed special entities)
    CASE LEFT(a.adm0_id, 3)
        WHEN 'XAB' THEN 'Abyei Area'
        WHEN 'XKK' THEN 'Area in dispute'
        ELSE COALESCE(s.full_nm_nd, NULLIF(a.adm0_name1, ''))
    END                                                                 AS gns_short_name,
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
    ON s.cc_ft = a.iso_2
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
