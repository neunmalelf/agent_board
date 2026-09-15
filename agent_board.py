#!/usr/bin/env python3
"""agent_board.py - thin launcher shim for the agent_board package.

What/when: Keeps the historical entry paths working after the move to the
src/ package layout: `~/sbin/agent_board.py` is a symlink to this file, and
both the systemd unit (`agent_board.service`) and the `agent_board` wrapper
script exec it. The implementation lives in `agent_board/board.py`; the
src/ directory is prepended to sys.path so the shim also works from a bare
checkout without an editable install.

usage: python3 agent_board.py [CLI arguments]

returns: The exit code of agent_board.board.main().

Example:
    python3 agent_board.py --once
"""
import sys
from pathlib import Path

if __name__ == "__main__":
    _src = str(Path(__file__).resolve().parent / "src")
    # Always at position 0: an editable install's .pth also lists src/ but
    # at the tail, where the same-named root files would shadow the package.
    sys.path.insert(0, _src)
    from agent_board.board import main

    sys.exit(main())