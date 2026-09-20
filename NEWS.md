# NEWS

User-visible highlights per release. Full details: `ChangeLog.md`;
decisions and reasoning: `history.md` (newest on top).

## 2.8 (2026-09-20)

- **Ctrl+C quits the board cleanly**: pressing Ctrl+C in the fullscreen TUI
  no longer dumps a Python traceback - like `q` it leaves the board, curses
  restores the terminal, and the exit code stays 0. The same applies to the
  headless `serve` frame writer and to an interrupted `--once` frame.
- **The service starts on a fresh machine**: `agent_board.py serve` creates
  the state directory for its frame file instead of failing with
  `FileNotFoundError` until the first agent posted a card.

## 2.7 (2026-09-20)

- **Agents behind a wrapper are no longer invisible**: the pane probe now
  follows the pane's process tree and matches an agent by process name *and*
  by argv, so an agent started inside `mc`, a node/python launcher, or any
  other wrapper gets its own column with pid and memory. In the live session
  the `earth` tab ran two agents (omp and a cline behind `mc`) but showed
  only one; both are rendered now, the cline column carrying its `CL` badge.
- **Every agent of a pane is listed**: a pane that hosts several agent kinds
  shows one column per kind (the extra ones are keyed `<pane>#<kind>`), and
  the agent that posted a status card leads its column.
- **Closed herdr tabs leave the view on the next refresh**: a card is swept
  as soon as its recorded tab is no longer an active herdr tab, not only
  when its pane disappeared from the snapshot.

## 2.6 (2026-09-20)

- **Quieter board**: a column now shows its current status line only - the
  step trail (`· [hh:mm] step: ...`, the agent's step-by-step process) is
  gone from the screen, so a board with many agents stays readable.
  `--trail` brings it back; the posted steps stay in the status card either
  way. Applies to the fullscreen TUI, `--once`, and the service frame.

## 2.5 (2026-09-20)

- **30 s refresh by default**: the fullscreen TUI, `--once`, and the
  service frame writer now refresh every 30 s instead of 2 s (matching
  `agent_board view`). `--poll-period` / `--autorefresh SECONDS` overrides
  it (minimum 1 s) - `agent_board.py serve --poll-period 2` keeps the old
  frame cadence.
- **Every agent in a herdr tab is shown**: one column per agent pane, not
  one per tab. Besides the agents herdr classifies, the board shows panes
  that posted a status card and known agent processes found in the pane's
  foreground (`herdr pane process-info`) - so a second agent in a tab
  (for example an unclassified cline or freebuff instance) no longer stays
  invisible; it gets its own column with pid and memory.
- **Tab liveness before every refresh**: the snapshot is re-read each
  cycle. A herdr-owned card is swept only when its pane and its tab are
  both gone, so an agent herdr never classified keeps its column while its
  tab is open, and a closed tab leaves the view right away.
- **`CL` badge for cline**, plus `cline` and `freebuff` as known agent
  kinds so their pid/mem resolve like any other agent.

## 2.4 (2026-09-15)

- **Platforms documented** in the README: Linux fully supported; macOS
  partial (no `/proc` → pid/tty discovery blind, no systemd → run
  `agent_board.py serve` directly); Windows not supported natively -
  run inside **WSL2** with systemd enabled.
- **man + tldr pages**: install steps added (`man/agent_board.1`,
  `man/agent-watcher.1` into `~/.local/share/man/man1/`, tldr pages into
  the client's custom page dir). Stale pre-restructure
  `~/projects/agent-watcher/` paths fixed in `tldr/agent-watcher.md` and
  `man/agent-watcher.1`.
- **view-compact spacing**: the left column's agent rows draw one space
  in, so the menu number no longer sits flush at column 0.
- **freebuff as a first-class agent column**: agents outside herdr's
  built-in list can be classified via herdr's custom-agent API
  (`herdr pane report-agent <pane> --source custom:<name> --agent <kind>
  --state working|idle|blocked`). The board renders them like any other
  column - chip state, pid/mem resolution, and a cyan `FB` badge for
  freebuff (the `Freebuff:` brand prefix is stripped from titles).
  Verified live; the freebuff agent posts status via the installed
  agent-board skill on its own.

## 2.3 (2026-09-13)

- **Proper Python project packaging**: `src/` layout, PEP 621
  `pyproject.toml` (setuptools), console scripts `agent-board` /
  `agent-watch`, modular pre-commit hook, helper-script toolset
  (`_tests`, `_run`, `_menu`, `_git`, `_install`, `_build`, `_docs`,
  `_check_version`).
- **Tooling gates**: ruff (E/F/I/UP/B/SIM) + mypy + pytest (49 tests);
  enforced by the hook and `./_tests` before every commit.
- **Runtime stays stdlib-only**: `dependencies = []` - zero third-party
  runtime dependencies, zero pip installs for end users.
- **Decision recorded**: the fullscreen TUI stays curses; textual was
  evaluated and rejected (stdlib-only invariant + ASCII column design).