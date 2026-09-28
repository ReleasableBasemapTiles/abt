"""
carto_processing_model.py

Defines the models responsible for executing carto_sql/*.sql against a
PostgreSQL database. By default (or if the schema dir has no
execution_plan.yml), scripts run one at a time in filename order, as they
always have. When execution_plan.yml is present and concurrency > 1, scripts
run in three phases instead:

  1. prefix    -- sequential (e.g. 000_update_aux_geom.sql, 001_set_schema.sql)
  2. groups    -- each group's scripts run in order, one after another (each
                  script on its own connection); independent groups run
                  concurrently with each other
  3. suffix    -- sequential, only if every group succeeded (e.g. 099_update_geometry.sql)

Either way, every script that runs is timed, and CartoProcessingModel.script_runs
lists how each went -- see ScriptRun.

See rbt-schema/carto_sql/execution_plan.yml for the full format and the
dependency analysis behind today's grouping.
"""

import os
import re
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import yaml
from pydantic import BaseModel, ConfigDict, PositiveInt
from tqdm import tqdm

from .parallel import ParallelExecutor
from .utils.pg_config import PGConfig
from .utils.run_reporter import STATUS_FAILED, STATUS_SUCCESS

_IDENTIFIER_RE = re.compile(r"^[a-z_][a-z0-9_]*$")

# What carto_sql's GUC readers fall back to when abt.* is unset, i.e. what
# one script gets when it runs alone (sequential mode). A concurrent group
# never gets more.
MAX_DISSOLVE_SHARDS = 16
MAX_PARALLEL_WORKERS_PER_GATHER = 10


def group_guc_values(weights: List[int], concurrency: int, cpu_count: int) -> List[Tuple[int, int]]:
    """Sizes each group's (abt.dissolve_shards, abt.parallel_workers_per_gather).

    The CPU budget, max(cpu_count - 4, cpu_count // 2), is shared between
    the groups that start at once -- the first `concurrency` of them, since
    ParallelExecutor starts tasks in list order -- in proportion to their
    weights. A group that starts later gets the share its weight would have
    had among those. Shards are that share and workers a quarter of it,
    each at least 2 and at most the scripts' sequential defaults. With every
    weight 1 this is budget // (groups running at once) for everyone.
    """
    running = min(len(weights), concurrency) or 1
    starting_weight = sum(weights[:running]) or 1
    budget = max(cpu_count - 4, cpu_count // 2)  # leave headroom for the OS/other backends
    values = []
    for weight in weights:
        share = max(1, budget * weight // starting_weight)
        values.append((
            min(MAX_DISSOLVE_SHARDS, max(2, share)),
            min(MAX_PARALLEL_WORKERS_PER_GATHER, max(2, share // 4)),
        ))
    return values


class CartoExecutionPlan(BaseModel):
    """Parsed rbt-schema/carto_sql/execution_plan.yml.

    Attributes:
        custom_schemas: Schema names to `CREATE SCHEMA IF NOT EXISTS` once,
            sequentially, before any group runs -- avoids concurrent scripts
            racing to create the same schema for the first time.
        extensions: Extension names to `CREATE EXTENSION IF NOT EXISTS`
            for the same reason (e.g. dblink).
        prefix: Filenames (matching carto_sql/*.sql) to run sequentially,
            in order, before any group.
        groups: Each inner list is a set of filenames that must run in that
            order, one after another. Different groups run concurrently
            with each other, started in list order.
        suffix: Filenames to run sequentially, in order, after every group
            has completed successfully.
        weights: Optional group-script filename -> weight (default 1). A
            group's weight is its heaviest script's, and sets its share of
            the CPU budget -- see group_guc_values.
    """
    custom_schemas: List[str] = []
    extensions: List[str] = []
    prefix: List[str] = []
    groups: List[List[str]] = []
    suffix: List[str] = []
    weights: Dict[str, PositiveInt] = {}

    @classmethod
    def load(cls, path: Path) -> Optional["CartoExecutionPlan"]:
        """Returns None if `path` doesn't exist, so callers can fall back to
        fully sequential execution for a --schema-dir that predates this
        file (or simply doesn't want concurrent carto execution).
        """
        if not path.exists():
            return None
        raw = yaml.safe_load(path.read_text()) or {}
        return cls(**{field: raw[field] for field in cls.model_fields if raw.get(field) is not None})

    def group_weight(self, group: List[str]) -> int:
        """A group's weight: its heaviest script's (scripts default to 1)."""
        return max((self.weights.get(name, 1) for name in group), default=1)


class ScriptRun(BaseModel):
    """How one carto_sql script went: SUCCESS or FAILED (with the error),
    and its wall-clock seconds."""
    script: str
    status: str
    seconds: float
    error: Optional[str] = None


def run_timed_script(pg_config: PGConfig, script: Path, runs: List[ScriptRun]) -> None:
    """Runs one script, appending a ScriptRun to `runs` whether it succeeds
    or raises (the exception still propagates)."""
    started = time.monotonic()
    try:
        pg_config.runSQLScript(sql_script=script)
    except Exception as e:
        runs.append(ScriptRun(script=script.name, status=STATUS_FAILED, seconds=time.monotonic() - started, error=str(e)))
        raise
    runs.append(ScriptRun(script=script.name, status=STATUS_SUCCESS, seconds=time.monotonic() - started))


class CartoGroup(BaseModel):
    """One ordered list of carto_sql scripts that must run one after another.
    Each script opens its own connection from `pg_config`, so session state
    (SET, temp tables) doesn't carry from one script to the next.
    Independent CartoGroups run concurrently with each other -- see
    CartoProcessingModel._process_with_plan. `runs` collects a ScriptRun
    for each script run so far, including the one that failed.
    """
    model_config = ConfigDict(arbitrary_types_allowed=True)

    scripts: List[Path]
    pg_config: PGConfig
    runs: List[ScriptRun] = []

    @property
    def name(self) -> str:
        """Used by ParallelExecutor for per-task logging/reporting."""
        return "+".join(s.stem for s in self.scripts)

    def run(self) -> None:
        for script in self.scripts:
            run_timed_script(self.pg_config, script, self.runs)


class CartoProcessingModel(BaseModel):
    """
    Orchestrates carto_sql/*.sql execution against a PostgreSQL database.

    Attributes:
        sql_files: Every carto_sql/*.sql file, sorted (the historical,
            always-correct source of truth for "what should run" -- an
            execution_plan.yml is validated against this, not the reverse).
        pg_config: Database connection details.
        log_dir: Directory where logs should be stored.
        execution_plan_path: Optional path to execution_plan.yml. If it
            doesn't exist, or `concurrency` <= 1, falls back to running
            sql_files sequentially in order (today's behavior).
        concurrency: Maximum number of groups to run at once.
        script_runs: Filled in by process_sql: a ScriptRun for every script
            that ran, in plan order (prefix, groups in plan order, suffix),
            including one that failed. Scripts that never started (the rest
            of a failed group, or the suffix after a failed group) are
            absent.
    """
    sql_files: List[Path]
    pg_config: PGConfig
    log_dir: Path
    execution_plan_path: Optional[Path] = None
    concurrency: int = 1
    script_runs: List[ScriptRun] = []

    def process_sql(self):
        """
        Executes every carto_sql script, sequentially or via
        execution_plan.yml's prefix/groups/suffix structure -- see the
        module docstring.
        """
        self.script_runs.clear()
        plan = CartoExecutionPlan.load(self.execution_plan_path) if self.execution_plan_path else None
        if plan is None or self.concurrency <= 1:
            self._process_sequential()
            return
        self._process_with_plan(plan)

    def _process_sequential(self):
        for sql in tqdm(self.sql_files, desc="Processing Carto SQL"):
            run_timed_script(self.pg_config, sql, self.script_runs)

    def _resolve(self, filenames: List[str]) -> List[Path]:
        """Maps execution_plan.yml filenames to their actual Path in
        self.sql_files (the source of truth for what's actually present).
        """
        by_name = {p.name: p for p in self.sql_files}
        missing = [name for name in filenames if name not in by_name]
        if missing:
            raise FileNotFoundError(
                f"execution_plan.yml references {missing}, not found among this "
                f"--schema-dir's carto_sql/*.sql (renamed, removed, or .skip'd?)"
            )
        return [by_name[name] for name in filenames]

    def _validate_plan_covers_all_files(self, plan: CartoExecutionPlan) -> None:
        """Fails loudly if execution_plan.yml and carto_sql/*.sql have drifted
        apart, rather than silently skipping a script that's present on disk
        but missing from the plan (or vice versa).
        """
        plan_names = set(plan.prefix) | {n for group in plan.groups for n in group} | set(plan.suffix)
        actual_names = {p.name for p in self.sql_files}

        problems = []
        missing_from_plan = actual_names - plan_names
        if missing_from_plan:
            problems.append(
                f"present in --schema-dir's carto_sql/ but missing from execution_plan.yml "
                f"(would silently never run): {sorted(missing_from_plan)}"
            )
        missing_from_disk = plan_names - actual_names
        if missing_from_disk:
            problems.append(f"listed in execution_plan.yml but not found on disk: {sorted(missing_from_disk)}")

        all_listed = plan.prefix + [n for group in plan.groups for n in group] + plan.suffix
        duplicates = {name for name in all_listed if all_listed.count(name) > 1}
        if duplicates:
            problems.append(f"listed more than once across prefix/groups/suffix: {sorted(duplicates)}")

        group_names = {n for group in plan.groups for n in group}
        stray_weights = set(plan.weights) - group_names
        if stray_weights:
            problems.append(f"weights for scripts that aren't in any group: {sorted(stray_weights)}")

        if problems:
            raise ValueError(
                "execution_plan.yml is out of sync with carto_sql/*.sql -- " + "; ".join(problems)
            )

    def _create_schemas_and_extensions(self, plan: CartoExecutionPlan) -> None:
        for schema in plan.custom_schemas:
            if not _IDENTIFIER_RE.match(schema):
                raise ValueError(f"execution_plan.yml custom_schemas: invalid identifier {schema!r}")
            self.pg_config.execute_sql(
                f"CREATE SCHEMA IF NOT EXISTS {schema};", description=f"create schema {schema}"
            )
        for ext in plan.extensions:
            if not _IDENTIFIER_RE.match(ext):
                raise ValueError(f"execution_plan.yml extensions: invalid identifier {ext!r}")
            self.pg_config.execute_sql(
                f"CREATE EXTENSION IF NOT EXISTS {ext};", description=f"create extension {ext}"
            )

    def _group_pg_configs(self, plan: CartoExecutionPlan) -> List[PGConfig]:
        """One PGConfig per plan group, with the abt.dissolve_shards /
        abt.parallel_workers_per_gather custom GUCs (read by 003_road.sql,
        005a_water_polygon.sql, 009_land_cover.sql, 022_dam.sql) sized from
        the group's weighted share of the host, so concurrently-running
        groups don't collectively oversubscribe it -- see group_guc_values.
        This is a starting heuristic, not a precisely-derived optimum --
        tune via execution_plan.yml's weights, --carto-concurrency and the
        host's own postgresql.conf if a run under- or over-subscribes.
        """
        values = group_guc_values(
            weights=[plan.group_weight(group) for group in plan.groups],
            concurrency=self.concurrency,
            cpu_count=os.cpu_count() or 4,
        )
        return [
            self.pg_config.with_options(
                f"-c abt.dissolve_shards={dissolve_shards} "
                f"-c abt.parallel_workers_per_gather={parallel_workers_per_gather}"
            )
            for dissolve_shards, parallel_workers_per_gather in values
        ]

    def _process_with_plan(self, plan: CartoExecutionPlan) -> None:
        self._validate_plan_covers_all_files(plan)

        print(f"--- Creating {len(plan.custom_schemas)} custom schema(s) and {len(plan.extensions)} extension(s) ---")
        self._create_schemas_and_extensions(plan)

        print(f"--- Running {len(plan.prefix)} prefix script(s) sequentially ---")
        for sql in tqdm(self._resolve(plan.prefix), desc="Carto prefix"):
            run_timed_script(self.pg_config, sql, self.script_runs)

        group_script_lists = [self._resolve(group) for group in plan.groups]
        groups = [
            CartoGroup(scripts=scripts, pg_config=config)
            for scripts, config in zip(group_script_lists, self._group_pg_configs(plan))
        ]
        for group in groups:
            if plan.group_weight([s.name for s in group.scripts]) > 1:
                print(f"--- {group.name}: {group.pg_config.extra_options} ---")

        print(f"--- Running {len(groups)} carto group(s), up to {self.concurrency} concurrently ---")
        executor = ParallelExecutor(log_dir=self.log_dir, max_workers=self.concurrency, instance="carto_groups")
        results = executor.run(objects=groups, action=CartoGroup.run)
        for group in groups:
            self.script_runs.extend(group.runs)

        failures = [(name, data) for name, status, data in results if status != "SUCCESS"]
        if failures:
            summary = "; ".join(f"{name}: {err}" for name, err in failures)
            raise RuntimeError(
                f"{len(failures)} of {len(groups)} carto group(s) failed, suffix not run: {summary}"
            )

        print(f"--- All groups succeeded; running {len(plan.suffix)} suffix script(s) sequentially ---")
        for sql in tqdm(self._resolve(plan.suffix), desc="Carto suffix"):
            run_timed_script(self.pg_config, sql, self.script_runs)
