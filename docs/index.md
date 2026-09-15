# agent_board

Watch what your coding agents are doing - in one place, live.

`agent_board` pairs two stdlib-only Python tools:

| Tool | What it does |
|------|--------------|
| **agent_board** (`src/agent_board/board.py`) | live status board: one vertical column per agent; agents register and post what they are doing until the task is closed. Renders as a fullscreen curses TUI, a one-shot ANSI frame, or a headless frame file written by a systemd user service. |
| **agent-watch** (`src/agent_board/watch.py`) | notification daemon that pops a desktop notification naming the exact tab that needs input. |

Full usage documentation lives in the repository [README.md](https://github.com/neunmalelf/agent_board) - start there.

## Quick links

- Install (users): `./_install` - editable install plus git hook wiring, or copy `systemd/*.service` manually as described in the README.
- Run (devs): `./_run` (TUI), `./_run --once` (one frame), `./_menu` (helper menu).
- Check (devs): `./_tests` (pytest + ruff + mypy).
- Project history and decisions: `history.md` at the repository root.

## Layout

```
agent_board/
├── src/agent_board/       # the package: board.py (board) + watch.py (daemon)
├── agent_board.py          # launcher shim (systemd + ~/sbin symlink entry)
├── agent_watch.py          # launcher shim (~/sbin/agent_watch entry)
├── agent_board             # bash service manager (start/stop/status/view)
├── _build _check_version _docs _git _install _menu _run _tests
├── hooks/                  # modular pre-commit hook + installer
├── history.md              # release log (newest entry on top)
├── history/                # archives: prompts/ changes/ todo/ plans/ tests/ ideas/ goals/
├── docs/                   # MkDocs sources (built into site/ by ./_docs)
├── man/  tldr/  systemd/  skills/  tests/
└── pyproject.toml  README.md  LICENSE  AGENTS.md  .agentrules
```