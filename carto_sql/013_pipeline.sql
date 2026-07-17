-- =============================================================================
-- LAYER: Pipeline
-- Schema:        export
-- Sources:       osm.osm_utility_linestring
-- =============================================================================


-- -----------------------------------------------------------------------------
-- export.pipeline_line — pipeline and submarine/overhead cable linestrings
-- -----------------------------------------------------------------------------

BEGIN;
DROP MATERIALIZED VIEW IF EXISTS export.pipeline_line CASCADE;
CREATE MATERIALIZED VIEW export.pipeline_line AS
SELECT
    osm_id,
    class,
    subclass,
    NULLIF(name, '')                                                    AS name,
    NULLIF(location, '')                                                AS location,
    NULLIF(usage, '')                                                   AS usage,
    NULLIF(substance, '')                                               AS substance,
    NULLIF(diameter, '')                                                AS diameter,
    NULLIF(flow_direction, '')                                          AS flow_direction,
    NULLIF(operator, '')                                                AS operator,
    NULLIF(seamark_type, '')                                            AS seamark_type,
    NULLIF(pipeline_submarine_category, '')                             AS pipeline_submarine_category,
    NULLIF(pipeline_submarine_product, '')                              AS pipeline_submarine_product,
    NULLIF(pipeline_overhead_category, '')                              AS pipeline_overhead_category,
    NULLIF(pipeline_overhead_product, '')                               AS pipeline_overhead_product,
    NULLIF(product, '')                                                 AS product,
    NULLIF(content, '')                                                 AS content,
    NULLIF(height, '')                                                  AS height,
    ele,
    NULLIF(operational_status, '')                                      AS operational_status,
    NULLIF(condition, '')                                               AS condition,
    tags,
    geometry
FROM osm.osm_utility_linestring
WHERE (
    class IN ('man_made', 'pipeline')
    AND subclass NOT IN (
        'line',
        'minor_line',
        'insulator',
        'transmission',
        'sub_station',
        'substation',
        'cable',
        'wire',
        'cable_submarine',
        'cable_overhead',
        'busbar',
        'bay',
        'power'
    )
)
OR (
    seamark_type IN ('pipeline_overhead', 'pipeline_submarine')
);

CREATE INDEX idx_pipeline_geometry ON export.pipeline_line USING gist(geometry);
CREATE INDEX idx_pipeline_osm_id   ON export.pipeline_line USING btree(osm_id);
CREATE INDEX idx_pipeline_class    ON export.pipeline_line USING btree(class);
CREATE INDEX idx_pipeline_subclass ON export.pipeline_line USING btree(subclass);
CREATE INDEX idx_pipeline_seamark  ON export.pipeline_line USING btree(seamark_type) WHERE seamark_type IS NOT NULL;
CREATE INDEX idx_pipeline_name     ON export.pipeline_line USING btree(name) WHERE name IS NOT NULL;
COMMIT;
