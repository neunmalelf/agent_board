# Development

This page is the developer entry point; the authoritative rules live in
`.agentrules` and the entry file for coding agents is `AGENTS.md`.

## Checks

```sh
./_tests            # pytest + ruff + mypy (full gate)
./_tests --quick    # pytest only
./_check_version    # pyproject <-> package version stamp sync
```

The git pre-commit hook (`hooks/pre-commit`) runs the same checks on every
commit (pytest quick mode + ruff + mypy + version stamps). Install it once
with `bash hooks/install.sh` (also done by `./_install`); re-run after
editing the hook. Single modules: `hooks/pre-commit --list-modules`,
`hooks/pre-commit --run=ruff`. Skip single modules with `SKIP_TESTS=1 git
commit` or bypass everything with `SKIP_HOOKS=1`.

## Scripts

| Script | Purpose |
|--------|---------|
| `./_tests` | pytest + ruff + mypy check suite (`--quick` skips static checks) |
| `_run` | run the TUI / one-shot frame / note CLI from a bare checkout |
| `_menu` | interactive helper menu (install/test/build/git/run) |
| `_git` | interactive commit with UTC-timestamp prefix, optional push |
| `_install` | `pip install -e .` + pre-commit hook wiring |
| `_build` | metadata + version-stamp validation (no artifacts by design) |
| `_docs` | build MkDocs docs into `site/` (requires `uv` + docs group) |
| `_check_version` | verify version stamps agree across pyproject and package |

## Versioning

`Major.Minor.YYYYMMDDhhmmssZ` (14-digit UTC timestamp, trailing `Z`). The
stamp lives in `pyproject.toml [project] version` and in
`src/agent_board/board.py __version__` (they must match exactly);
`src/agent_board/watch.py` carries its own Major.Minor with the same
timestamp. Every helper script carries its own `__VERSION__` stamp. Bump on
every material change, before the commit (see history rules).

## History rules

1. `history.md` (repo root) is the release log: newest entry on top, one
   entry per version bump, written before the release commit. The latest
   entry doubles as the release notes.
2. `history/` is the working archive: `prompts/` (prompt/session logs),
   `changes/` (change summaries), `todo/` (todo.md snapshots),
   `plans/` (plan.md snapshots), `tests/` (test reports), `ideas/`,
   `goals/`. Archive with a unified `YYYYMMDDThhmmss` timestamp in the
   filename; never delete archived files.
3. Decisions (e.g. tooling choices) get their own dated entry in
   `history.md`, including the reasoning and the rejected alternatives.