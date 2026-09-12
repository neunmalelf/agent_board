---
name: agent-board
description: "Post your live status to the shared agent board (agent_board.py) while you work. Use at the start of any multi-step task — especially when a goal.md or todo.md exists or other agents are running in parallel: register, post each step as you start it, update as you go, mark done at the end, stop when leaving without finishing."
---

# Agent board

The user watches a vertical status board (run `agent_board.py` in any terminal)
with one column per agent. Your column header is your herdr tab title,
captured when you register. Posting is cheap (<100 ms, one small JSON file).

## When to post

Run exactly one of (binary is `~/sbin/agent_board.py`, normally just
`agent_board.py` in PATH):

| Moment | Command |
|---|---|
| Task start | `agent_board.py note register -m "<one-line goal>"` |
| Step started (esp. each goal.md / todo.md item) | `agent_board.py note step -m "<step>"` |
| Status materially changed | `agent_board.py note update -m "<what you are doing now>"` |
| Finished | `agent_board.py note done -m "<one-line result>"` |
| Waiting on the user (question, options) | `agent_board.py note input -m "<question or options>"` |
| Rate/quota limit hit (cannot continue) | `agent_board.py note quota -m "<provider message>" --reset "<ISO time, duration, or seconds>"` |
| Leaving without finishing | `agent_board.py note stop` |

## Rules

- One short line per message (<120 chars), concrete: file, symbol, action.
- `step` and `input` also append to your visible trail; `update` replaces
  the current line only. A handful per task is right — do not spam.
- Whenever you ask the user something or present options, post `input`:
  your column turns yellow ("needs input") so the user sees it. Your next
  `step`/`update`/`done` clears it automatically.
- When a rate/quota limit stops you, post `quota` with `--reset`: your
  column turns red ("stopped") with a live "Resets in d hh:mm:ss"
  countdown. Your next `step`/`update`/`done` clears it automatically.
- Messages are user-visible. No secrets, no raw tool dumps.
- Your column disappears automatically when your herdr pane closes; `stop`
  is only for leaving while the pane stays open.
- If `agent_board.py` is missing from PATH try `~/sbin/agent_board.py`; if
  that is missing too, skip silently and continue working.