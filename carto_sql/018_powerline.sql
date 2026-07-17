-- =============================================================================
-- LAYER: Powerline
-- Schema:        export
-- Sources:       osm.osm_utility_linestring
-- =============================================================================


-- -----------------------------------------------------------------------------
-- export.powerline_line — power line and cable linestrings
-- -----------------------------------------------------------------------------

BEGIN;
DROP MATERIALIZED VIEW IF EXISTS export.powerline_line CASCADE;
CREATE MATERIALIZED VIEW export.powerline_line AS
SELECT
    osm_id,
    class,
    subclass,
    NULLIF(name, '')                                                    AS name,
    NULLIF(location, '')                                                AS location,
    NULLIF(cable_overhead_category, '')                                 AS cable_overhead_category,
    NULLIF(cable_submarine_category, '')                                AS cable_submarine_category,
    NULLIF(usage, '')                                                   AS usage,
    NULLIF(voltage, '')                                                 AS voltage,
    NULLIF(operator, '')                                                AS operator,
    NULLIF(cables, '')                                                  AS cables,
    NULLIF(wires, '')                                                   AS wires,
    geometry
FROM osm.osm_utility_linestring
WHERE subclass IN (
    'line', 'minor_line', 'insulator', 'transmission',
    'sub_station', 'substation', 'cable', 'wire',
    'cable_submarine', 'cable_overhead', 'busbar', 'bay', 'power'
)
AND (
    cable_overhead_category IS NULL
    OR cable_overhead_category NOT IN ('ferry', 'mooring')
)
AND (
    cable_submarine_category IS NULL
    OR cable_submarine_category != 'ferry'
);

CREATE INDEX idx_powerline_geometry ON export.powerline_line USING gist(geometry);
CREATE INDEX idx_powerline_osm_id   ON export.powerline_line USING btree(osm_id);
CREATE INDEX idx_powerline_class    ON export.powerline_line USING btree(class);
CREATE INDEX idx_powerline_subclass ON export.powerline_line USING btree(subclass);
CREATE INDEX idx_powerline_name     ON export.powerline_line USING btree(name) WHERE name IS NOT NULL;
COMMIT;
