---
name: agent-board
description: "Post your live status to the shared agent board (agent-board) while you work. Use at the start of any multi-step task — especially when a goal.md or todo.md exists or other agents are running in parallel: register, post each step as you start it, update as you go, mark done at the end, stop when leaving without finishing."
---

# Agent board

The user watches a vertical status board (run `agent-board` in any terminal)
with one column per agent. Your column header is your herdr tab title,
captured when you register. Posting is cheap (<100 ms, one small JSON file).

## When to post

Run exactly one of (binary is `~/sbin/agent-board`, normally just
`agent-board` in PATH):

| Moment | Command |
|---|---|
| Task start | `agent-board note register -m "<one-line goal>"` |
| Step started (esp. each goal.md / todo.md item) | `agent-board note step -m "<step>"` |
| Status materially changed | `agent-board note update -m "<what you are doing now>"` |
| Finished | `agent-board note done -m "<one-line result>"` |
| Leaving without finishing | `agent-board note stop` |

## Rules

- One short line per message (<120 chars), concrete: file, symbol, action.
- `step` also appends to your visible trail; `update` replaces the current
  line only. A handful per task is right — do not spam.
- Messages are user-visible. No secrets, no raw tool dumps.
- Your column disappears automatically when your herdr pane closes; `stop`
  is only for leaving while the pane stays open.
- If `agent-board` is missing from PATH try `~/sbin/agent-board`; if that is
  missing too, skip silently and continue working.