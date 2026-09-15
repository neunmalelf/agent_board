# ChangeLog

All notable changes, newest first. Versions are
`Major.Minor.<14-digit UTC stamp>Z` (stamps in commit messages and
`src/agent_board/` `__version__`). Detailed reasoning, decisions, and
release notes live in `history.md`; user-facing highlights in `NEWS.md`.

## 2.4.20260915172753Z - 2026-09-15

- README: "Platforms" section (Linux supported; macOS partial - no
  `/proc`, no systemd; Windows via WSL2) and "man + tldr pages" install
  block.
- README: note on custom-reported agents (freebuff) in the Columns
  section.
- Fixed stale pre-restructure `~/projects/agent-watcher/` paths in
  `tldr/agent-watcher.md` and `man/agent-watcher.1`.
- view-compact: left column's agent rows draw one space in (`run_tui`
  compact path; full frame blocks unchanged).
- `AGENT_BADGE` gains `"freebuff": ("FB", ())`; `clean_title` drops a
  leading `Freebuff:` brand label, so herdr custom-reported freebuff
  agents render like every other agent column.
- agent-watch version 1.2 → 1.3 with the release stamp.

## 2.3.20260913092333Z - 2026-09-13

- src/ layout: implementation moved into `src/agent_board/`
  (`board.py`, `watch.py`); root-level `agent_board.py` /
  `agent_watch.py` are thin launcher shims.
- PEP 621 `pyproject.toml` (setuptools), console scripts `agent-board` /
  `agent-watch`, ruff + mypy + pytest config; runtime stays stdlib-only
  (`dependencies = []`).
- Packaging version carries the stamp without the trailing Z (PEP 440);
  `_check_version` enforces the pairing.
- Helper scripts: `_tests`, `_run`, `_menu`, `_git`, `_install`,
  `_build`, `_docs`, `_check_version`.
- Modular pre-commit hook (`hooks/pre-commit` + `hooks/install.sh`)
  gating version stamps, ruff, mypy, and the quick test suite.
- Docs: `README.md`, `docs/` + MkDocs, `AGENTS.md`, `.agentrules`, MIT
  `LICENSE`, `requirements-dev.txt`, `.gitattributes` (LF).
- Fixes: `agent_board` wrapper installed a wrong unit filename;
  agent-watch version bumped 1.1 → 1.2.
- Decision recorded: no textual - the TUI stays curses (stdlib-only
  invariant and the ASCII column frame outweigh the interaction gains).

## 2.2.202609130748Z - 2026-09-13

- Baseline before the proper-python-project restructure.
- python_comment_style docstrings + type hints applied across ~100
  functions (agent_board 2.2, agent_watch 1.1).

## 2.1 - 2026-09-13

- Click-to-focus and numbered lines in `view` / `view-compact` (mouse
  click or number + Enter focuses the matching herdr tab); docs updated.

## 2.0.202609121108Z - 2026-09-12

- Underscore program names, needs-input (`❯`) + quota (`■`) statuses
  with live reset countdown, herdr tab coverage (every tab gets a
  column), agent badges, colored `--help`, `--version`, pytest suite.
- view-compact polish: single space after the column separator; number
  prefix on right-hand columns.

## 1.0.20260909065300 - 2026-09-09

- Initial release: live status board (`agent_board.py`) with one column
  per herdr agent, JSON card files posted by the agents themselves, and
  the `agent-watch` desktop-notification daemon.