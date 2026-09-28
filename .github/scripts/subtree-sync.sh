#!/usr/bin/env bash
# Mirror one subtree of abt out to its standalone repo: abtv2-tools/ ->
# ReleasableBasemapTiles/abtv2-tools, rbt-schema/ -> ReleasableBasemapTiles/rbt-schema.
# abt is the source of truth; see docs/project/mirrors.md.
#
#   subtree-sync.sh check   <prefix> <base-rev>   report what HEAD would publish; never pushes
#   subtree-sync.sh publish <prefix>              fast-forward the mirror's main to HEAD's split
#
# `git subtree split` rebuilds <prefix>/'s history as a standalone repo,
# reusing the original upstream commits it was merged in from. It is
# deterministic, so the split of a later main descends from the split already
# pushed and the mirror only ever fast-forwards. A mirror main that isn't an
# ancestor of the split has commits abt doesn't -- that is reported and not
# published, unless SUBTREE_SYNC_OVERWRITE lists that exact commit: then
# publish force-pushes the split over it.
#
# Needs full history (fetch-depth: 0) and GNU coreutils. publish reads
# SUBTREE_SYNC_TOKEN; SUBTREE_SYNC_MIRROR_URL overrides the mirror URL (tests).
# Both modes read SUBTREE_SYNC_OVERWRITE: <prefix>@<sha> entries separated by
# whitespace, each naming a mirror main (at least 7 hex digits) to discard.
set -euo pipefail

usage() { echo "usage: $0 check <prefix> <base-rev> | publish <prefix>" >&2; exit 2; }
[[ $# -ge 2 ]] || usage
mode=$1 prefix=${2%/}
case $prefix in
  abtv2-tools | rbt-schema) ;;
  *) echo "::error::$prefix/ is not a mirrored subtree" >&2; exit 2 ;;
esac
slug="${GITHUB_REPOSITORY_OWNER:-ReleasableBasemapTiles}/$prefix"
url=${SUBTREE_SYNC_MIRROR_URL:-https://github.com/$slug.git}
summary=${GITHUB_STEP_SUMMARY:-/dev/null}
export GIT_TERMINAL_PROMPT=0

# Log a line and, under Actions, add it to the job summary. Every line starts
# with plain text, so a commit subject or path can't be read as a workflow
# command.
note() { echo "$*"; echo "$*" >>"$summary"; }
fail() { echo "::error title=$slug::$1"; echo "**Error:** $1" >>"$summary"; exit 1; }

# Validate every entry up front, so a typo fails the PR that adds it.
read -rd '' -a overwrite <<<"${SUBTREE_SYNC_OVERWRITE:-}" || true
for entry in "${overwrite[@]}"; do
  [[ $entry =~ ^(abtv2-tools|rbt-schema)@[0-9a-f]{7,40}$ ]] ||
    fail "SUBTREE_SYNC_OVERWRITE entry '$entry' isn't <dir>@<SHA of the mirror's main>, such as abtv2-tools@495cfbd."
done

# Signing would change the synthetic commits' SHAs (commit-tree honours
# commit.gpgSign), so a split made on a signing clone wouldn't match CI's.
split_of() { git -c commit.gpgsign=false subtree split -q --prefix="$prefix" "$1"; }

git rev-parse -q --verify "HEAD:$prefix" >/dev/null ||
  fail "HEAD has no $prefix/. Renaming or removing a mirrored directory needs a manual re-bootstrap of the mirror."
split=$(split_of HEAD)
note "### \`$prefix/\` → $slug"
note "Split of HEAD: \`${split:0:7}\` ($(git version))"

# Fetch the mirror's main into refs/subtree-sync/<prefix>; "$@" adds auth.
fetch_mirror() {
  git "$@" fetch -q --no-tags "$url" "+refs/heads/main:refs/subtree-sync/$prefix" &&
    mirror=$(git rev-parse "refs/subtree-sync/$prefix")
}

# Stop before publishing any commit that also belongs to abt's own history.
# Every new commit should be a synthetic split commit; an abt commit here
# means git subtree mapped a commit without <prefix>/ (deleted, then
# restored) to itself, and pushing would copy all of abt into the mirror.
guard_leak() {
  local new ours
  new=$(git rev-list --count "$split" "^$mirror")
  ours=$(git rev-list --count "$split" "^$mirror" ^HEAD)
  [[ $new == "$ours" ]] ||
    fail "the split of $prefix/ contains $((new - ours)) commit(s) from abt's own history (was $prefix/ deleted and restored?). Not publishing."
}

# True if SUBTREE_SYNC_OVERWRITE lists the mirror's current main.
overwrite_listed() {
  local entry
  for entry in "${overwrite[@]}"; do
    [[ ${entry%@*} == "$prefix" && $mirror == "${entry#*@}"* ]] && return 0
  done
  return 1
}

# List the mirror-only commits that overwriting the mirror's main drops.
# $1 says who does it, e.g. "Force-pushed".
discarding() {
  local n
  n=$(git rev-list --count "$split..$mirror")
  echo "::warning title=$slug main is listed in SUBTREE_SYNC_OVERWRITE::$1 over $slug main ($mirror), discarding $n commit(s) that abt doesn't have."
  note "**$1 over $slug main (\`$mirror\`), discarding $n commit(s):**"
  git log --format="- \`%h\` %s" "$split..$mirror" >>"$summary"
  git log --format='  discarded: %h %s' "$split..$mirror"
}

diverged() {
  echo "::error title=$slug has diverged::$slug main (${mirror:0:7}) has commits abt's $prefix/ doesn't. Bring them in with git subtree pull (or git merge -s ours if already ported) and merge that PR with a merge commit, or discard them by adding $prefix@${mirror:0:7} to SUBTREE_SYNC_OVERWRITE. See docs/project/mirrors.md."
  note "**$slug main (\`$mirror\`) has commits that abt doesn't:**"
  git log --format="- \`%h\` %s" "$split..$mirror" >>"$summary"
  git log --format='  mirror-only: %h %s' "$split..$mirror"
  exit 1
}

case $mode in
check)
  [[ $# -eq 3 ]] || usage
  for entry in "${overwrite[@]}"; do
    if [[ ${entry%@*} == "$prefix" ]]; then
      note "SUBTREE_SYNC_OVERWRITE lists \`$entry\`: publish force-pushes over $slug main while it is still \`${entry#*@}\`."
    fi
  done
  base_split=$(split_of "$3")
  if [[ $base_split == "$split" ]]; then
    note "Merging this publishes nothing to $slug."
    exit 0
  fi
  if git diff --quiet "$base_split" "$split"; then
    note "Merging this adds history to $slug without changing any files."
  else
    note "Merging this changes these files in $slug:"
    { echo '```'; git diff --stat "$base_split" "$split"; echo '```'; } | tee -a "$summary"
  fi
  # New split commits that are also abt commits came in from the mirror
  # (git subtree pull, merge -s ours). Only a merge commit keeps them.
  inbound=$(($(git rev-list --count "$split" "^$base_split") - $(git rev-list --count "$split" "^$base_split" ^HEAD)))
  if ((inbound > 0)); then
    echo "::warning title=Merge with \"Create a merge commit\"::this PR brings $inbound commit(s) of $slug history into $prefix/. Squash or rebase would drop them and the next publish would be rejected."
    note "**Merge with \"Create a merge commit\":** this PR brings $inbound commit(s) of $slug history into \`$prefix/\`; squash or rebase would drop them."
  fi

  # Relative links that climb out of the subtree 404 in the mirror.
  while IFS=: read -r file line target; do
    resolved=$(realpath -m --relative-to=. "$(dirname "$file")/$target")
    [[ $resolved == "$prefix" || $resolved == "$prefix"/* ]] ||
      echo "::warning file=$file,line=$line::link to $target leaves $prefix/ and will 404 in $slug"
  done < <(grep -rnoE --include='*.md' '\]\((\.\./)+[^)#[:space:]]*' "$prefix" | sed 's/:\](/:/' || true)
  cmp -s LICENSE "$prefix/LICENSE" ||
    echo "::warning file=$prefix/LICENSE::$prefix/LICENSE should be a copy of the root LICENSE"
  if git rev-parse -q --verify "HEAD:$prefix/.github/workflows" >/dev/null; then
    echo "::warning::$prefix/.github/workflows/ can only be pushed to $slug if SUBTREE_SYNC_TOKEN has Workflows: write"
  fi

  if ! fetch_mirror 2>/dev/null; then
    echo "::warning::couldn't read $slug anonymously; skipping the divergence check (publish still checks on main)"
    exit 0
  fi
  # A re-run keeps its original merge ref, which may predate a later publish
  # of main; main's own split descending from the mirror is just as good.
  if ! git merge-base --is-ancestor "$mirror" "$split"; then
    main=$(git rev-parse -q --verify origin/main) || main=
    if [[ -z $main ]] || ! git merge-base --is-ancestor "$mirror" "$(split_of "$main")"; then
      overwrite_listed || diverged
      guard_leak
      discarding "The publish after merging force-pushes"
      exit 0
    fi
  fi
  guard_leak
  note "$slug main (\`${mirror:0:7}\`) is an ancestor of this split, so the publish after merging will fast-forward."
  ;;

publish)
  [[ $# -eq 2 ]] || usage
  auth=()
  if [[ -z ${SUBTREE_SYNC_MIRROR_URL:-} ]]; then
    [[ -n ${SUBTREE_SYNC_TOKEN:-} ]] ||
      fail "SUBTREE_SYNC_TOKEN is not set; it belongs in the subtree-sync environment (docs/project/mirrors.md)."
    # Hand the token to git through a credential helper that reads it from
    # the environment, so it never lands in argv, .git/config, or a URL.
    # shellcheck disable=SC2016
    auth=(-c credential.helper= -c 'credential.helper=!f() { test "$1" = get && echo username=x-access-token && echo "password=$SUBTREE_SYNC_TOKEN"; }; f')
  fi
  fetch_mirror "${auth[@]}"
  if [[ $mirror == "$split" ]]; then
    note "$slug main is already at \`${split:0:7}\`."
    exit 0
  fi
  lease=()
  if ! git merge-base --is-ancestor "$mirror" "$split"; then
    if overwrite_listed; then
      # The lease fails the push if main has moved since the fetch.
      lease=("--force-with-lease=refs/heads/main:$mirror")
    elif git merge-base --is-ancestor "$split" "$mirror"; then
      note "$slug main (\`${mirror:0:7}\`) is already ahead of this split; a newer run published it."
      exit 0
    else
      diverged
    fi
  fi
  guard_leak
  n=$(git rev-list --count "$split" "^$mirror")
  git "${auth[@]}" push -q "${lease[@]}" "$url" "$split:refs/heads/main" ||
    fail "push to $slug was rejected. Check that SUBTREE_SYNC_TOKEN hasn't expired, has Contents: write on $slug, and that its owner can always bypass the mirror's main ruleset (for an overwrite, that includes Block force pushes)."
  if ((${#lease[@]})); then
    discarding "Force-pushed"
    note "Published $n commit(s) to $slug main: \`${split:0:7}\` replaces \`${mirror:0:7}\`."
  else
    note "Published $n commit(s) to $slug main: \`${mirror:0:7}..${split:0:7}\`."
  fi
  ;;

*) usage ;;
esac
