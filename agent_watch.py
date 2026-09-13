#!/usr/bin/env python3
"""agent_watch.py — thin launcher shim for the agent-watch daemon.

What/when: Keeps the historical entry path working after the move to the
src/ package layout: `~/sbin/agent_watch` is a symlink to this file. The
daemon implementation lives in `agent_board/watch.py`; the src/ directory
is prepended to sys.path so the shim also works from a bare checkout
without an editable install.

usage: python3 agent_watch.py [CLI arguments]

returns: The exit code of agent_board.watch.main().

Example:
    python3 agent_watch.py --once --dry-run
"""
import sys
from pathlib import Path

if __name__ == "__main__":
    _src = str(Path(__file__).resolve().parent / "src")
    # Always at position 0: an editable install's .pth also lists src/ but
    # at the tail, where the same-named root files would shadow the package.
    sys.path.insert(0, _src)
    from agent_board.watch import main

    sys.exit(main())