# Prerequisites

What a build needs before you start, and which step of [Ubuntu Setup](ubuntu.md) installs each part. `setup_ubuntu.sh` installs all of it in one go.

## A host

The pipeline runs on **Ubuntu 26.04**, the release both install paths target. The two documented sizes:

| Tier | vCPUs | RAM | Disk | For |
|---|---|---|---|---|
| Planet | 48 | 384 GB | 2+ TB NVMe | a full-planet build; `import` alone takes 24+ hours |
| Small extract | 8 | 32 GB | 100 GB SSD | one country or region, e.g. the [Norway walkthrough](../walkthroughs/norway.md) |

See [Performance & Sizing](performance.md) for how the CLI and Postgres scale to each. Running the tests or building these docs needs none of this: they work on macOS or any Linux (see [Testing](../project/testing.md#running-the-suites-locally)).

## Tools

| Tool | Version | Used by | Install step |
|---|---|---|---|
| PostgreSQL and PostGIS | 16+ and 3.4+ (Ubuntu 26.04 ships 18 and 3.6) | `import`, `carto`, `export` | [2](ubuntu.md#2-postgresql-18-postgis-36) |
| `imposm` | 0.14+ | `import` (OSM) | [3](ubuntu.md#3-imposm-014) |
| `tippecanoe`, `tile-join` | 2.76+, built from source (the apt package is 2.53) | `export`, `bundler` | [4](ubuntu.md#4-tippecanoe-276-build-from-source) |
| GDAL (`ogr2ogr`, `ogrinfo`) and PROJ | 3.9.2+ and 9.8+ | `import` (aux data), `export` | [6](ubuntu.md#6-gdal-python-environment) |
| Python and the CLI's packages | 3.13, from `abtv2-tools/env.yaml` | every command | [6](ubuntu.md#6-gdal-python-environment) |
| `aria2c` | any | `download -k planet` | [1](ubuntu.md#1-base-packages) |
| `sqlite3` CLI | any | `init.sh --contours`, and inspecting output | [1](ubuntu.md#1-base-packages) |
| Rust and `abt-vundler` | stable | `vundler` | [7](ubuntu.md#7-rust-and-abt-vundler) |
| AWS CLI | any | `init.sh`'s S3 upload and `--overture` | [8](ubuntu.md#8-aws-cli-and-duckdb-optional) |
| `duckdb` | any | `init.sh --overture` | [8](ubuntu.md#8-aws-cli-and-duckdb-optional) |

The Postgres role needs to be a superuser, because `carto`'s parallel dissolves connect back to the database through `dblink` without a password. Step 2 creates one; `setup_ubuntu.sh` creates the same role, `rbt`.

## Network access

`download` fetches from the internet, so the host needs outbound HTTPS to:

- `download.geofabrik.de`, for the Geofabrik index and extracts;
- the planet mirrors, for `-k planet` (`download` queries several and checks that they agree on the file);
- each aux source's host: the `url` in every `rbt-schema/import/aux_data/*.json`. The MIRTA host, `www.acq.osd.mil`, is unreachable from some networks.

Downloads verify TLS certificates. See [Troubleshooting](../reference/troubleshooting.md#download-and-import) if one fails the check.

## AWS credentials

Only `init.sh`'s final S3 upload needs them, and only as `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY` and `AWS_SESSION_TOKEN` in the environment; `init.sh --no-upload` skips the upload and the check. `--overture` reads Overture's public bucket without credentials. See [init.sh Orchestrator](../walkthroughs/init-sh.md) for the details, including how long the credentials have to last.

## Next

1. [Ubuntu Setup](ubuntu.md), by hand or with `setup_ubuntu.sh`.
2. The [Norway walkthrough](../walkthroughs/norway.md), a small build end to end.
3. The [Glossary](../overview/glossary.md) and [Working Directory](../overview/working-directory.md), for what the commands produce.
