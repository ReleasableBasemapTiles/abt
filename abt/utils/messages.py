DataSchemaErrorMessage = """
Data Schema Directory Must include
    - <Schema Folder> 
    -- import 
    --- layers
    ---- <imposm_mapping.yaml>...
    -- export
    --- <data.json>...
    -- carto_sql
    --- <ordered directory of postgresql/postgis>.sql 
"""

class MbtilesNotFound(Exception):
    pass