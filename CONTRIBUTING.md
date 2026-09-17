# Contributing

This repository keeps [CHANGELOG.md](CHANGELOG.md) in [Keep a Changelog](https://keepachangelog.com/en/1.0.0/) form. [git-cliff](https://git-cliff.org/) regenerates that file on every push to `main` and on every `v*` tag, from **Conventional Commits**.

## Commit and pull request titles

Use [Conventional Commits](https://www.conventionalcommits.org/en/v1.0.0/):

```text
type(scope): short description
```

`type` is one of `feat`, `fix`, `docs`, `style`, `refactor`, `perf`, `test`, `build`, `ci`, `chore`, `revert`. `scope` is optional (`init`, `overture`, `schema`, `bundler`, `vundler`, `docs`, `ci`, …).

Examples:

```text
feat(init): add --from export flag for existing mbtiles
fix(overture): raise open-file limit before invoking tippecanoe
docs: add MkDocs documentation site
chore(ci): add git-cliff changelog workflow
```

Breaking changes use a `!` after the type/scope (`feat!: ...`) or a `BREAKING CHANGE:` footer. Those show up in the changelog as **breaking**.

CI rejects pull requests whose title or commits do not match this format (`Lint PR`). Merge commits and `chore(changelog):` commits are ignored.

## Prefer squash merge

Squash-merging uses the **PR title** as the commit on `main`, which is the line git-cliff will publish. If you merge with a merge commit instead, keep every commit on the branch conventional — git-cliff skips `Merge pull request` lines.

## Changelog updates

Do not edit `CHANGELOG.md` by hand for ordinary work. After merge (or after you push a `v*` tag), the Changelog workflow rewrites the file and commits `chore(changelog): update CHANGELOG.md [skip ci]`.

GitHub Releases are still created by hand (`gh release create`). Repo tags like `v1.0.0` become changelog versions. This repository has no `v*` tags yet, so `CHANGELOG.md` is an `[Unreleased]` history until the first one is cut.

## Local commit-msg hook (optional)

To reject non-conventional commits before they reach GitHub:

```bash
git config core.hooksPath .githooks
```

That only affects this clone. It does not change your global Git config.

## Tests and docs

See [docs/project/contributing.md](docs/project/contributing.md) for how to run the `abtv2-tools` and `vundler-rs` test suites, and [docs/project/testing.md](docs/project/testing.md) for what they cover.
