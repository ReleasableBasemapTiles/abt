# Upstream Mirrors

abt is the source of truth for both halves of the pipeline. Each half is also published, with its history, as a standalone repository:

| Directory in abt | Mirror |
|---|---|
| `abtv2-tools/` | [ReleasableBasemapTiles/abtv2-tools](https://github.com/ReleasableBasemapTiles/abtv2-tools) |
| `rbt-schema/` | [ReleasableBasemapTiles/rbt-schema](https://github.com/ReleasableBasemapTiles/rbt-schema) |

The **Subtree sync** workflow keeps each mirror's `main` in step with abt's `main`. On a pull request it reports what merging would publish, and after the merge it pushes the result. Nobody pushes to a mirror by hand.

!!! warning "Change it in abt, not in the mirror"
    Open issues and pull requests against abt. A commit pushed straight to a mirror's `main` stops the sync for that mirror until the commit has been brought into abt or discarded. See [When a mirror has diverged](#when-a-mirror-has-diverged).

## How it works

Both directories are unsquashed git subtrees. `git subtree add` merged each upstream repository's history into abt (`5a7e3a1` for `abtv2-tools/`, `647cae8` for `rbt-schema/`), and `f09c5c7` later pulled in more `rbt-schema` commits.

`git subtree split --prefix=<dir>` turns that history back into a standalone repository: one commit for each abt commit that changed `<dir>/`, with `<dir>/` as the root. It reuses the original upstream commits instead of rewriting them, and it produces the same commit IDs every time it runs. The split of a later `main` therefore always builds on the split already pushed, and a mirror only ever fast-forwards, unless a pull request [discards commits](#discard-the-commits) that were pushed to it directly.

[`.github/scripts/subtree-sync.sh`](https://github.com/ReleasableBasemapTiles/abt/blob/main/.github/scripts/subtree-sync.sh) does the work in two modes. [`.github/workflows/subtree-sync.yml`](https://github.com/ReleasableBasemapTiles/abt/blob/main/.github/workflows/subtree-sync.yml) runs each mode once per mirror.

**Check** runs on every pull request. It splits the pull request's merge commit and the base it was merged onto, then lists in the job summary the files that merging would change in the mirror. Next it fetches the mirror's `main` and **fails** if the mirror has commits abt doesn't. If `SUBTREE_SYNC_OVERWRITE` lists the mirror's `main` to be [discarded](#discard-the-commits), it reports what publish will discard instead. It also warns about:

- relative links in the directory's Markdown that climb out of it (`../docs/...`), because they 404 in the mirror;
- a `LICENSE` that is no longer an exact copy of the root one;
- a pull request that brings mirror history in, which must be merged with **Create a merge commit** (see [below](#when-a-mirror-has-diverged));
- a `.github/workflows/` directory inside a mirrored directory, which the token can only push with an extra permission (see [Setup](#setup)).

Check uses no secrets, so pull requests from forks get it too. When a pull request doesn't change a directory, its check passes without looking at the mirror at all, so it is safe to make **Check abtv2-tools** and **Check rbt-schema** required status checks. If a mirror is private, the anonymous fetch fails. The check then warns and skips the divergence test, and publish still compares before it pushes.

**Publish** runs on every push to `main`, nightly at 06:37 UTC, and on demand (Actions → Subtree sync → Run workflow). It splits the tip of `main`, fetches the mirror's `main`, and then:

| When the mirror's `main` is… | Publish… |
|---|---|
| the same as the split | does nothing |
| behind the split | pushes the split to `main` as a fast-forward |
| any other commit listed in `SUBTREE_SYNC_OVERWRITE` | force-pushes the split over it, with a lease on that commit, and lists the commits it discarded |
| ahead of the split (a newer run already published) | does nothing |
| neither (it has commits abt doesn't) | fails, lists the mirror-only commits, and pushes nothing |

Publish also refuses to push a split that contains commits from abt's own history. `git subtree split` produces one if a directory is deleted and later restored, and pushing it would copy all of abt into the mirror.

The nightly run is the same job, so it also catches up anything a failed run left behind and flags a mirror that has moved on its own.

??? example "The workflow"

    ```yaml
    --8<-- ".github/workflows/subtree-sync.yml"
    ```

## Setup

A repository admin does this once. These are settings, not files, so none of it can be done in a pull request.

### 1. A token that can push to the mirrors

Create a [fine-grained personal access token](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/managing-your-personal-access-tokens):

- **Resource owner:** `ReleasableBasemapTiles`. If the organization requires approval for fine-grained tokens, an organization owner has to approve it.
- **Repository access:** Only select repositories, then `abtv2-tools` and `rbt-schema`. The token needs no access to abt itself.
- **Permissions:** Contents: **Read and write**. Metadata: Read-only is added automatically. Add Workflows: Read and write only if a mirrored directory ever gains a `.github/workflows/` directory.
- **Expiration:** as long as the organization allows. Set a reminder to rotate the token before it expires; an expired token makes publish fail with a hint to check it.

Issue the token from a dedicated machine account in the organization rather than a person's account, so the sync doesn't stop when that person leaves.

### 2. A `subtree-sync` environment in abt

In abt, open Settings → Environments → **New environment** and name it `subtree-sync`:

- **Deployment branches and tags:** choose Selected branches and tags and add `main`. A workflow edited on a pull request branch then can't read the secret.
- **Environment secrets:** add `SUBTREE_SYNC_TOKEN` with the token from step 1.
- Leave **Required reviewers** off, or every merge waits for someone to approve its publish.

!!! warning "Create the environment before the workflow first runs"
    If a workflow names an environment that doesn't exist, GitHub creates it with no restrictions. If the workflow ran before the environment was set up, check the deployment branch rule before you add the secret.

### 3. Lock down each mirror's `main`

In each mirror, open Settings → Rules → Rulesets → New branch ruleset. Target the default branch and set enforcement to **Active**:

- Turn on **Restrict updates**, **Restrict deletions**, and **Block force pushes**.
- Under **Bypass list**, add a team that holds only the token owner (or failing that, the token owner's role, such as Repository admin) with **Always allow**. Publish pushes directly, not through a pull request. The bypass also lets publish force-push when it [discards a mirror's commits](#discard-the-commits).
- Leave **Require linear history** off, because the split history contains merges. Leave **Require signed commits** off, because split commits are created fresh and are unsigned.

Organization rulesets that cover every repository, such as rules on file paths, extensions, or sizes, apply to the mirrors too, and to every commit in the history that publish pushes. Either exclude the mirrors from them or give the token owner a bypass.

It also helps to point each mirror's description at abt and to turn off Issues, Discussions, and the Wiki there. Don't archive a mirror, because archived repositories reject pushes.

### 4. Bring in commits a mirror already has

Before the first publish, each mirror's `main` must be an ancestor of abt's split. For `abtv2-tools` this isn't the case: five upstream commits, the `--max-zoom` bundler flag, were copied into abt by hand in [pull request #2](https://github.com/ReleasableBasemapTiles/abt/pull/2) instead of being merged. For `rbt-schema`, abt has everything up to `3cca358`, the last commit pulled in; whether the mirror has moved on since then is unknown.

The pull request check can't read a private mirror, so check each one from a clone that can:

```bash
split() { git -c commit.gpgsign=false subtree split -q --prefix="$1" "$2"; }
for dir in abtv2-tools rbt-schema; do
  git fetch -q "https://github.com/ReleasableBasemapTiles/$dir.git" main
  echo "$dir main has these commits that abt doesn't:"
  git log --oneline "$(split "$dir" origin/main)..FETCH_HEAD"
done
```

An empty list means the first publish will fast-forward. Reconcile any mirror that lists commits, as described in [When a mirror has diverged](#when-a-mirror-has-diverged). Until then, its publish fails without pushing anything.

### 5. First publish

Publish runs on the next push to `main`. It can also be started from Actions → Subtree sync → Run workflow. The first run pushes each directory's full abt-era history. Each job's summary names the range it pushed. Afterwards, the mirror's `main` is the same commit as `git subtree split -q --prefix=<dir> origin/main` run in a local clone.

## When a mirror has diverged

A check or publish that fails with **has diverged** names the mirror's `main` and lists the commits that the mirror has and abt doesn't. Until they are brought into abt or discarded, publish pushes nothing to that mirror.

### Bring the commits into abt

Bring them into abt in a pull request, then merge that pull request with **Create a merge commit**. Squash and rebase both drop the mirror's commits, and the next publish would fail again.

The commands below use this helper. `commit.gpgsign=false` keeps `git subtree split` from asking to sign each commit it creates:

```bash
split() { git -c commit.gpgsign=false subtree split -q --prefix="$1" "$2"; }
```

**If abt already has their changes** (they were copied in by hand, as in pull request #2), merge them without changing any files:

```bash
git fetch https://github.com/ReleasableBasemapTiles/abtv2-tools.git main
git log --oneline "$(split abtv2-tools origin/main)..FETCH_HEAD"   # only the commits you expect?
git switch -c chore/reconcile-abtv2-tools-mirror origin/main
git merge -s ours --no-ff FETCH_HEAD -m "Merge abtv2-tools mirror main (already ported in #2)"
git merge-base --is-ancestor FETCH_HEAD "$(split abtv2-tools HEAD)" && echo "publish will fast-forward"
```

**If they have changes abt doesn't**, pull them in and resolve any conflicts, as [pull request #1](https://github.com/ReleasableBasemapTiles/abt/pull/1) did:

```bash
git switch -c chore/pull-rbt-schema-mirror origin/main
git subtree pull --prefix=rbt-schema https://github.com/ReleasableBasemapTiles/rbt-schema.git main
```

In both cases:

- The mirror's commits come in unchanged, because rewording them would change their IDs and the mirror would still have commits abt doesn't. If they aren't Conventional Commits, Lint PR's commit check fails, and an admin has to merge past it if that check is required. The merge commit's own message starts with `Merge `, which Lint PR and git-cliff both skip.
- git-cliff would list the mirror's commits under **Unreleased**. If abt already has their changes, add their full IDs to [`.cliffignore`](https://git-cliff.org/docs/usage/skipping-commits) in the same pull request:

    ```bash
    git log --no-merges --format=%H "$(split abtv2-tools origin/main)..FETCH_HEAD" >> .cliffignore
    ```

- The pull request's own check reports the history it adds and warns that it must be merged with a merge commit. After the merge, the next publish fast-forwards the mirror.

### Discard the commits

If abt doesn't need the mirror's commits, because their changes were copied into abt by hand or aren't wanted, publish can overwrite the mirror's `main` instead. Bring in any commit whose changes abt should keep, because discarding loses it.

In a pull request, add the mirror's `main` to `SUBTREE_SYNC_OVERWRITE` at the top of [the workflow](https://github.com/ReleasableBasemapTiles/abt/blob/main/.github/workflows/subtree-sync.yml), as `<dir>@<SHA>`. Take the SHA from the failed run; its first 7 characters are enough. Separate several entries with spaces:

```yaml
env:
  SUBTREE_SYNC_OVERWRITE: abtv2-tools@495cfbd
```

- While the mirror's `main` is still that commit, publish force-pushes the split over it. The push carries a lease on the commit that publish fetched, so if anything is pushed to the mirror in the meantime, publish fails instead of discarding it.
- The job summary lists the discarded commits and the full SHA of the old `main`. When the check can read the mirror, it reports what publish will discard instead of failing.
- The token owner must be able to force-push to the mirror's `main`. The bypass from [Setup step 3](#3-lock-down-each-mirrors-main) covers it.
- Clones of the mirror have to be reset to the new `main`.
- Once publish has run, the entry no longer matches, so it does nothing. Remove it in a later pull request.

## Working in the mirrored directories

- **Don't rename, move, or delete `abtv2-tools/` or `rbt-schema/`.** Publish stops with an error, and the mirror then has to be set up again by hand. Deleting a directory and restoring it later has the same effect.
- **Keep links inside the directory.** A relative link that leaves it works in abt but 404s in the mirror. Link to abt's files with `https://github.com/ReleasableBasemapTiles/abt/blob/main/...` and to this site with `https://ReleasableBasemapTiles.github.io/abt/...`. The check flags any it finds.
- **Keep the license files in step.** `abtv2-tools/LICENSE` and `rbt-schema/LICENSE` are exact copies of the root `LICENSE`. Each directory's `NOTICE` carries the parts of the root `NOTICE` that apply to it. Change them together.
- **Squash merge is fine** for ordinary pull requests. Only a pull request that brings mirror history in needs **Create a merge commit**, and its check says so.
- **Mind file sizes.** Everything in a directory's history is pushed to its mirror, so GitHub's 100 MB file limit and any organization file rules apply there too.

## Running the check locally

```bash
bash .github/scripts/subtree-sync.sh check abtv2-tools origin/main
bash .github/scripts/subtree-sync.sh check rbt-schema origin/main
```

Each command reports what the checked-out commit would publish compared with `origin/main`, and never pushes. It needs a full clone (not `--depth`) and `git subtree`, which ships with Git on most platforms. It also needs GNU `realpath`; on macOS, install Homebrew's `coreutils` and put its `gnubin` directory first on `PATH`. It compares against a mirror only when the checked-out commit changes that directory. It fetches with your own Git credentials, so a private mirror you can read is compared too.

## Known limitations

- Commit messages that mention an abt pull request, such as a squash merge's `(#123)` or `Merge pull request #123`, link to the mirror's own #123 there, not abt's.
- Tags and releases aren't mirrored.
- GitHub disables scheduled workflows in a public repository after 60 days without activity. If abt were public and went idle, the nightly run would stop; pushes to `main` would still publish.
- The sync relies on `git subtree split` producing the same commits on every run. If a future Git release changed that, publish would report the mirror as diverged and push nothing. Reconciling with `git merge -s ours` as above would fix it.
