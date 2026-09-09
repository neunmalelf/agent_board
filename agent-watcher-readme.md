# agent-watcher

Turn "some agent beeped" into "which tab needs you".

`agent-watch` is a small daemon that watches your coding agents and pops a
desktop notification naming the exact workspace/tab/agent that needs
attention — so when several agents or LLM harnesses are running at once, you
know which tab to look at instead of guessing.

## Features

- **herdr source** — polls `herdr api snapshot`; notifies when a background
  (non-focused) agent pane transitions to a needs-attention state:
  `blocked` (approval/question UI), `done` (background work finished), or
  `idle` while unfocused (ready for input).
- **external source** — finds known coding-agent processes running *outside*
  herdr (controlling tty not owned by a herdr pane) and notifies when one
  appears and its terminal goes idle. Best-effort heuristic; no standalone
  instance was available to validate it.
- Skips the pane you are already looking at; dedupes per episode.
- Runs as a systemd user service (auto-start at login, auto-restart).

## Layout

```
~/projects/agent-watcher/
├── agent-watch              # the daemon (Python 3, stdlib only)
├── agent-watcher-readme.md  # this file
├── agent-watcher.1          # man page
├── tldr.md                  # quick cheat sheet
└── systemd/
    └── agent-watch.service   # systemd user unit
```

`~/sbin/agent-watch` is a symlink to `~/projects/agent-watcher/agent-watch`.

## Install

The daemon is already installed and running. To install on a fresh machine:

```sh
# 1. Put the source somewhere (here: ~/projects/agent-watcher)
# 2. Symlink it into your bin dir
ln -s ~/projects/agent-watcher/agent-watch ~/sbin/agent-watch

# 3. Install the systemd user unit
mkdir -p ~/.config/systemd/user
cp ~/projects/agent-watcher/systemd/agent-watch.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now agent-watch.service
```

Requirements: Python 3, `herdr` in PATH, `notify-send` (KDE/GNOME notification
daemon), `pgrep` (procps).

## Usage

Run as a daemon (normally via systemd):

```sh
agent-watch
```

Test / debug:

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

## Examples

```sh
# See what it would notify right now
agent-watch --once --dry-run
# → [notify] herdr: hermes :: w1 · w1:tV · fmann@amd:~/b/myagent
# → [notify] herdr: opencode :: w1 · w1:tP · OC | Add --timestamp ...

# Poll faster
agent-watch --interval 1

# Be more patient before flagging an external agent as idle
agent-watch --idle-threshold 30
```

## Managing the service

```sh
systemctl --user status agent-watch          # running?
systemctl --user restart agent-watch         # after editing the script
systemctl --user stop agent-watch            # stop
systemctl --user disable --now agent-watch   # stop + disable at login
journalctl --user -u agent-watch -f          # follow its log
```

## Uninstall

```sh
systemctl --user disable --now agent-watch.service
rm ~/.config/systemd/user/agent-watch.service
rm ~/sbin/agent-watch
rm -rf ~/projects/agent-watcher
```

## Notes / limitations

- The external "needs input" heuristic (tty idle for `--idle-threshold`
  seconds) is best-effort and unvalidated — no standalone agent was running
  when it was written. The *detection* of external agents is validated.
- herdr's own `[ui.toast] delivery = "system"` and `status_indicators` +
  `show_agent_labels_on_pane_borders` complement this watcher; see
  `~/.config/herdr/config.toml`.
