"""agent_board — a live status board for coding agents.

The package pairs the board itself (`agent_board.board`: the `note` CLI,
the fullscreen curses TUI, the ANSI frame renderer, and the headless
`serve` loop) with the `agent-watch` notification daemon
(`agent_board.watch`). Both modules are stdlib-only by design; the
console scripts `agent-board` and `agent-watch` plus the historical
root-level launcher shims (`agent_board.py`, `agent_watch.py`) all end
up in `main()` of the respective module.
"""
from agent_board.board import __version__, main

__all__ = ["__version__", "main"]