-- =============================================================================
-- AUX DATA GEOMETRY NORMALIZATION
-- Schema:        aux_data
-- =============================================================================


-- -----------------------------------------------------------------------------
-- aux_data — rename geometry columns, reproject to EPSG:4326, create gist indexes
-- -----------------------------------------------------------------------------

DO $$
DECLARE
    rec              RECORD;
    geom_column_name TEXT;
    geom_srid        INT;
    geom_type        TEXT;
    idx              TEXT;
BEGIN
    FOR rec IN
        SELECT f_table_schema    AS schema_name,
               f_table_name      AS table_name,
               f_geometry_column AS column_name,
               srid,
               type              AS geometry_type,
               'idx_' || f_table_name || '_geom' AS idx
        FROM geometry_columns
        WHERE f_table_schema = 'aux_data'
    LOOP
        geom_column_name := rec.column_name;
        geom_srid        := rec.srid;
        geom_type        := rec.geometry_type;
        idx              := rec.idx;

        -- 1. Rename column if it isn't named 'geometry'
        IF geom_column_name != 'geometry' THEN
            EXECUTE format('ALTER TABLE %I.%I RENAME COLUMN %I TO geometry;', rec.schema_name, rec.table_name, geom_column_name);
            RAISE NOTICE 'Renamed geometry column % from table % to geometry.', geom_column_name, rec.table_name;
        END IF;

        -- 2. Reproject to 4326 if it's currently 3857
        IF geom_srid = 3857 THEN
            EXECUTE format('ALTER TABLE %I.%I ALTER COLUMN geometry TYPE geometry(%s, 4326) USING ST_Transform(geometry, 4326);', rec.schema_name, rec.table_name, geom_type);
            RAISE NOTICE 'Reprojected geometry column for table % to SRID 4326.', rec.table_name;
        END IF;

        -- 3. Ensure GIST index exists
        EXECUTE format('CREATE INDEX IF NOT EXISTS %I ON %I.%I USING gist(geometry);', rec.idx, rec.schema_name, rec.table_name);
        RAISE NOTICE 'GIST index % verified/created on % .% (geometry).', rec.idx, rec.schema_name, rec.table_name;
    END LOOP;
END $$;