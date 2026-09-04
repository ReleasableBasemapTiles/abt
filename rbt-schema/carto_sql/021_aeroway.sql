-- =============================================================================
-- LAYER: Aeroway
-- Schema:        export
-- Intermediates: aeroway.runway_surface_mapping
--                aeroway.aerodrome_polygon
--                aeroway.osm_runway_line
--                aeroway.aerodrome_runway
--                aeroway.airports_runways
--                aeroway.ourairports_osm_join
--                aeroway.airports_runways_osm
-- Sources:       osm.osm_aeroway_polygon
--                osm.osm_aeroway_linestring
--                aux_data.ourairports_airports
--                aux_data.ourairports_runways
-- =============================================================================


-- -----------------------------------------------------------------------------
-- SCHEMA
-- -----------------------------------------------------------------------------

BEGIN;
CREATE SCHEMA IF NOT EXISTS aeroway;
COMMIT;


-- -----------------------------------------------------------------------------
-- aeroway.runway_surface_mapping — runway surface code reference table
-- -----------------------------------------------------------------------------

BEGIN;
DROP TABLE IF EXISTS aeroway.runway_surface_mapping CASCADE;
CREATE TABLE aeroway.runway_surface_mapping (
    id                SERIAL      PRIMARY KEY,
    original_surface  TEXT        NOT NULL UNIQUE,
    standardized_code VARCHAR(10) NOT NULL,
    is_pattern        BOOLEAN     DEFAULT FALSE
);

CREATE INDEX idx_runway_surface_mapping_original_surface ON aeroway.runway_surface_mapping USING btree(original_surface);
CREATE INDEX idx_runway_surface_mapping_is_pattern       ON aeroway.runway_surface_mapping USING btree(is_pattern);
COMMIT;


-- -----------------------------------------------------------------------------
-- aeroway.runway_surface_mapping — surface code data population
-- -----------------------------------------------------------------------------

BEGIN;

-- Pattern matches (evaluated with ILIKE)
INSERT INTO aeroway.runway_surface_mapping
    (original_surface, standardized_code, is_pattern)
VALUES
    ('ALUM%',      'ALUM-DECK', TRUE),
    ('%asphalt%',  'ASP',       TRUE),
    ('%concrete%', 'CON',       TRUE)
ON CONFLICT (original_surface) DO NOTHING;

-- Asphalt (ASP)
INSERT INTO aeroway.runway_surface_mapping (original_surface, standardized_code) VALUES
    ('APSH','ASP'),('asfalt','ASP'),('Asfalt','ASP'),('Asfalto','ASP'),
    ('Ashpalt','ASP'),('asp','ASP'),('ASP','ASP'),('ASP. Avgas available.','ASP'),
    ('asph','ASP'),('Asph','ASP'),('ASPH','ASP'),('ASPH 71/F/C/X/T','ASP'),
    ('asphalt','ASP'),('Asphalt','ASP'),('ASPHALT','ASP'),
    ('Asphalt. 131.615 Mhz','ASP'),('ASP/CON','ASP'),('ASP/CONC','ASP'),
    ('ASP/GRE','ASP'),('ASP/GRS','ASP'),('ASP/GVL','ASP'),
    ('Asphalt/Coccrete','ASP'),('asphalt concrete','ASP'),
    ('asphalt/concrete','ASP'),('Asphalt/Concrete','ASP'),
    ('asphalt/dirt','ASP'),('Asphalt/Dirt','ASP'),('Asphalt/Grass','ASP'),
    ('asphalt/gravel','ASP'),('Asphalt/treated','ASP'),('Asphalt/Turf','ASP'),
    ('ASPHALT/TURF','ASP'),('Asph/Conc','ASP'),('ASPH-CONC','ASP'),
    ('ASPH/ CONC','ASP'),('ASPH/CONC','ASP'),('ASPH-CONC-F','ASP'),
    ('ASPH-CONC-G','ASP'),('ASPH-CONC-P','ASP'),('ASPH-DIRT','ASP'),
    ('ASPH-DIRT-G','ASP'),('ASPH-DIRT-P','ASP'),('ASPH-E','ASP'),
    ('ASPH-F','ASP'),('ASPH-G','ASP'),('ASPH/GRASS','ASP'),
    ('ASPH-GRVL','ASP'),('ASPH/GRVL','ASP'),('ASPH-GRVL-F','ASP'),
    ('ASPH/GRVL-F','ASP'),('ASPH-GRVL-G','ASP'),('ASPH-GRVL-P','ASP'),
    ('ASPH-L','ASP'),('ASPH-P','ASP'),('ASPH-TRTD','ASP'),
    ('ASPH-TRTD-F','ASP'),('ASPH-TRTD-G','ASP'),('ASPH-TRTD-P','ASP'),
    ('ASPH-TURF','ASP'),('ASPH-TURF-E','ASP'),('ASPH-TURF-F','ASP'),
    ('ASPH-TURF-G','ASP'),('ASPH-TURF-P','ASP'),('ASP/TURF','ASP'),
    ('Grooved ASP','ASP'),('Blacktop on granite','ASP')
ON CONFLICT (original_surface) DO NOTHING;

-- Unknown (U)
INSERT INTO aeroway.runway_surface_mapping (original_surface, standardized_code) VALUES
    ('UG','U'),('UNK','U'),('UNKNOWN','U'),('Unknown ? Aço(steel)','U'),('','U')
ON CONFLICT (original_surface) DO NOTHING;

-- Unpaved (UNPAVED)
INSERT INTO aeroway.runway_surface_mapping (original_surface, standardized_code) VALUES
    ('Unpaved','UNPAVED'),('UnPaved','UNPAVED'),('UNPAVED','UNPAVED'),
    ('Unpeved runway','UNPAVED'),('Not paved','UNPAVED'),('unsealed','UNPAVED')
ON CONFLICT (original_surface) DO NOTHING;

-- Water (WAT)
INSERT INTO aeroway.runway_surface_mapping (original_surface, standardized_code) VALUES
    ('WAT','WAT'),('water','WAT'),('Water','WAT'),('WATER','WAT'),
    ('WATER-E','WAT'),('WATER-G','WAT')
ON CONFLICT (original_surface) DO NOTHING;

-- Wood (WOOD)
INSERT INTO aeroway.runway_surface_mapping (original_surface, standardized_code) VALUES
    ('Wood','WOOD'),('WOOD','WOOD')
ON CONFLICT (original_surface) DO NOTHING;

-- Turf (TURF)
INSERT INTO aeroway.runway_surface_mapping (original_surface, standardized_code) VALUES
    ('Tuef','TURF'),('turf','TURF'),('tURF','TURF'),('Turf','TURF'),
    ('TURF','TURF'),('Torf','TURF')
ON CONFLICT (original_surface) DO NOTHING;

-- Sand (SAN)
INSERT INTO aeroway.runway_surface_mapping (original_surface, standardized_code) VALUES
    ('SAN','SAN'),('sand','SAN'),('Sand','SAN'),('SAND','SAN'),
    ('sand and grass','SAN'),('Sand/clay','SAN'),('Sand/Clay','SAN'),
    ('SAND/CLAY/GRAV','SAN'),('SAND-F','SAN'),('sand/grass','SAN'),
    ('SAN (Piçarra)','SAN'),('Sand grass','SAN'),('Sand/grass','SAN'),
    ('Sand/Grass','SAN'),('SAND/GRASS','SAN'),('SAND/GRAVEL','SAN'),
    ('SAND/GRAVEL/AS','SAN'),('SAND/GRVL','SAN'),('Sand laterite','SAN'),
    ('SAND, TIDAL','SAN'),('SAND/TURF','SAN'),('Sandy gravel with clay','SAN')
ON CONFLICT (original_surface) DO NOTHING;

-- Bitumen (BIT)
INSERT INTO aeroway.runway_surface_mapping (original_surface, standardized_code) VALUES
    ('BITUM','BIT'),('Bitumen','BIT'),('bitumen/gravel','BIT'),
    ('Bituminous','BIT'),('BITUMINOUS','BIT'),
    ('Volcanic ash impregnated with bitumen','BIT'),('tar','BIT'),
    ('Tar','BIT'),('Tar - lights 5 clicks on 124.8','BIT'),('tarmac','BIT'),
    ('Tarmac','BIT'),('tar old','BIT'),('Tarred','BIT'),('sealed','BIT'),
    ('Sealed','BIT'),('Sealed bitumen','BIT'),('Sealed, grooved.','BIT')
ON CONFLICT (original_surface) DO NOTHING;

-- Brick (BRI)
INSERT INTO aeroway.runway_surface_mapping (original_surface, standardized_code) VALUES
    ('BRI','BRI'),('Brick','BRI'),('BRICK','BRI'),('Ceramic Brick','BRI')
ON CONFLICT (original_surface) DO NOTHING;

-- Graded Earth (GRE)
INSERT INTO aeroway.runway_surface_mapping (original_surface, standardized_code) VALUES
    ('compacted earth','GRE'),('Compacted Earth','GRE'),('Compacted sand','GRE'),
    ('Graded Hardcore','GRE'),('Zahorra compactada','GRE'),('graded earth','GRE'),
    ('Graded earth','GRE'),('Graded Earth','GRE'),('Grass/Graded Hardcore','GRE'),
    ('GRASS/HARDCORE','GRE'),('Grass/rolled earth','GRE'),('Grass over gravel','GRE'),
    ('Grass over hard gravel','GRE'),('TURF/ASP','GRE'),('TURF/ASPHALT','GRE'),
    ('TURF/CHIPSEAL','GRE'),('TURF/CLAY','GRE'),('Turf/Concrete','GRE'),
    ('Turf/dirt','GRE'),('Turf/Dirt','GRE'),('TURF-DIRT','GRE'),
    ('TURF-DIRT-F','GRE'),('TURF-DIRT-G','GRE'),('TURF-DIRT-P','GRE'),
    ('TURF-E','GRE'),('TURF/EARTH','GRE'),('TURF/EARTH/GRA','GRE'),
    ('TURF-F','GRE'),('TURF-G','GRE'),('Turf / Grass','GRE'),
    ('Turf/Grass','GRE'),('Turf / Gravel','GRE'),('Turf/Gravel','GRE'),
    ('TURF/GRAVEL','GRE'),('TURF/GRAVEL/AS','GRE'),('TURF/GRAVEL/CL','GRE'),
    ('TURF/GRAVEL/SN','GRE'),('TURF-GRVL','GRE'),('TURF/GRVL','GRE'),
    ('TURF-GRVL-F','GRE'),('TURF-GRVL-G','GRE'),('TURF-GRVL-P','GRE'),
    ('TURF/OIL PACKE','GRE'),('TURF-P','GRE'),('TURF-SAND-F','GRE'),
    ('Turf / Snow','GRE'),('Turf/Snow','GRE'),('TURF/SNOW','GRE'),
    ('Turf, soft during spring thaw','GRE'),('TURF/SOIL','GRE'),
    ('TURF/TREATED G','GRE'),('TURF-TRTD-G','GRE'),('Paved/Compacted schist','GRE'),
    ('packed dirt','GRE'),('PACKED GRAVEL','GRE')
ON CONFLICT (original_surface) DO NOTHING;

-- Clay (CLA)
INSERT INTO aeroway.runway_surface_mapping (original_surface, standardized_code) VALUES
    ('Brown clay','CLA'),('Brown clay gravel','CLA'),('Brown gravel','CLA'),
    ('Brown silt clay','CLA'),('Brown Silt clay','CLA'),('CLA','CLA'),
    ('Clay','CLA'),('CLAY','CLA'),('Clay/grass','CLA'),('Clay/Gravel','CLA'),
    ('CLAY/GRAVEL','CLA'),('CLAY/GRAVEL/TU','CLA'),('CLAY/GRVL','CLA'),
    ('Clay/Sand','CLA'),('CLAY/SAND','CLA'),('CLAY/TURF','CLA'),
    ('Grey clay','CLA'),('Grey gravel','CLA'),('Grey silt clay','CLA'),
    ('Red clay','CLA'),('Red clay gravel','CLA'),('Red gravel','CLA'),
    ('Red silt clay','CLA'),('Rock/Gravel/Clay','CLA'),('Shale/Clay','CLA'),
    ('Shaly Clay','CLA'),('Black clay','CLA'),('Black silt','CLA'),
    ('Hard clay','CLA'),('Hard loam','CLA')
ON CONFLICT (original_surface) DO NOTHING;

-- Coral (COR)
INSERT INTO aeroway.runway_surface_mapping (original_surface, standardized_code) VALUES
    ('Compacted coral and sand','COR'),('COR','COR'),('Coral','COR'),
    ('CORAL','COR'),('Coral grass','COR'),('Coral penetration','COR'),
    ('Coral sand','COR'),('Crushed coral','COR')
ON CONFLICT (original_surface) DO NOTHING;

-- Gravel (GVL)
INSERT INTO aeroway.runway_surface_mapping (original_surface, standardized_code) VALUES
    ('CRUSHED ROCK','GVL'),('crushed rock and asphalt','GVL'),('grav','GVL'),
    ('PIC','GVL'),('PIÇ','GVL'),('Piçarra','GVL'),('Yellow gravel','GVL'),
    ('GRAV','GVL'),('gravel','GVL'),('Gravel','GVL'),('GRAVEL','GVL'),
    ('Gravel/Asphalt mix','GVL'),
    ('GRAVEL / CINDERS / CRUSHED ROCK / CORAL/SHELLS / SLAG','GVL'),
    ('Gravel/clay','GVL'),('GRAVEL/CLAY','GVL'),('GRAVEL/CLAY/SA','GVL'),
    ('Gravel (covered with a tarp)','GVL'),('Gravel dirt','GVL'),
    ('Gravel/dirt','GVL'),('Gravel/Dirt','GVL'),('GRAVEL-E','GVL'),
    ('GRAVEL-F','GVL'),('GRAVEL-G','GVL'),('Gravel/grass','GVL'),
    ('Gravel/Grass','GVL'),('GRAVEL/GRASS','GVL'),
    ('Gravel/grass, First 410m of RWY 23 paved','GVL'),
    ('GRAVEL, GRASS / SOD','GVL'),('GRAVEL-P','GVL'),('GRAVEL/SAND','GVL'),
    ('GRAVEL/SAND/CL','GVL'),('Gravel/Snow','GVL'),('Gravel/soil','GVL'),
    ('GRAVEL, TRTD','GVL'),('Gravel/Turf','GVL'),('GRAVEL/TURF','GVL'),
    ('GRV','GVL'),('GRV/ASP','GVL'),('GRV/GRASS','GVL'),('GRVL','GVL'),
    ('GRVL/ASP','GVL'),('GRVL/CLAY','GVL'),('Grvl/Dirt','GVL'),
    ('GRVL-DIRT','GVL'),('GRVL-DIRT-E','GVL'),('GRVL-DIRT-F','GVL'),
    ('GRVL-DIRT-G','GVL'),('GRVL-DIRT-P','GVL'),('GRVL-E','GVL'),
    ('GRVL-F','GVL'),('GRVL-G','GVL'),('GRVL-GRASS','GVL'),
    ('GRVL/GRASS','GVL'),('GRVL-P','GVL'),('GRVL/PIÇ','GVL'),
    ('GRVL-TRTD','GVL'),('GRVL-TRTD-F','GVL'),('GRVL-TRTD-P','GVL'),
    ('GRVL-TURF','GVL'),('GRVL/TURF','GVL'),('GRVL-TURF-F','GVL'),
    ('GRVL-TURF-G','GVL'),('GRVL-TURF-P','GVL'),('GRV/MAICILLO','GVL'),
    ('GRV/PAD','GVL'),('GVL','GVL'),('White gravel','GVL'),
    ('Paved/Gravel','GVL'),('Rocky gravel','GVL'),('Piçarra gravel','GVL'),
    ('Piçarra Gravel','GVL')
ON CONFLICT (original_surface) DO NOTHING;

-- Grass / Soil / Dirt (GRS)
INSERT INTO aeroway.runway_surface_mapping (original_surface, standardized_code) VALUES
    ('dirt','GRS'),('Volcanic ash/soil','GRS'),('dirt?','GRS'),('lakebed','GRS'),
    ('Dirt','GRS'),('DIRT','GRS'),('DIRT(Caliche)','GRS'),('DIRT-E','GRS'),
    ('DIRT-F','GRS'),('DIRT-G','GRS'),('Dirt/grass','GRS'),('Dirt/Gravel','GRS'),
    ('DIRT-GRVL','GRS'),('DIRT-GRVL-F','GRS'),('DIRT-GRVL-G','GRS'),
    ('DIRT-GRVL-P','GRS'),('dirt, No winter maint.','GRS'),('DIRT-P','GRS'),
    ('Dirt/rock','GRS'),('DIRT-SAND','GRS'),('DIRT-TRTD','GRS'),
    ('DIRT-TURF','GRS'),('DIRT-TURF-F','GRS'),('DIRT-TURF-G','GRS'),
    ('earth','GRS'),('Earth','GRS'),('EARTH','GRS'),('Earth/sand','GRS'),
    ('EARTH/SNOW','GRS'),('EARTH/TURF','GRS'),('Erba','GRS'),
    ('GOOD GRASS','GRS'),('Gr','GRS'),('GR','GRS'),('GRA','GRS'),
    ('graas','GRS'),('GRAAS','GRS'),('gras','GRS'),('Gras','GRS'),
    ('grass','GRS'),('Grass','GRS'),('GRASS','GRS'),
    ('grass. 26 end has power lines 20ft from threshold. approx 50 ft','GRS'),
    ('GRASS&amp;GRAVEL','GRS'),('Grass and granite sand','GRS'),
    ('Grass/Asphalt Insert 1968X59 Feet','GRS'),
    ('GRASS CAUTION: ATC do NOT apply wake turbulence separation!','GRS'),
    ('Grass - caution moles','GRS'),('Grass/clay','GRS'),('Grass/Clay','GRS'),
    ('grass/concrete','GRS'),('Grass/Concrete','GRS'),('grass coral','GRS'),
    ('Grass/dirt','GRS'),('Grass Dirt','GRS'),('grass/earth','GRS'),
    ('Grassed black clay','GRS'),('Grassed blackclay','GRS'),
    ('Grassed black clay sand','GRS'),('Grassed black clay silt','GRS'),
    ('Grassed black sand','GRS'),('Grassed black silt','GRS'),
    ('Grassed black silt clay','GRS'),('Grassed black silt sand','GRS'),
    ('Grassed black soil','GRS'),('Grassed brown clay','GRS'),
    ('Grassed Brown Clay','GRS'),('Grassed brown clay gravel','GRS'),
    ('Grassed brown gravel','GRS'),('Grassed brown loam','GRS'),
    ('Grassed brown sandy clay','GRS'),('Grassed brown silt clay','GRS'),
    ('Grassed brown silt loam','GRS'),('Grassed brown silty clay','GRS'),
    ('Grassed clay','GRS'),('Grassed clay silt clay','GRS'),
    ('Grassed gravel','GRS'),('Grassed grey clay','GRS'),
    ('Grassed grey gravel','GRS'),('Grassed grey sand','GRS'),
    ('Grassed grey silt clay','GRS'),('Grassed grey silt sand','GRS'),
    ('Grassed limestone gravel','GRS'),('Grassed red clay','GRS'),
    ('Grassed Red Clay','GRS'),('Grassed red clay gravel','GRS'),
    ('Grassed red silt','GRS'),('Grassed red silt clay','GRS'),
    ('Grassed red silt sand','GRS'),('Grassed red silty clay','GRS'),
    ('Grassed river gravel','GRS'),('Grassed Sand','GRS'),
    ('Grassed sand clay','GRS'),('Grassed sandy loam','GRS'),
    ('Grassed silt clay','GRS'),('Grassed white coronas','GRS'),
    ('Grassed white gravel','GRS'),('Grassed white lime stone','GRS'),
    ('Grassed yellow clay','GRS'),('Grassed yellow gravel','GRS'),
    ('Grassed yellow silt clay','GRS'),('GRASS-F','GRS'),
    ('Grass, first 500x6 meter on 25 is paved','GRS'),
    ('grass/gravel','GRS'),('Grass/gravel','GRS'),('Grass/Gravel','GRS'),
    ('GRASS/GRAVEL','GRS'),('Grass/Helipads Concrete','GRS'),
    ('Grass - Herbe','GRS'),('grass - herbe  (avion)','GRS'),
    ('Grass - Herbe -> Avion - ULM','GRS'),('grass - herbe  (planeur)','GRS'),
    ('Grass/Moss','GRS'),('Grassnow taxiway only!!','GRS'),
    ('Grass on coral','GRS'),('GRASS OR EARTH NOT GRADED OR ROLLED','GRS'),
    ('Grass over clay','GRS'),('Grass over rock','GRS'),('GRASS/PAD','GRS'),
    ('grass paved with a plastic grille','GRS'),('Grass/red clay','GRS'),
    ('Grass red silty clay','GRS'),('Grasss','GRS'),('Grass/Sand','GRS'),
    ('Grass/sandy soil','GRS'),('Grass/Snow','GRS'),('GRASS/SNOW','GRS'),
    ('GRASS / SOD','GRS'),('GRASS / SOD, GRAVEL','GRS'),
    ('GRASS / SOD, NATURAL SOIL','GRS'),('grassy','GRS'),('ground','GRS'),
    ('Ground','GRS'),('GRS','GRS'),('GRS Emergency Strip','GRS'),
    ('GRS/GVL','GRS'),('SOD','GRS'),('Sod over hard clay','GRS'),
    ('Sod with gravel & sand','GRS'),('Soft','GRS'),('Soft Gravel','GRS'),
    ('SOFT SAND','GRS'),('Soil','GRS'),('Soil and Grass','GRS'),
    ('Soil, rough gravel','GRS'),('Natural Soil','GRS'),
    ('NATURAL SOIL','GRS'),('NATURAL SOIL, GRASS / SOD','GRS'),
    ('LOOSE GRAVEL','GRS'),('Limestone/Grass','GRS'),('Hard mud','GRS'),
    ('Hard Sand','GRS'),('Herba (grass)','GRS')
ON CONFLICT (original_surface) DO NOTHING;

-- Concrete (CON)
INSERT INTO aeroway.runway_surface_mapping (original_surface, standardized_code) VALUES
    ('CON','CON'),('CON/ASP','CON'),('conc','CON'),('Conc','CON'),('CONC','CON'),
    ('CONC/ASPH','CON'),('CONC-E','CON'),('CONC-F','CON'),('CONC-G','CON'),
    ('CONC-GRVD','CON'),('CONC-GRVL','CON'),('CONC/GRVL','CON'),
    ('CONC-GRVL-G','CON'),('CONC/MTAL','CON'),('CONC-P','CON'),
    ('concrete','CON'),('Concrete','CON'),('CONCRETE','CON'),
    ('CONCRETE AND ASP','CON'),('Concrete and turf.','CON'),
    ('Concrete/Asphalt','CON'),('concrete blocks','CON'),
    ('Concrete/Grass','CON'),('CONCRETE + GRASS. MTOM 2t','CON'),
    ('Concrete/Gravel','CON'),('Concrete - Grooved','CON'),
    ('Concrete/Turf','CON'),('CONC-TRTD','CON'),('CONC-TRTD-G','CON'),
    ('Conc/Turf','CON'),('CONC-TURF','CON'),('CONC-TURF-F','CON'),
    ('CONC-TURF-G','CON'),('CON/GRS','CON'),('CON/GVL','CON'),
    ('CON/MET','CON'),('CON/PAD','CON'),('C0N','CON'),('Caliche','CON'),
    ('CALICHE','CON'),('cement','CON'),('Cement','CON')
ON CONFLICT (original_surface) DO NOTHING;

-- Snow (SNO)
INSERT INTO aeroway.runway_surface_mapping (original_surface, standardized_code) VALUES
    ('SNO','SNO'),('Snow','SNO'),('SNOW','SNO'),('Snow/Ice','SNO')
ON CONFLICT (original_surface) DO NOTHING;

-- Ice (ICE)
INSERT INTO aeroway.runway_surface_mapping (original_surface, standardized_code) VALUES
    ('ice','ICE'),('Ice','ICE'),('ICE','ICE'),('Ice - frozen lake','ICE')
ON CONFLICT (original_surface) DO NOTHING;

-- Composite (COM)
INSERT INTO aeroway.runway_surface_mapping (original_surface, standardized_code) VALUES
    ('COM','COM'),('COP','COM')
ON CONFLICT (original_surface) DO NOTHING;

-- Permanent / Hard Paved (PER)
INSERT INTO aeroway.runway_surface_mapping (original_surface, standardized_code) VALUES
    ('Surface paved','PER'),('hard','PER'),('Hard','PER'),
    ('Hard Surfaced','PER'),('paved','PER'),('Paved','PER'),
    ('PAVED','PER'),('Pavement','PER'),('paving','PER'),('PER','PER')
ON CONFLICT (original_surface) DO NOTHING;

-- Macadam / Treated (MAC)
INSERT INTO aeroway.runway_surface_mapping (original_surface, standardized_code) VALUES
    ('TER','MAC'),('TREATED','MAC'),('TREATED-E','MAC'),('TREATED-F','MAC'),
    ('TREATED-G','MAC'),('TREATED GRAVEL','MAC'),('TREATED SAND','MAC'),
    ('TRTD','MAC'),('TRTD-DIRT','MAC'),('TRTD-DIRT-F','MAC'),
    ('TRTD-DIRT-P','MAC'),('TRTD GRVL','MAC'),('OIL&CHIP-T-G','MAC'),
    ('OILED','MAC'),('OILED DIRT','MAC'),('OILED GRAVEL','MAC'),
    ('OILED GRAVEL/T','MAC'),('Oilgravel','MAC'),('Oilgravel/sand','MAC'),
    ('OLD ASP','MAC'),('Oligravel/GRVL','MAC'),('MAC','MAC'),('Macadam','MAC')
ON CONFLICT (original_surface) DO NOTHING;

-- Pierced Steel Planking (PSP)
INSERT INTO aeroway.runway_surface_mapping (original_surface, standardized_code) VALUES
    ('Mats','PSP'),('MATS','PSP'),('MATS-G','PSP'),('MET','PSP'),
    ('Metal','PSP'),('METAL','PSP'),('MET/CON','PSP'),('MTAL','PSP'),
    ('Steel','PSP'),('STEEL','PSP'),('STEEL-CONC','PSP'),
    ('PIERCED STEEL PLANKING / LANDING MATS / MEMBRANES','PSP')
ON CONFLICT (original_surface) DO NOTHING;

COMMIT;


-- -----------------------------------------------------------------------------
-- aeroway.aerodrome_polygon — OSM aerodrome boundary polygons with area
-- -----------------------------------------------------------------------------

BEGIN;
DROP MATERIALIZED VIEW IF EXISTS aeroway.aerodrome_polygon CASCADE;
CREATE MATERIALIZED VIEW aeroway.aerodrome_polygon AS
SELECT
    osm_id,
    geometry,
    ST_Area(ST_Transform(geometry, 3857))::real                         AS area,
    NULLIF(iata, '')                                                    AS iata,
    NULLIF(icao, '')                                                    AS icao,
    NULLIF(name, '')                                                    AS name
FROM osm.osm_aeroway_polygon
WHERE subclass = 'aerodrome';

CREATE INDEX idx_aerodrome_polygon_geometry ON aeroway.aerodrome_polygon USING gist(geometry);
CREATE INDEX idx_aerodrome_polygon_name     ON aeroway.aerodrome_polygon USING btree(name) WHERE name IS NOT NULL;
CREATE INDEX idx_aerodrome_polygon_icao     ON aeroway.aerodrome_polygon USING btree(icao) WHERE icao IS NOT NULL;
CREATE INDEX idx_aerodrome_polygon_iata     ON aeroway.aerodrome_polygon USING btree(iata) WHERE iata IS NOT NULL;
COMMIT;


-- -----------------------------------------------------------------------------
-- aeroway.osm_runway_line — OSM runway linestrings with length
-- -----------------------------------------------------------------------------

BEGIN;
DROP MATERIALIZED VIEW IF EXISTS aeroway.osm_runway_line CASCADE;
CREATE MATERIALIZED VIEW aeroway.osm_runway_line AS
SELECT
    osm_id,
    geometry,
    ST_Length(ST_Transform(geometry, 3857))::real                       AS runway_length_m,
    NULLIF(surface, '')                                                 AS runway_surface
FROM osm.osm_aeroway_linestring
WHERE subclass = 'runway';

CREATE INDEX idx_osm_runway_line_geometry ON aeroway.osm_runway_line USING gist(geometry);
COMMIT;


-- -----------------------------------------------------------------------------
-- aeroway.aerodrome_runway — aerodrome polygons joined to intersecting runways
-- -----------------------------------------------------------------------------

BEGIN;
DROP MATERIALIZED VIEW IF EXISTS aeroway.aerodrome_runway CASCADE;
CREATE MATERIALIZED VIEW aeroway.aerodrome_runway AS
SELECT
    a.osm_id          AS osm_id_aerodrome,
    b.osm_id          AS osm_id_runway,
    a.area            AS osm_aerodrome_area,
    b.runway_length_m AS osm_runway_length,
    b.runway_surface  AS osm_runway_surface,
    a.iata,
    a.icao,
    a.name,
    a.geometry
FROM aeroway.aerodrome_polygon a
LEFT JOIN aeroway.osm_runway_line b ON ST_Intersects(b.geometry, a.geometry);

CREATE INDEX idx_aerodrome_runway_geometry ON aeroway.aerodrome_runway USING gist(geometry);
CREATE INDEX idx_aerodrome_runway_name     ON aeroway.aerodrome_runway USING btree(name) WHERE name IS NOT NULL;
CREATE INDEX idx_aerodrome_runway_icao     ON aeroway.aerodrome_runway USING btree(icao) WHERE icao IS NOT NULL;
CREATE INDEX idx_aerodrome_runway_iata     ON aeroway.aerodrome_runway USING btree(iata) WHERE iata IS NOT NULL;
COMMIT;


-- -----------------------------------------------------------------------------
-- aeroway.airports_runways — OurAirports airports joined to their runways
-- -----------------------------------------------------------------------------

BEGIN;
DROP MATERIALIZED VIEW IF EXISTS aeroway.airports_runways CASCADE;
CREATE MATERIALIZED VIEW aeroway.airports_runways AS
SELECT
    a.id                                AS airport_id,
    a.ident,
    NULLIF(r.length_ft,       '')::real AS runway_length_ft,
    NULLIF(r.width_ft,        '')::real AS runway_width_ft,
    NULLIF(r.surface,         '')       AS runway_surface,
    NULLIF(r.lighted,         '')       AS runway_lighted,
    NULLIF(r.closed,          '')       AS runway_closed,
    NULLIF(r.le_ident,        '')       AS runway_le_ident,
    NULLIF(r.le_heading_degt, '')::real AS runway_le_heading,
    NULLIF(r.he_ident,        '')       AS runway_he_ident,
    NULLIF(r.he_heading_degt, '')::real AS runway_he_heading,
    a.type,
    a.name,
    NULLIF(a.elevation_ft,    '')::real AS elevation_ft,
    a.continent,
    a.iso_country,
    a.iso_region,
    a.municipality,
    a.scheduled_service,
    a.gps_code                          AS icao,
    a.iata_code                         AS iata,
    a.local_code,
    a.geometry
FROM aux_data.ourairports_airports a
LEFT JOIN aux_data.ourairports_runways r ON a.id = r.airport_ref
WHERE NOT ST_Contains(ST_MakeEnvelope(-2, -2, 2, 2, 4326), a.geometry);

CREATE INDEX idx_airports_runways_geometry         ON aeroway.airports_runways USING gist(geometry);
CREATE INDEX idx_airports_runways_airport_id       ON aeroway.airports_runways USING btree(airport_id);
CREATE INDEX idx_airports_runways_runway_length_ft ON aeroway.airports_runways USING btree(runway_length_ft);
CREATE INDEX idx_airports_runways_ident            ON aeroway.airports_runways USING btree(ident);
CREATE INDEX idx_airports_runways_icao             ON aeroway.airports_runways USING btree(icao) WHERE icao IS NOT NULL;
CREATE INDEX idx_airports_runways_iata             ON aeroway.airports_runways USING btree(iata) WHERE iata IS NOT NULL;
CREATE INDEX idx_airports_runways_name             ON aeroway.airports_runways USING btree(name) WHERE name IS NOT NULL;
COMMIT;


-- -----------------------------------------------------------------------------
-- aeroway.ourairports_osm_join — OSM aerodromes matched to OurAirports records
-- -----------------------------------------------------------------------------
-- Performance note:
--   The four match conditions (geometry, ICAO, IATA, name) are split into
--   separate UNION branches so each can use its own index. A single JOIN with
--   OR conditions forces a cross join + filter and cannot use any index.
-- -----------------------------------------------------------------------------

BEGIN;
DROP MATERIALIZED VIEW IF EXISTS aeroway.ourairports_osm_join CASCADE;
CREATE MATERIALIZED VIEW aeroway.ourairports_osm_join AS
-- Spatial match: OSM aerodrome polygon contains OurAirports point
SELECT DISTINCT
    a.osm_id_aerodrome,
    a.osm_id_runway,
    a.osm_aerodrome_area,
    a.osm_runway_length,
    a.osm_runway_surface,
    b.airport_id
FROM aeroway.aerodrome_runway a
JOIN aeroway.airports_runways b ON ST_Intersects(a.geometry, b.geometry)

UNION

-- ICAO code match
SELECT DISTINCT
    a.osm_id_aerodrome,
    a.osm_id_runway,
    a.osm_aerodrome_area,
    a.osm_runway_length,
    a.osm_runway_surface,
    b.airport_id
FROM aeroway.aerodrome_runway a
JOIN aeroway.airports_runways b ON a.icao = b.icao
WHERE a.icao IS NOT NULL AND b.icao IS NOT NULL

UNION

-- IATA code match
SELECT DISTINCT
    a.osm_id_aerodrome,
    a.osm_id_runway,
    a.osm_aerodrome_area,
    a.osm_runway_length,
    a.osm_runway_surface,
    b.airport_id
FROM aeroway.aerodrome_runway a
JOIN aeroway.airports_runways b ON a.iata = b.iata
WHERE a.iata IS NOT NULL AND b.iata IS NOT NULL

UNION

-- Name match
SELECT DISTINCT
    a.osm_id_aerodrome,
    a.osm_id_runway,
    a.osm_aerodrome_area,
    a.osm_runway_length,
    a.osm_runway_surface,
    b.airport_id
FROM aeroway.aerodrome_runway a
JOIN aeroway.airports_runways b ON a.name = b.name
WHERE a.name IS NOT NULL AND b.name IS NOT NULL;

CREATE INDEX idx_ourairports_osm_join_airport_id         ON aeroway.ourairports_osm_join USING btree(airport_id);
CREATE INDEX idx_ourairports_osm_join_osm_aerodrome_area ON aeroway.ourairports_osm_join USING btree(osm_aerodrome_area);
CREATE INDEX idx_ourairports_osm_join_osm_runway_length  ON aeroway.ourairports_osm_join USING btree(osm_runway_length);
COMMIT;


-- -----------------------------------------------------------------------------
-- aeroway.airports_runways_osm — OurAirports records enriched with OSM runway data
-- -----------------------------------------------------------------------------

BEGIN;
DROP MATERIALIZED VIEW IF EXISTS aeroway.airports_runways_osm CASCADE;
CREATE MATERIALIZED VIEW aeroway.airports_runways_osm AS
SELECT
    a.airport_id,
    a.ident,
    CASE
        WHEN a.runway_length_ft IS NULL AND b.osm_runway_length IS NOT NULL
            THEN (b.osm_runway_length * 3.28084)::real
        ELSE a.runway_length_ft
    END                AS runway_length_ft,
    a.runway_width_ft,
    CASE
        WHEN a.runway_surface IS NULL AND b.osm_runway_surface IS NOT NULL
            THEN b.osm_runway_surface
        ELSE a.runway_surface
    END                AS runway_surface,
    a.runway_lighted,
    a.runway_closed,
    a.runway_le_ident,
    a.runway_le_heading,
    a.runway_he_ident,
    a.runway_he_heading,
    a.type,
    a.name,
    a.elevation_ft,
    a.continent,
    a.iso_country,
    a.iso_region,
    a.municipality,
    a.scheduled_service,
    a.icao,
    a.iata,
    a.local_code,
    b.osm_id_aerodrome,
    b.osm_id_runway,
    b.osm_aerodrome_area,
    a.geometry
FROM aeroway.airports_runways a
LEFT JOIN aeroway.ourairports_osm_join b ON a.airport_id = b.airport_id;

CREATE INDEX idx_airports_runways_osm_geometry           ON aeroway.airports_runways_osm USING gist(geometry);
CREATE INDEX idx_airports_runways_osm_airport_id         ON aeroway.airports_runways_osm USING btree(airport_id);
CREATE INDEX idx_airports_runways_osm_runway_length_ft   ON aeroway.airports_runways_osm USING btree(runway_length_ft);
CREATE INDEX idx_airports_runways_osm_ident              ON aeroway.airports_runways_osm USING btree(ident);
CREATE INDEX idx_airports_runways_osm_osm_aerodrome_area ON aeroway.airports_runways_osm USING btree(osm_aerodrome_area);
CREATE INDEX idx_airports_runways_osm_runway_surface     ON aeroway.airports_runways_osm USING btree(runway_surface) WHERE runway_surface IS NOT NULL;
COMMIT;


-- -----------------------------------------------------------------------------
-- export.airport_polygon — OSM aeroway polygon features
-- -----------------------------------------------------------------------------

BEGIN;
DROP MATERIALIZED VIEW IF EXISTS export.airport_polygon CASCADE;
CREATE MATERIALIZED VIEW export.airport_polygon AS
SELECT
    osm_id,
    COALESCE(NULLIF(name_en, ''), NULLIF(name, ''))                     AS name,
    NULLIF(aerodrome_type, '')                                          AS aerodrome_type,
    NULLIF(amenity,        '')                                          AS amenity,
    class,
    subclass,
    NULLIF(ele,            '')                                          AS ele,
    NULLIF(iata,           '')                                          AS iata,
    NULLIF(icao,           '')                                          AS icao,
    NULLIF(military,       '')                                          AS military,
    NULLIF(operator,       '')                                          AS operator,
    NULLIF(surface,        '')                                          AS surface,
    ST_Area(ST_Transform(geometry, 3857))::real                          AS area,
    geometry
FROM osm.osm_aeroway_polygon;

CREATE INDEX idx_aeroway_surface_geometry ON export.airport_polygon USING gist(geometry);
CREATE INDEX idx_aeroway_surface_subclass ON export.airport_polygon USING btree(subclass);
CREATE INDEX idx_aeroway_surface_area     ON export.airport_polygon USING btree(area);
COMMIT;


-- -----------------------------------------------------------------------------
-- export.airport_label — de-duplicated airport point layer
-- -----------------------------------------------------------------------------

BEGIN;
DROP MATERIALIZED VIEW IF EXISTS export.airport_label CASCADE;
CREATE MATERIALIZED VIEW export.airport_label AS
WITH runway_counts AS (
    SELECT
        airport_id,
        SUM(CASE WHEN runway_length_ft > 4000                THEN 1 ELSE 0 END) AS l_runway_count,
        SUM(CASE WHEN runway_length_ft BETWEEN 1500 AND 4000 THEN 1 ELSE 0 END) AS m_runway_count,
        SUM(CASE WHEN runway_length_ft < 1500                THEN 1 ELSE 0 END) AS s_runway_count,
        SUM(CASE WHEN runway_length_ft IS NULL               THEN 1 ELSE 0 END) AS u_runway_count,
        COUNT(*)                                                                 AS runway_count
    FROM aeroway.airports_runways_osm
    GROUP BY airport_id
),
airports AS (
    SELECT
        a.airport_id,
        a.ident,
        a.runway_length_ft,
        a.runway_width_ft,
        COALESCE(surf_pat.standardized_code, surf_exact.standardized_code, a.runway_surface)
                                           AS runway_surface,
        a.runway_lighted,
        a.runway_closed,
        a.runway_le_ident,
        a.runway_le_heading,
        a.runway_he_ident,
        a.runway_he_heading,
        a.type,
        a.name,
        a.elevation_ft,
        a.continent,
        a.iso_country,
        a.iso_region,
        a.municipality,
        a.scheduled_service,
        a.icao,
        a.iata,
        a.local_code,
        a.osm_id_aerodrome,
        a.osm_id_runway,
        a.osm_aerodrome_area,
        CASE
            WHEN a.osm_aerodrome_area >= 2500000
                THEN 1
            WHEN (a.osm_aerodrome_area < 2500000 OR a.osm_aerodrome_area IS NULL)
                 AND (    b.l_runway_count = b.runway_count
                      OR (b.runway_count > 1
                          AND (   (b.l_runway_count = 1 AND b.m_runway_count >= 1)
                               OR  b.m_runway_count > 1)))
                THEN 2
            WHEN (a.osm_aerodrome_area < 2500000 OR a.osm_aerodrome_area IS NULL)
                 AND b.runway_count >= 1
                 AND b.l_runway_count = 0
                 AND b.m_runway_count = 1
                THEN 3
            ELSE 4
        END                                AS category,
        CASE WHEN a.type = 'closed' THEN 2 ELSE 1 END AS rank,
        a.geometry,
        ROW_NUMBER() OVER (
            PARTITION BY a.airport_id
            ORDER BY COALESCE(a.runway_length_ft, -1) DESC
        )                                  AS _row_rank
    FROM aeroway.airports_runways_osm a
    LEFT JOIN runway_counts b ON a.airport_id = b.airport_id
    LEFT JOIN LATERAL (
        SELECT m.standardized_code
        FROM aeroway.runway_surface_mapping m
        WHERE m.is_pattern AND a.runway_surface ILIKE m.original_surface
        LIMIT 1
    ) surf_pat ON true
    LEFT JOIN LATERAL (
        SELECT m.standardized_code
        FROM aeroway.runway_surface_mapping m
        WHERE NOT m.is_pattern AND a.runway_surface = m.original_surface
        LIMIT 1
    ) surf_exact ON true
    WHERE NOT (
        a.name ILIKE ANY(ARRAY['%helicopter%','%helipad%','%heliport%'])
        OR a.type = 'heliport'
    )
)
SELECT
    airport_id, ident,
    runway_length_ft, runway_width_ft, runway_surface,
    runway_lighted, runway_closed,
    runway_le_ident, runway_le_heading,
    runway_he_ident, runway_he_heading,
    type, name, elevation_ft,
    continent, iso_country, iso_region, municipality, scheduled_service,
    icao, iata, local_code,
    osm_id_aerodrome, osm_id_runway, osm_aerodrome_area,
    category, rank, geometry
FROM airports
WHERE _row_rank = 1;

CREATE INDEX idx_airport_geometry ON export.airport_label USING gist(geometry);
CREATE INDEX idx_airport_type     ON export.airport_label USING btree(type);
CREATE INDEX idx_airport_category ON export.airport_label USING btree(category);
CREATE INDEX idx_airport_icao     ON export.airport_label USING btree(icao) WHERE icao IS NOT NULL;
CREATE INDEX idx_airport_iata     ON export.airport_label USING btree(iata) WHERE iata IS NOT NULL;
COMMIT;


-- -----------------------------------------------------------------------------
-- export.heliport_point — heliport and helicopter facility points
-- -----------------------------------------------------------------------------

BEGIN;
DROP MATERIALIZED VIEW IF EXISTS export.heliport_point CASCADE;
CREATE MATERIALIZED VIEW export.heliport_point AS
WITH airports AS (
    SELECT
        CASE
            WHEN name ILIKE '%hospital%'
              OR name ILIKE '%clinic%'
              OR name ILIKE '%emergency%'
              OR name ILIKE '%medic%'  THEN 'y'
            ELSE 'n'
        END AS hospital,
        ident AS airport_ident,
        CASE
            WHEN (name ILIKE '%helicopter%'
               OR name ILIKE '%helipad%'
               OR name ILIKE '%heliport%')
             AND type = 'closed'                   THEN 'closed_heliport'
            WHEN (name ILIKE '%helicopter%'
               OR name ILIKE '%helipad%'
               OR name ILIKE '%heliport%')
             AND type NOT IN ('closed','heliport') THEN 'heliport'
            ELSE type
        END AS type,
        name,
        NULLIF(elevation_ft, '')::real AS elevation_ft,
        scheduled_service,
        gps_code  AS icao,
        iata_code AS iata,
        local_code,
        geometry
    FROM aux_data.ourairports_airports
    WHERE NOT ST_Contains(ST_MakeEnvelope(-2, -2, 2, 2, 4326), geometry)
)
SELECT
    airport_ident,
    type,
    name,
    hospital,
    CASE
        WHEN type = 'heliport'        AND hospital = 'y' THEN 1
        WHEN type = 'heliport'        AND hospital = 'n' THEN 2
        WHEN type = 'closed_heliport' AND hospital = 'y' THEN 3
        ELSE 4
    END AS rank,
    elevation_ft,
    scheduled_service,
    icao,
    iata,
    local_code,
    geometry
FROM airports
WHERE type IN ('heliport','closed_heliport');

CREATE INDEX idx_heliport_geometry ON export.heliport_point USING gist(geometry);
CREATE INDEX idx_heliport_type     ON export.heliport_point USING btree(type);
CREATE INDEX idx_heliport_rank     ON export.heliport_point USING btree(rank);
COMMIT;


-- -----------------------------------------------------------------------------
-- export.runway_line — aeroway linestring features
-- -----------------------------------------------------------------------------

BEGIN;
DROP MATERIALIZED VIEW IF EXISTS export.runway_line CASCADE;
CREATE MATERIALIZED VIEW export.runway_line AS
SELECT
    osm_id,
    NULLIF(ref,      '')                                                AS ref,
    class,
    subclass,
    NULLIF(icao,     '')                                                AS icao,
    NULLIF(iata,     '')                                                AS iata,
    NULLIF(surface,  '')                                                AS surface,
    NULLIF(width,    '')                                                AS width,
    NULLIF(ele,      '')                                                AS ele,
    ST_Length(ST_Transform(geometry, 3857))::real                       AS length_m,
    NULLIF(military, '')                                                AS military,
    NULLIF(name,     '')                                                AS name,
    NULLIF(operator, '')                                                AS operator,
    geometry
FROM osm.osm_aeroway_linestring;

CREATE INDEX idx_runway_curve_geometry ON export.runway_line USING gist(geometry);
CREATE INDEX idx_runway_curve_subclass ON export.runway_line USING btree(subclass);
CREATE INDEX idx_runway_curve_length_m ON export.runway_line USING btree(length_m);
COMMIT;
