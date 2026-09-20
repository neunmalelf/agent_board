# ChangeLog

All notable changes, newest first. Versions are
`Major.Minor.<14-digit UTC stamp>Z` (stamps in commit messages and
`src/agent_board/` `__version__`). Detailed reasoning, decisions, and
release notes live in `history.md`; user-facing highlights in `NEWS.md`.

## 2.6.20260920141919Z - 2026-09-20

- Step trails are opt-in: `column_lines()`, `render_frame()`,
  `render_once()`, `run_tui()`, and `run_serve()` take `trail=False` by
  default, so a column renders head, meta line, current status line, and
  the closing rule; new `--trail` flag (TUI, `--once`, `serve` =
  `agent_board.py --trail serve`) re-enables the last four
  `· [hh:mm] k: m` entries. Cards keep the full log (`MAX_LOG` 24).
- README "Text + trail" bullet and run-command block, `tldr/agent_board.md`
  Notes, and `man/agent_board.1` (new `--trail` entry) document the flag.
  README serve example fixed to `agent_board.py --poll-period 2 serve`
  (top-level options must precede the subcommand).
- Tests 63 → 65 (trail hidden by default in columns and frames, shown with
  `trail=True`; parser default asserts `trail` off).

## 2.5.20260920140934Z - 2026-09-20

- Refresh default 2 s → 30 s for every mode (`--poll-period` /
  `--autorefresh SECONDS` overrides, minimum 1 s; the serve loop passes
  `--poll-period 2` for a lively frame file). Parser construction moved
  into `build_parser()` so the default is testable; `main()` parses once
  and dispatches.
- One column per agent pane instead of one per tab: `herdr_snapshot()`
  now returns agents, tabs, and panes; `build_columns()` gained
  `panes`/`pane_agents` and renders a column for every unclassified pane
  that has a card or a probed agent process (`pane_agent()`,
  `detect_pane_agents()` via `herdr pane process-info` + `pid_rss()`).
  A tab without any agent keeps its `(? unknown)` fallback column.
- Liveness re-check per refresh: `sweep()` takes tabs and panes and drops
  a herdr card only when its pane and tab are both gone; a card whose
  pane herdr did not classify survives while the tab is open.
- `herdr_match()` prefers the exact pane id and only falls back to a tab
  that hosts exactly one agent, so a second agent in a tab can no longer
  be mislabeled with the first one's kind. `note register` takes the
  header from the pane's title, records the pane's tab id, marks snapshot
  panes as herdr-owned, and probes the pane process for its agent kind.
- `AGENT_BADGE` gains cline → `CL`; `AGENT_ALIASES` gains cline and
  freebuff (pane probe, pid/mem resolution).
- Refresh is one `gather_columns()` call for TUI, `--once`, and serve;
  it costs ~0.15 s on a 6-tab/20-pane session (16 pane probes).
- Tests 51 → 63; README, README columns/removal notes, `man/agent_board.1`
  (default 30, pane/tab coverage), `tldr/agent_board.md`, `NEWS.md`.
  agent-watch stamp moved with the release (no code change).

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