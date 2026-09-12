# agent_board

Watch what your coding agents are doing — in one place, live.

Two small tools live in this project (both Python 3, stdlib only):

| Tool | What it does |
|------|--------------|
| `agent_board.py` | live status board: one vertical column per agent; agents register and post what they are doing until the task is closed |
| `agent-watch` | daemon that pops a desktop notification naming the exact tab that needs input |

## agent_board.py

### Service

```sh
agent_board start       # install (if needed) + enable + start the service
agent_board stop        # stop + disable
agent_board restart
agent_board status      # service state + the current board frame
agent_board view        # foreground fullscreen TUI (autorefresh 30 s)
agent_board view --autorefresh 10   # TUI, refresh every 10 s
agent_board view-compact            # one line per agent, two columns
agent_board view-compact --autorefresh 10   # compact, refresh every 10 s
agent_board logs [n]    # last n journal lines of the service
```

`agent_board start` runs the board as a systemd user service
(`agent_board.service` → `agent_board.py serve`): every 2 s it renders the
board to `~/.local/state/agent_board/board.txt`. `agent_board status`
prints the service state and that frame, so the board is readable anywhere
(including `watch -c "cat ~/.local/state/agent_board/board.txt"`).
For the interactive fullscreen TUI run `agent_board.py` or `agent_board view`
(`view` refreshes the live data every 30 s; `--autorefresh N` overrides).

### Columns

Each live agent gets one column:

```
┌─ (● working) (1_ddpico) fmann@amd:~/projects/1_ddpico
│ agy · w1:tP · pid 2068849 · mem 569M
```

- **Header** = the agent's herdr tab title ("project name"), captured at
  register time (spinner glyphs stripped).
- **Chip** = `● working · ❯ needs input · ■ stopped · blocked ○ idle
  ✓ done` from herdr's snapshot; `+ external` / `! stale` for cards
  outside herdr. `note input` (question/options for the user) shows the
  yellow `❯ needs input` chip; `note quota --reset <when>` shows the red
  `■ stopped` chip with a live "Resets in d hh:mm:ss" countdown — both
  clear on the agent's next step/update.
- **Tab label** = herdr's own tab label (`tabs[].label` in the snapshot),
  shown in magenta inside light-grey parens after the chip; the
  description text renders white. The tab id (`w1:tP`) stays on the meta
  line.
- **Agent badge** = cyan agent symbol. omp's `π` and opencode's `OC`/
  `OpenCode` are colored in place when the tab title starts with them;
  agents whose titles carry no symbol get one prepended (agy → `AG`).
- **Tab coverage** = every herdr tab gets a column. Tabs whose agent
  herdr could not detect (agent kind unknown) render as
  `(? unknown) <tab label>` with no meta beyond the tab id, so tabs like
  `freebuff -- mediadownloader_web` never vanish from the board.
- **pid + mem** — resolved per agent from `/proc` (herdr's snapshot carries
  no pid): matched by agent-kind alias + cwd, external cards by their pts
  tty.
- **Text + trail** — what the agent posted: current line plus its last
  steps with timestamps.
- **Removal**: herdr pane closed → column vanishes automatically (the
  snapshot is the liveness truth; stale card files are swept). Agents
  outside herdr post with an `ext-*` id; their column drops on
  `note stop` or after `--stale-seconds` (600).

### Agent side

| Moment | Command |
|--------|---------|
| Task start | `agent_board.py note register -m "<one-line goal>"` |
| Step started (esp. each goal.md / todo.md item) | `agent_board.py note step -m "<step>"` |
| Status materially changed | `agent_board.py note update -m "<now doing>"` |
| Finished | `agent_board.py note done -m "<one-line result>"` |
| Waiting on the user (question, options) | `agent_board.py note input -m "<question or options>"` |
| Rate/quota limit hit | `agent_board.py note quota -m "<message>" --reset "<when>"` |

Messages are one short line, user-visible. `step` also appends to the
visible trail; `update` replaces the current line only. One frame without
the TUI: `agent_board.py --once`.

### Tests

`python3 -m pytest tests/ -q` — 46 tests covering text helpers, reset
parsing, card storage, every `note` action (incl. `input`/`quota` flag
lifecycles), column building (chip priority, sorting, tab fallback,
sweep), rendering (plain/ANSI/compact, badges, countdowns), help
coloring, process resolution, and the CLI + wrapper end-to-end in an
isolated state dir. Run it after every change to `agent_board.py`.

### Global skill

`~/.agents/skills/agent-board/SKILL.md` teaches agents to post: register at
task start, post each step when working through goal.md / todo.md, `done`
at the end, `stop` when leaving unfinished. omp and hermes load it
automatically from `~/.agents/skills/`; any harness that can run a shell
command can post.

## agent-watch

Turn "some agent beeped" into "which tab needs you".

`agent-watch` is a small daemon that watches your coding agents and pops a
desktop notification naming the exact workspace/tab/agent that needs
attention.

### Features

- **herdr source** — polls `herdr api snapshot`; notifies when a background
  (non-focused) agent pane transitions to a needs-attention state:
  `blocked` (approval/question UI), `done` (background work finished), or
  `idle` while unfocused (ready for input).
- **external source** — finds known coding-agent processes running *outside*
  herdr (controlling tty not owned by a herdr pane) and notifies when one
  appears and its terminal goes idle. Best-effort heuristic.
- Skips the pane you are already looking at; dedupes per episode.
- Runs as a systemd user service (auto-start at login, auto-restart).

### Usage

```sh
agent-watch --once --dry-run   # print what it would notify, no popups
agent-watch --once             # one real pass (sends notifications)
agent-watch --help             # all options
```

### Options

| Option | Default | Meaning |
|--------|---------|---------|
| `--herdr-bin` | `herdr` | herdr CLI path |
| `--notify-cmd` | `notify-send` | notification command |
| `--interval` | `2.0` | herdr poll interval (s) |
| `--external-interval` | `5.0` | external scan interval (s) |
| `--idle-threshold` | `10.0` | external tty idle seconds before "needs input" |
| `--once` | off | single pass, then exit |
| `--dry-run` | off | print instead of notifying |

## Layout

```
~/projects/agent_board/
├── agent_board               # service manager (start/stop/status/view)
├── agent_board.py             # status board: note CLI, TUI, serve mode
├── agent-watch.py            # notification daemon
├── agent_board_readme.md     # this file
└── systemd/
    ├── agent_board.service   # frame-writer service (agent_board start)
    └── agent-watch.service   # watcher service
```

`~/sbin/agent_board.py`, `~/sbin/agent_watch` and `~/sbin/agent_board` are
symlinks into this directory.

## Install (fresh machine)

```sh
# 1. Put the project somewhere (here: ~/projects/agent_board)
# 2. Symlink the binaries
ln -s ~/projects/agent_board/agent_board.py ~/sbin/agent_board.py
ln -s ~/projects/agent_board/agent-watch.py ~/sbin/agent-watch
ln -s ~/projects/agent_board/agent_board ~/sbin/agent_board

# 2. Install the services
mkdir -p ~/.config/systemd/user
cp ~/projects/agent_board/systemd/*.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now agent_board.service agent-watch.service

# 3. Install the global posting skill
mkdir -p ~/.agents/skills
cp -r ~/projects/agent_board/skills/agent-board ~/.agents/skills/
```

Requirements: Python 3, `herdr` in PATH, `notify-send` (for agent-watch).

## Managing the services

```sh
~/sbin/agent_board status                    # board: state + live frame
systemctl --user status agent_board agent_watch
journalctl --user -u agent_board -f          # follow board writer log
systemctl --user restart agent-watch         # after editing the watcher
```

## Uninstall

```sh
~/sbin/agent_board stop
systemctl --user disable --now agent-watch.service
rm ~/.config/systemd/user/agent_board.service ~/.config/systemd/user/agent-watch.service
rm ~/sbin/agent_board.py ~/sbin/agent_watch ~/sbin/agent_board
rm -rf ~/projects/agent_board
```

## Notes / limitations

- pid + mem resolution is best-effort: it matches agent-kind aliases + cwd
  (herdr agents) or the pts tty (external cards); a column may show without
  pid if the process cannot be identified confidently.
- The external "needs input" heuristic in agent-watch (tty idle) is
  best-effort; the *detection* of external agents is validated.
- herdr's own `[ui.toast] delivery = "system"` and `status_indicators` +
  `show_agent_labels_on_pane_borders` complement these tools; see
  `~/.config/herdr/config.toml`.