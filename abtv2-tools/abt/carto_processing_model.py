"""
carto_processing_model.py

Defines the models responsible for executing carto_sql/*.sql against a
PostgreSQL database. By default (or if the schema dir has no
execution_plan.yml), scripts run one at a time in filename order, as they
always have. When execution_plan.yml is present and concurrency > 1, scripts
run in three phases instead:

  1. prefix    -- sequential (e.g. 000_update_aux_geom.sql, 001_set_schema.sql)
  2. groups    -- each group's scripts run in order on their own connection;
                  independent groups run concurrently with each other
  3. suffix    -- sequential, only if every group succeeded (e.g. 099_update_geometry.sql)

See rbt-schema/carto_sql/execution_plan.yml for the full format and the
dependency analysis behind today's grouping.
"""

import os
import re
from pathlib import Path
from typing import List, Optional

import yaml
from pydantic import BaseModel, ConfigDict
from tqdm import tqdm

from .parallel import ParallelExecutor
from .utils.pg_config import PGConfig

_IDENTIFIER_RE = re.compile(r"^[a-z_][a-z0-9_]*$")


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
            order, sequentially, on one connection. Different groups run
            concurrently with each other.
        suffix: Filenames to run sequentially, in order, after every group
            has completed successfully.
    """
    custom_schemas: List[str] = []
    extensions: List[str] = []
    prefix: List[str] = []
    groups: List[List[str]] = []
    suffix: List[str] = []

    @classmethod
    def load(cls, path: Path) -> Optional["CartoExecutionPlan"]:
        """Returns None if `path` doesn't exist, so callers can fall back to
        fully sequential execution for a --schema-dir that predates this
        file (or simply doesn't want concurrent carto execution).
        """
        if not path.exists():
            return None
        raw = yaml.safe_load(path.read_text()) or {}
        return cls(**{field: raw.get(field, []) for field in cls.model_fields})


class CartoGroup(BaseModel):
    """One ordered list of carto_sql scripts that must run sequentially on a
    single connection. Independent CartoGroups run concurrently with each
    other -- see CartoProcessingModel._process_with_plan.
    """
    model_config = ConfigDict(arbitrary_types_allowed=True)

    scripts: List[Path]
    pg_config: PGConfig

    @property
    def name(self) -> str:
        """Used by ParallelExecutor for per-task logging/reporting."""
        return "+".join(s.stem for s in self.scripts)

    def run(self) -> None:
        for script in self.scripts:
            self.pg_config.runSQLScript(sql_script=script)


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
    """
    sql_files: List[Path]
    pg_config: PGConfig
    log_dir: Path
    execution_plan_path: Optional[Path] = None
    concurrency: int = 1

    def process_sql(self):
        """
        Executes every carto_sql script, sequentially or via
        execution_plan.yml's prefix/groups/suffix structure -- see the
        module docstring.
        """
        plan = CartoExecutionPlan.load(self.execution_plan_path) if self.execution_plan_path else None
        if plan is None or self.concurrency <= 1:
            self._process_sequential()
            return
        self._process_with_plan(plan)

    def _process_sequential(self):
        for sql in tqdm(self.sql_files, desc="Processing Carto SQL"):
            self.pg_config.runSQLScript(sql_script=sql)

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

    def _scaled_pg_config(self, num_groups: int) -> PGConfig:
        """Derives a PGConfig for concurrent groups' connections, with the
        abt.dissolve_shards / abt.parallel_workers_per_gather custom GUCs
        (read by 003_road.sql, 005a_water_polygon.sql, 009_land_cover.sql,
        022_dam.sql) scaled down so `num_groups` concurrently-running groups
        don't collectively oversubscribe the host. This is a starting
        heuristic, not a precisely-derived optimum -- tune via
        --carto-concurrency and the host's own postgresql.conf if a
        particular run under- or over-subscribes.
        """
        cpu_count = os.cpu_count() or 4
        budget = max(cpu_count - 4, cpu_count // 2)  # leave headroom for the OS/other backends
        per_group = max(1, budget // max(num_groups, 1))
        dissolve_shards = max(2, per_group)
        parallel_workers_per_gather = max(2, per_group // 4)
        return self.pg_config.with_options(
            f"-c abt.dissolve_shards={dissolve_shards} "
            f"-c abt.parallel_workers_per_gather={parallel_workers_per_gather}"
        )

    def _process_with_plan(self, plan: CartoExecutionPlan) -> None:
        self._validate_plan_covers_all_files(plan)

        print(f"--- Creating {len(plan.custom_schemas)} custom schema(s) and {len(plan.extensions)} extension(s) ---")
        self._create_schemas_and_extensions(plan)

        print(f"--- Running {len(plan.prefix)} prefix script(s) sequentially ---")
        for sql in tqdm(self._resolve(plan.prefix), desc="Carto prefix"):
            self.pg_config.runSQLScript(sql_script=sql)

        group_script_lists = [self._resolve(group) for group in plan.groups]
        scaled_config = self._scaled_pg_config(num_groups=min(len(group_script_lists), self.concurrency) or 1)
        groups = [CartoGroup(scripts=scripts, pg_config=scaled_config) for scripts in group_script_lists]

        print(f"--- Running {len(groups)} carto group(s), up to {self.concurrency} concurrently ---")
        executor = ParallelExecutor(log_dir=self.log_dir, max_workers=self.concurrency, instance="carto_groups")
        results = executor.run(objects=groups, action=CartoGroup.run)

        failures = [(name, data) for name, status, data in results if status != "SUCCESS"]
        if failures:
            summary = "; ".join(f"{name}: {err}" for name, err in failures)
            raise RuntimeError(
                f"{len(failures)} of {len(groups)} carto group(s) failed, suffix not run: {summary}"
            )

        print(f"--- All groups succeeded; running {len(plan.suffix)} suffix script(s) sequentially ---")
        for sql in tqdm(self._resolve(plan.suffix), desc="Carto suffix"):
            self.pg_config.runSQLScript(sql_script=sql)
