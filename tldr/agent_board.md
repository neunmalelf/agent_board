# agent_board.py

> Live status board for coding agents: one column per agent, liveness
> from herdr, statuses and trails posted by the agents themselves.

- Launch the fullscreen board (q or Ctrl+C quits, j/k scrolls; click a column or
  type its number + Enter to focus that herdr tab):
  `agent_board.py`
- Print a single frame (pipe into `watch`):
  `agent_board.py --once`
- Open your column at task start:
  `agent_board.py note register -m "one-line goal"`
- Post a step (status line + visible trail entry):
  `agent_board.py note step -m "todo 2/5: rewrite token refresh"`
- Signal you are waiting on the user (yellow chip):
  `agent_board.py note input -m "A) keep B) revert?"`
- Report a rate/quota stop with a live reset countdown (red chip):
  `agent_board.py note quota -m "Individual quota reached." --reset 2d 3h`
- Mark finished:
  `agent_board.py note done -m "PR #12 opened, tests green"`
- Leave the board:
  `agent_board.py note stop`

## Install

```sh
ln -s ~/projects/agent_board/agent_board.py ~/sbin/agent_board.py
ln -s ~/projects/agent_board/agent_board ~/sbin/agent_board
mkdir -p ~/.config/systemd/user
cp ~/projects/agent_board/systemd/agent_board.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now agent_board.service
```

## Service

```sh
agent_board status
agent_board restart
journalctl --user -u agent_board -f
```

## Notes

- The column header is the agent's herdr tab title, captured at register.
- Every agent pane gets a column: one tab can show several agents side by
  side (herdr-classified ones, panes that posted a card, and known agent
  processes found in the pane's process tree by name or argv, e.g. an
  unclassified cline or freebuff, even inside a wrapper like `mc`). A pane
  hosting several agent kinds gets one column per kind.
  Tabs without any agent show as `? unknown`.
- Refresh (TUI, `--once`, service frame) defaults to 30 s:
  `--poll-period` / `--autorefresh SECONDS` overrides it (minimum 1).
- Agents of one herdr tab stay together: the tab sorts by its most urgent
  column, and inside a tab columns keep the chip priority (working first,
  done last) and card age.
- Columns show the current status line only; `--trail` adds each agent's
  last step entries (the posted steps stay in the card either way).
- Every refresh re-reads the snapshot and drops the columns whose pane or
  tab is gone.
- Status chips: `● working`, `❯ needs input`, `■ stopped`, `blocked`,
  `○ idle`, `✓ done`, `+ external`, `! stale`.