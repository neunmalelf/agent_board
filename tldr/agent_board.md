# agent_board.py

> Live status board for coding agents: one column per agent, liveness
> from herdr, statuses and trails posted by the agents themselves.

- Launch the fullscreen board (q quits, j/k scrolls; click a column or
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
- Every herdr tab gets a column; tabs whose agent cannot be classified
  show as `? unknown`.
- Status chips: `● working`, `❯ needs input`, `■ stopped`, `blocked`,
  `○ idle`, `✓ done`, `+ external`, `! stale`.