#!/usr/bin/env bash
# lock.sh
#
# Shared flock helper for the Overture pipeline. Sourced by fetch.sh and
# tile.sh (never invoked directly) to guard against two pipelines writing
# into the same data dir at once -- e.g. a run started twice by hand, or an
# orphaned background job left over from an init.sh invocation that aborted
# elsewhere (see init.sh's own cleanup trap, which exists specifically to
# prevent that). shard.sh's per-process temp paths (see shard.sh) only stop
# two writers from destroying *each other's* in-progress files -- they don't
# stop fetch.sh's "already done" skip check, or tile.sh reading a parts dir
# that's still being written into, from racing.
#
# Usage: acquire_overture_lock <data_dir> <exclusive|shared>
#
# Fails fast (no waiting, no retry) rather than blocking: an operator who
# accidentally starts a second run should see an immediate, actionable
# error naming the PID that's already holding the lock, not a pipeline that
# silently hangs or interleaves with another one.
#
# The lock is released by the kernel the moment this process exits, by any
# means (including SIGKILL) -- there is deliberately no pidfile or stale-
# lock cleanup to get out of sync with reality.
acquire_overture_lock() {
  local outdir="$1" mode="$2" flag lock_file holder

  case "$mode" in
    exclusive) flag=-x ;;
    shared) flag=-s ;;
    *)
      echo "ERROR: acquire_overture_lock: mode must be 'exclusive' or 'shared', got '${mode:-}'" >&2
      exit 1
      ;;
  esac

  mkdir -p "$outdir"
  lock_file="$outdir/.lock"

  # <> (read-write, no truncate) rather than > : a failed acquire below
  # still needs to read the *previous* holder's PID out of this file, and
  # `exec 9>` would truncate it away before we ever got to look.
  exec 9<>"$lock_file"

  if ! flock -n "$flag" 9; then
    holder="$(cat "$lock_file" 2>/dev/null || true)"
    echo "ERROR: could not acquire the ${mode} lock on '${outdir}' (held by PID ${holder:-unknown})." >&2
    echo "       A concurrent fetch.sh/tile.sh run against this data dir corrupts its parts/*.fgb shards." >&2
    echo "       See the 'Concurrency' section of rbt-schema/scripts/overture/README.md." >&2
    exit 1
  fi

  # Held from here on -- record our own PID so a *future* failed acquire
  # can name us as the holder.
  truncate -s 0 "$lock_file"
  echo "$$" >&9
}
