# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Changed

- Publish the MkDocs site to GitHub Pages

## [2.0.0] - 2026-09-17

### Added

- Add Ubuntu setup script, bump env.yaml to Python 3.13, expand README
- Added standalone Overture buildings scripts
- Add NGA abbreviations, secondary capitals, and label refinements
- Added back missing ocean_polygon logic
- Added 'crs' metadata tag to overture building generation
- Add --max-zoom bundler flag for zoom-capped packages
- Add Overture buildings pipeline integration to init.sh
- Add MkDocs documentation site
- Add generated Database Schema page

### Changed

- Initial commit: workspace README and Ubuntu setup script
- Initial commit
- Metadata path fix
- Update env.yaml to replace libgdal-pg with libgdal in dependencies
- Adjusted aux_model to support wildcards in GDB imports
- Strip tippecanoe build metadata and honor declared bundle center
- Initial commit
- README todo
- SQL parallel optimizations
- Ocean self-intersecting polygon fix; Overture buildings tippecanoe flag adjustment
- Update road, wrailway, water, and utility layer defs. Adjusted SQL, JSON schemas, and imposm3 mappings
- Potential ocean_polygon artifacts fix; removed abandoned rail elements from export schema; added class_rank field for place conflict resolution
- Adjusted place_labels scheme to create more separation at ranks 10/11
- Rename transportation_station to transportation_station_polygon; drop abandoned railways
- Updated MIRTA download URL
- MIRTA layer name fix
- Set temp_buffers for landcover dissolve workers via dblink connstr
- Implemented z13 performance improvements (requires validation
- Admin and place name scheme adjustments
- Place and admin adjustements based on NGA feedback
- Metadata.py adjustments/cleanup
- Resolved overlapping admin0/1/2 boundary issue; correct adm0 short names
- Update docs and setup script for single-repo layout
- Document a 48 vCPU / 384GB sizing tier; add PG_MAX_CONNECTIONS
- Scale -n/--num-workers defaults to host CPU count
- Parallelize vundler's per-zoom-level mbtiles conversion
- Make dblink shard count / parallel workers configurable via GUCs
- Run independent carto_sql script groups concurrently
- Document concurrent carto/vundler execution and new failure semantics
- Enhance download functionality with aria2 integration and update setup configurations
- Update README and setup script for planet-scale processing and vundler integration
- Enhance init.sh for EPSG:3395 support and update processing steps
- Refactor init.sh and setup_ubuntu.sh for improved EPSG:3395 handling
- Enhance init.sh for S3 upload functionality and AWS credential checks
- Enhance init.sh for EPSG:4087 support and concurrent processing
- Update .gitignore files to include macOS-specific entries
- Complete test harnesses and review tasks for vundler integration
- Updated ne_physical_centerlines with new Appalachian Mts. and Rocky Mts. geometries
- Place_label ranking tweaks; rebuilt name / name_en logic to consolidate on single name field
- Syntax error correction
- Consolidate name/name_en to single English-first name field
- Syntax fix for grain_srf
- Roads, water: consolidate name/name_en to single English-first name field
- Reworked water_polygon handling to resolve simplification artifacts at small scales
- Lake America in-line label override
- Lake America in-line label override strengthening
- Overture building production alt-projections
- Consolidate name/name_en, water fixes, label overrides
- Overture building metadata update
- Made tag_crs.py standalone / removed abt module dependencies
- Building metadata
- .btis file  handling for non-3857 MBTiles
- Re-verify execution_plan.yml against upstream 3cca358
- Auto-detect monorepo root, add awscli/duckdb install stages
- Enhance setup_ubuntu.sh with auto-detection and installation options
- Bump target Python to 3.14
- Init.sh --from export flag; standardize tile output to .mbtiles
- Enhance abt-tools.py and mbtiles handling
- Overture tile.sh: raise open-file limit before invoking tippecanoe
- Cap mkdocs/mkdocs-material below their next major
- Pin to python3.13 to fix pyclipper install not available in python3.14
- Add git-cliff changelog and Conventional Commit linting

### Fixed

- Fix invalid # comment in 005a_water_polygon.sql
- Fixed admin label short name bug; Updated Overture building processing scripts and added README
- Fix status_cd type: number -> float in adm1/adm2 line exports
- Fix status_cd type to int across adm0/1/2 exports (bigint in Postgres)
- Downgrade adm0_line_supplements orphan check to WARNING
- Use current_setting('port') so connstr works on non-default ports
- Fix EPSG:4087 misalignment from DuckDB's outdated bundled PROJ

### Removed

- Removed abt_ prefix from metadata.py

[unreleased]: https://github.com/ReleasableBasemapTiles/abt/compare/v2.0.0..HEAD
[2.0.0]: https://github.com/ReleasableBasemapTiles/abt/releases/tag/v2.0.0

