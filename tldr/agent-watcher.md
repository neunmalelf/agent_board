# agent-watch

Notify which agent tab needs input.

- Watches herdr panes + external (non-herdr) agents; pops a desktop
  notification naming workspace/tab/agent when one needs attention.

## Install

```sh
ln -s ~/projects/agent-watcher/agent-watch ~/sbin/agent-watch
mkdir -p ~/.config/systemd/user
cp ~/projects/agent-watcher/systemd/agent-watch.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now agent-watch.service
```

## Run

```sh
agent-watch                          # daemon (normally via systemd)
agent-watch --once --dry-run         # preview, no popups
agent-watch --once                   # one real pass
```

## Service

```sh
systemctl --user status agent-watch
systemctl --user restart agent-watch
systemctl --user stop agent-watch
journalctl --user -u agent-watch -f
```

## Options

| Flag | Default | Meaning |
|------|---------|---------|
| `--interval` | 2.0 | herdr poll interval (s) |
| `--external-interval` | 5.0 | external scan interval (s) |
| `--idle-threshold` | 10.0 | external idle seconds before "needs input" |
| `--once` | off | single pass then exit |
| `--dry-run` | off | print instead of notifying |

## Files

- Source: `~/projects/agent-watcher/agent-watch`
- Unit: `~/.config/systemd/user/agent-watch.service`
- README: `~/projects/agent-watcher/agent-watcher-readme.md`
- Man: `~/projects/agent-watcher/agent-watcher.1`
