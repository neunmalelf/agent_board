# ChangeLog

All notable changes, newest first. Versions are
`Major.Minor.<14-digit UTC stamp>Z` (stamps in commit messages and
`src/agent_board/` `__version__`). Detailed reasoning, decisions, and
release notes live in `history.md`; user-facing highlights in `NEWS.md`.

## 2.9.20260920145912Z - 2026-09-20

- Columns are grouped by herdr tab: `build_columns()` collects the columns per
  tab, sorts inside a tab (`column_sort_key()`: chip priority, then card age)
  and places each tab by its most urgent column, so the agents of one tab -
  including its `(? unknown)` fallback and a second agent probed in the same
  pane - follow each other in the TUI, `--once`, and the service frame.
  A column without a tab (an agent outside herdr) keeps its own place in that
  order instead of joining a group.
- The compact layout benefits directly: the two agents of a tab now land in
  adjacent numbered rows (previously they could sit in different halves).
- README ("Order" bullet), `tldr/agent_board.md`, `man/agent_board.1`;
  tests 82 → 83 (`test_build_columns_groups_agents_of_one_tab` asserts the
  contiguous order, the tab placement by the most urgent column, and that an
  `ext-*` column keeps its own place).

## 2.8.20260920145442Z - 2026-09-20

- Ctrl+C in the fullscreen TUI no longer prints a `KeyboardInterrupt`
  traceback: `run_tui()` catches it around `getch()` (and treats the ETX key
  3 like `q`), `main()` catches it around `curses.wrapper()` and the
  `serve` loop, so both exit 0 with the terminal restored. The footer and
  the `man`/`tldr`/README key lists say `q/Ctrl+C quit`.
- `run_serve()` creates the frame file's directory (`os.makedirs` on
  `dirname(frame_path)`) instead of crashing with `FileNotFoundError` on a
  machine whose state directory does not exist yet (the systemd unit would
  have restarted every 5 s until the first card was posted).
- Tests 79 → 82: a pty test sends a real Ctrl+C into the TUI (fails on the
  previous release with exit code -2), `run_serve` writes into a missing
  frame directory and ends on Ctrl+C, and `main()` returns 0 for an
  interrupted `serve`, TUI, and `--once`.

## 2.7.20260920144525Z - 2026-09-20

- The pane probe follows the pane's process tree: `read_proc()`,
  `child_pids()`, `proc_tree()` (bounded by `MAX_TREE_PROCS` 64) and
  `proc_kind()` (process name plus argv tokens, `AGENT_ARG_SUFFIXES`
  stripped) replace the name-only lookup. `pane_agents()` returns one entry
  per agent kind in the pane, largest RSS first; `pane_agent()` stays as the
  thin largest-entry wrapper used by `note register`.
- `detect_pane_agents()` maps a pane to its entry list; new
  `probe_entries()` normalizes the map value. `build_columns()` renders one
  column per probed kind (extras keyed `<pane>#<kind>`) and lets the kind
  that posted the card lead; `card_chip()` factors the done/stopped/input
  precedence out of the agent and pane loops.
- `sweep()` also drops a herdr card whose recorded tab is missing from a
  non-empty live tab list, so a closed tab leaves the view even while its
  pane is still listed. External cards stay untouched.
- Tests 65 → 79: `proc_kind` matrix, `proc_tree` walk/limit/real-/proc,
  nested-agent probe, one entry per kind, `probe_entries`, per-kind columns,
  the live earth shape (omp plus cline behind mc with its `CL` badge), and
  the tab-liveness sweep cases. `test_self_pane_id_prefers_env` got its lost
  `def` line back (its asserts had silently run inside the previous test).
- README (tab coverage + removal bullets), `man/agent_board.1`,
  `tldr/agent_board.md`, `NEWS.md`. Live check: `--once` renders the earth
  tab as two columns (`CL > - set the default also to 30s`, `π Optimize
  without changing`); the probe costs ~0.10 s for 16 unclassified panes.



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