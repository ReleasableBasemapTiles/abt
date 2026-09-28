DataSchemaErrorMessage = """
A schema directory (--schema-dir, e.g. an rbt-schema checkout) holds:
    import/
        osm/              imposm mapping files (*.yml/*.yaml), one per table
        aux_data/         auxiliary source configs (*.json)
        imposm_base.yml   optional imposm settings shared by every table
    carto_sql/            numbered *.sql scripts, plus an optional execution_plan.yml
    export/               one tile layer config (*.json) per layer
    tile-metadata/        metadata.py, read by the bundler command
import/, import/osm/, import/aux_data/, carto_sql/ and export/ must exist.
"""
