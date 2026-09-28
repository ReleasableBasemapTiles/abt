"""Tests for abt.export.exporter's skip logic and atomic outputs --
specifically that export_to_mbtiles resumes a tileset an earlier run left
unfinished instead of mistaking it for completed work, and that neither
step ever leaves an unfinished file at its final path -- plus export_layer's
per-step recording and order_largest_first.

run_subprocess is replaced with a recorder rather than actually invoking
ogr2ogr/tippecanoe: what's under test is the decision to run at all and
where the output lands. The recorder writes a stand-in output file where
the command says the tool would, as the real tools do on success; the
real tools' own behaviour is covered in test_utils_subprocess_tools.py.
"""

import sqlite3
from pathlib import Path

import pytest

from abt.export import exporter
from abt.export.exporter import export_layer, export_to_fgb, export_to_mbtiles, order_largest_first
from abt.export.tile_layer_model import (
    GeometryTypes,
    OGRExportOptions,
    TileLayer,
    TippecanoeOptions,
)
from abt.utils.pg_config import PGConfig
from abt.utils.run_reporter import RunReporter


def make_layer(tmp_path: Path, **overrides) -> TileLayer:
    defaults = dict(
        geometry_type=GeometryTypes.LINESTRING,
        pg_config=PGConfig(
            host="localhost", port=5432, user="u", password="p", database="d",
            log_path=tmp_path,
        ),
        flatgeobuf_dir=tmp_path / "flatgeobuf",
        mbtiles_dir=tmp_path / "mbtiles",
        tmp_dir=tmp_path / "tmp",
        log_dir=tmp_path / "logs",
        tippecanoe_options=TippecanoeOptions(minimum_zoom=8, maximum_zoom=13, max_detail_const=13),
        ogr_export_options=OGRExportOptions(),
    )
    defaults.update(overrides)
    layer = TileLayer(**defaults)
    # run_subprocess and get_logger both expect their directories to exist
    # already -- every real call site pre-creates them via
    # ProcessingDirectorySchema.init_working_directories.
    for directory in (layer.flatgeobuf_dir, layer.mbtiles_dir, layer.tmp_dir, layer.log_dir):
        directory.mkdir(parents=True, exist_ok=True)
    return layer


@pytest.fixture
def layer(tmp_path, request) -> TileLayer:
    """A TileLayer whose layer_id is unique to the requesting test.

    get_logger caches its FileHandler on a module-level logging.Logger
    keyed by stage and layer name, so tests sharing a layer_id would all
    write into whichever tmp_path happened to run first.
    """
    return make_layer(tmp_path, layer_id=request.node.name)


def command_output(kwargs) -> Path:
    """The output path a recorded ogr2ogr/tippecanoe command writes to."""
    cmd = kwargs["cmd"]
    if kwargs["tool_name"] == "tippecanoe":
        return Path(cmd[cmd.index("--output") + 1])
    return Path(cmd[-2])  # ogr2ogr: <output> PG:<uri>


def fake_tool_run(**kwargs) -> None:
    """Writes the output a successful ogr2ogr/tippecanoe run would."""
    output = command_output(kwargs)
    if kwargs["tool_name"] == "tippecanoe":
        write_tileset(output, tiles=1)
    else:
        output.write_bytes(b"fgb")


@pytest.fixture
def recorded_runs(monkeypatch):
    """Replaces run_subprocess with a recorder, returning the call list."""
    calls = []

    def record(**kwargs):
        calls.append(kwargs)
        fake_tool_run(**kwargs)

    monkeypatch.setattr(exporter, "run_subprocess", record)
    return calls


def write_tileset(path: Path, tiles: int) -> None:
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE metadata (name TEXT, value TEXT)")
    con.execute(
        "CREATE TABLE tiles "
        "(zoom_level INTEGER, tile_column INTEGER, tile_row INTEGER, tile_data BLOB)"
    )
    for i in range(tiles):
        con.execute("INSERT INTO tiles VALUES (8, 0, ?, ?)", (i, b"tile"))
    con.commit()
    con.close()


def test_export_to_mbtiles_runs_when_no_output_exists(layer, recorded_runs):
    export_to_mbtiles(layer)
    assert len(recorded_runs) == 1
    assert recorded_runs[0]["tool_name"] == "tippecanoe"


def test_export_to_mbtiles_skips_a_finished_tileset(layer, recorded_runs):
    write_tileset(layer.mbtiles_export_filename, tiles=1)
    export_to_mbtiles(layer)
    assert recorded_runs == []


def test_export_to_mbtiles_reruns_on_a_tile_less_stub(layer, recorded_runs):
    write_tileset(layer.mbtiles_export_filename, tiles=0)
    export_to_mbtiles(layer)
    assert len(recorded_runs) == 1


def test_export_to_mbtiles_reruns_on_a_zero_byte_output(layer, recorded_runs):
    layer.mbtiles_export_filename.touch()
    export_to_mbtiles(layer)
    assert len(recorded_runs) == 1


def test_export_to_mbtiles_removes_the_stub_before_rerunning(layer, monkeypatch):
    # tippecanoe exits EXIT_EXISTS rather than overwriting, so retrying is
    # only useful if the stub is gone by the time it runs.
    write_tileset(layer.mbtiles_export_filename, tiles=0)
    existed_at_run_time = []

    def record(**kwargs):
        existed_at_run_time.append(layer.mbtiles_export_filename.exists())
        fake_tool_run(**kwargs)

    monkeypatch.setattr(exporter, "run_subprocess", record)
    export_to_mbtiles(layer)
    assert existed_at_run_time == [False]


def test_export_to_mbtiles_logs_that_it_discarded_a_stub(layer, recorded_runs):
    write_tileset(layer.mbtiles_export_filename, tiles=0)
    export_to_mbtiles(layer)
    log_text = (layer.log_dir / f"{layer.layer_id}_export_to_mbtiles.log").read_text()
    assert f"Discarding incomplete {layer.mbtiles_export_filename.name}" in log_text


def test_export_to_mbtiles_says_nothing_about_stubs_on_a_first_run(layer, recorded_runs):
    export_to_mbtiles(layer)
    log_file = layer.log_dir / f"{layer.layer_id}_export_to_mbtiles.log"
    assert not log_file.exists()


def test_export_to_fgb_still_skips_on_existence_alone(layer, recorded_runs):
    # Existence is the right check for the .fgb because only a finished
    # file is ever moved to the final path (see the tests below).
    layer.ogr_export_filename.touch()
    export_to_fgb(layer)
    assert recorded_runs == []


# --- atomic outputs ----------------------------------------------------------

def test_export_to_fgb_writes_to_a_partial_path_then_moves_it_into_place(layer, recorded_runs):
    export_to_fgb(layer)
    assert command_output(recorded_runs[0]) == layer.ogr_partial_filename
    # GDAL's FlatGeobuf driver creates a directory for a name not ending in .fgb.
    assert layer.ogr_partial_filename.suffix == ".fgb"
    assert layer.ogr_export_filename.read_bytes() == b"fgb"
    assert not layer.ogr_partial_filename.exists()


def test_export_to_fgb_failure_leaves_nothing_at_the_final_path(layer, monkeypatch):
    # Regression test: ogr2ogr used to write straight to the final path, so
    # a killed run left a truncated .fgb that the rerun skipped and
    # tippecanoe then tiled without complaint.
    def killed(**kwargs):
        command_output(kwargs).write_bytes(b"trunc")
        raise RuntimeError("ogr2ogr killed")

    monkeypatch.setattr(exporter, "run_subprocess", killed)
    with pytest.raises(RuntimeError):
        export_to_fgb(layer)
    assert not layer.ogr_export_filename.exists()


def test_export_to_fgb_clears_a_stale_partial_before_running(layer, monkeypatch):
    layer.ogr_partial_filename.parent.mkdir(parents=True, exist_ok=True)
    layer.ogr_partial_filename.write_bytes(b"left by a killed run")
    existed_at_run_time = []

    def record(**kwargs):
        existed_at_run_time.append(layer.ogr_partial_filename.exists())
        fake_tool_run(**kwargs)

    monkeypatch.setattr(exporter, "run_subprocess", record)
    export_to_fgb(layer)
    assert existed_at_run_time == [False]


def test_export_to_fgb_tool_success_without_output_is_an_error(layer, monkeypatch):
    monkeypatch.setattr(exporter, "run_subprocess", lambda **kwargs: None)
    with pytest.raises(FileNotFoundError):
        export_to_fgb(layer)


def test_export_to_mbtiles_writes_to_a_partial_path_then_moves_it_into_place(layer, recorded_runs):
    export_to_mbtiles(layer)
    assert command_output(recorded_runs[0]) == layer.mbtiles_partial_filename
    assert exporter.is_complete_tileset(layer.mbtiles_export_filename)
    assert not layer.mbtiles_partial_filename.exists()


def test_export_to_mbtiles_killed_mid_run_leaves_nothing_at_the_final_path(layer, monkeypatch):
    # Regression test: a tippecanoe killed partway through writes some zoom
    # levels' tiles, which passed is_complete_tileset, so the rerun skipped
    # it and the layer shipped without its top zooms.
    def killed(**kwargs):
        write_tileset(command_output(kwargs), tiles=3)
        raise RuntimeError("tippecanoe killed")

    monkeypatch.setattr(exporter, "run_subprocess", killed)
    with pytest.raises(RuntimeError):
        export_to_mbtiles(layer)
    assert not layer.mbtiles_export_filename.exists()


def test_projection_override_metadata_is_written_before_the_move(tmp_path, request, recorded_runs):
    layer = make_layer(tmp_path, layer_id=request.node.name, projection_override="EPSG:3395")
    assert layer.is_projection_override_active
    export_to_mbtiles(layer)
    con = sqlite3.connect(layer.mbtiles_export_filename)
    metadata = dict(con.execute("SELECT name, value FROM metadata"))
    con.close()
    assert metadata["crs"] == "EPSG:3395"
    assert "bounds" in metadata and "center" in metadata


# --- export_layer --------------------------------------------------------------

def stage_tasks(reporter, tmp_path):
    summary = reporter.write_summary(tmp_path / "summary.json")
    return {stage["stage"]: stage["tasks"] for stage in summary["stages"]}


def test_export_layer_runs_and_records_both_steps(layer, recorded_runs, tmp_path):
    reporter = RunReporter(run_id="r1", command="abt export")
    export_layer(layer, reporter)
    assert [run["tool_name"] for run in recorded_runs] == ["ogr2ogr", "tippecanoe"]
    tasks = stage_tasks(reporter, tmp_path)
    assert list(tasks) == ["export_to_fgb", "export_to_mbtiles"]
    for (task,) in tasks.values():
        assert task["task"] == layer.layer_id
        assert task["status"] == "SUCCESS"
        assert task["duration_s"] >= 0


def test_export_layer_does_not_attempt_mbtiles_after_a_failed_fgb_export(layer, monkeypatch, tmp_path):
    # Regression test: tippecanoe used to run anyway and fail on the missing
    # .fgb, so one ogr2ogr failure was reported twice.
    tools = []

    def ogr2ogr_fails(**kwargs):
        tools.append(kwargs["tool_name"])
        raise RuntimeError("ogr2ogr exit 1")

    monkeypatch.setattr(exporter, "run_subprocess", ogr2ogr_fails)
    reporter = RunReporter(run_id="r1", command="abt export")
    with pytest.raises(RuntimeError, match="ogr2ogr exit 1"):
        export_layer(layer, reporter)
    assert tools == ["ogr2ogr"]
    tasks = stage_tasks(reporter, tmp_path)
    assert tasks["export_to_fgb"][0]["error"] == "ogr2ogr exit 1"
    assert tasks["export_to_mbtiles"] == [
        {"task": layer.layer_id, "status": "FAILED", "error": "not attempted (export_to_fgb failed)"},
    ]


# --- order_largest_first ------------------------------------------------------

def layers_with_fgbs(tmp_path, fgb_sizes):
    """One layer per layer_id, with an existing .fgb of the given size (None: no .fgb)."""
    layers = []
    for layer_id, fgb_size in fgb_sizes.items():
        layer = make_layer(tmp_path, layer_id=layer_id)
        if fgb_size is not None:
            layer.ogr_export_filename.write_bytes(b"x" * fgb_size)
        layers.append(layer)
    return layers


def test_order_largest_first_uses_table_sizes_then_fgb_sizes(tmp_path, monkeypatch):
    table_sizes = {"road": 10_000, "water": 30_000, "empty": 0}
    monkeypatch.setattr(PGConfig, "table_sizes", lambda self, schema: table_sizes if schema == "export" else {})
    layers = layers_with_fgbs(tmp_path, {
        "road": None, "water": None, "resumed": 20_000, "empty": 5, "poi": None, "adm": None,
    })
    ordered = order_largest_first(layers, layers[0].pg_config)
    # resumed has no table but a 20 kB .fgb; empty's table is empty, so its
    # .fgb decides; poi and adm have neither and tie, so go by name.
    assert [layer.layer_id for layer in ordered] == ["water", "resumed", "road", "empty", "adm", "poi"]


def test_order_largest_first_falls_back_to_fgb_sizes_when_the_query_fails(tmp_path, monkeypatch, capsys):
    def unreadable(self, schema):
        raise RuntimeError("permission denied")

    monkeypatch.setattr(PGConfig, "table_sizes", unreadable)
    layers = layers_with_fgbs(tmp_path, {"a": 1, "b": 3, "c": None})
    ordered = order_largest_first(layers, layers[0].pg_config)
    assert [layer.layer_id for layer in ordered] == ["b", "a", "c"]
    assert "couldn't read the export table sizes (permission denied)" in capsys.readouterr().out
