# NEWS

User-visible highlights per release. Full details: `ChangeLog.md`;
decisions and reasoning: `history.md` (newest on top).

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