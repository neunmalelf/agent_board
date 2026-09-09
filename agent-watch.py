#!/usr/bin/env python3
"""agent-watch — turn "some agent beeped" into "which tab needs you".

Watches two sources and emits a desktop notification naming the exact
workspace/tab/agent that needs attention:

  1. herdr  — polls `herdr api snapshot`; notifies when a background
              (non-focused) agent pane transitions to a needs-attention
              state (blocked, done, or idle while unfocused).
  2. external — finds known coding-agent processes running OUTSIDE herdr
              (controlling tty not owned by a herdr pane) and notifies when
              one appears and its terminal goes idle (best-effort heuristic;
              no standalone instance was available to validate it).

Run as a long-lived daemon (systemd user unit or `nohup`). Use --once for a
single pass, --dry-run to print instead of notifying.
"""
import argparse
import glob
import os
import shutil
import subprocess
import sys
import time

# Agent binaries herdr recognizes; used to spot external (non-herdr) agents.
KNOWN_AGENTS = {
    "omp", "codex", "claude", "gemini", "opencode", "agy", "hermes",
    "cursor", "devin", "qwen", "kimi", "droid", "grok", "amp", "maki",
    "kilo", "qoder", "qwen-code",
}


def run_json(cmd, timeout=10):
    """Run a command, return parsed JSON, or None on any failure."""
    try:
        out = subprocess.run(cmd, capture_output=True, text=True,
                             timeout=timeout)
        if out.returncode != 0:
            return None
        return json_loads(out.stdout)
    except (OSError, subprocess.TimeoutExpired):
        return None


def json_loads(s):
    import json
    try:
        return json.loads(s)
    except ValueError:
        return None


# --------------------------------------------------------------------------
# herdr source
# --------------------------------------------------------------------------

def herdr_agents(herdr_bin):
    """Return list of agent dicts from `herdr api snapshot`, or [] on error."""
    d = run_json([herdr_bin, "api", "snapshot"])
    if not d:
        return []
    snap = d.get("result", {}).get("snapshot", {})
    return snap.get("agents", []) or []


def needs_attention(status, focused):
    """True when an agent pane wants the user's eyes."""
    if focused:
        return False  # you are already looking at it
    if status == "blocked":
        return True   # approval / question UI
    if status == "done":
        return True   # background work finished
    if status == "idle":
        return True   # ready for input, tab not focused
    return False


def herdr_label(a):
    ws = a.get("workspace_id", "?")
    tab = a.get("tab_id", "?")
    title = a.get("terminal_title_stripped") or a.get("terminal_title") or ""
    return f"{ws} · {tab} · {title}"


# --------------------------------------------------------------------------
# external (non-herdr) source
# --------------------------------------------------------------------------

def _descendants(pid):
    out = {pid}
    changed = True
    while changed:
        changed = False
        for p in list(out):
            for c in glob.glob(f"/proc/{p}/task/*/children"):
                try:
                    for ch in open(c).read().split():
                        ch = int(ch)
                        if ch not in out:
                            out.add(ch)
                            changed = True
                except OSError:
                    pass
    return out


def _tty_of(pid):
    try:
        return os.readlink(f"/proc/{pid}/fd/0")
    except OSError:
        return None


def herdr_ttys(herdr_bin):
    """Set of /dev/pts/N controlling ttys owned by herdr panes."""
    sp = subprocess.run(["pgrep", "-f", "herdr server"],
                        capture_output=True, text=True)
    servers = [int(x) for x in sp.stdout.split() if x.isdigit()]
    ttys = set()
    for s in servers:
        for d in _descendants(s):
            t = _tty_of(d)
            if t and t.startswith("/dev/pts/"):
                ttys.add(t)
    return ttys


def external_agents(herdr_bin):
    """List of (pid, comm, tty) for known agents running outside herdr."""
    owned = herdr_ttys(herdr_bin)
    found = []
    for p in glob.glob("/proc/[0-9]*"):
        pid = int(p.split("/")[-1])
        try:
            comm = open(f"/proc/{pid}/comm").read().strip()
        except OSError:
            continue
        if comm not in KNOWN_AGENTS:
            continue
        t = _tty_of(pid)
        if not t or not t.startswith("/dev/pts/"):
            continue  # not an interactive terminal agent
        if t in owned:
            continue  # it is a herdr pane; the herdr source covers it
        found.append((pid, comm, t))
    return found


def tty_idle_seconds(tty):
    """Seconds since the pts device was last written, or None if unknown."""
    try:
        return time.time() - os.stat(tty).st_mtime
    except OSError:
        return None


# --------------------------------------------------------------------------
# notification
# --------------------------------------------------------------------------

def notify(title, body, notify_cmd, dry_run):
    if dry_run:
        print(f"[notify] {title} :: {body}", flush=True)
        return
    subprocess.run([notify_cmd, title, body])


# --------------------------------------------------------------------------
# main loop
# --------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--herdr-bin", default="herdr")
    ap.add_argument("--notify-cmd", default="notify-send")
    ap.add_argument("--interval", type=float, default=2.0,
                    help="herdr poll interval (s)")
    ap.add_argument("--external-interval", type=float, default=5.0,
                    help="external scan interval (s)")
    ap.add_argument("--idle-threshold", type=float, default=10.0,
                    help="external tty idle seconds before 'needs input'")
    ap.add_argument("--once", action="store_true",
                    help="single pass, then exit (for smoke tests)")
    ap.add_argument("--dry-run", action="store_true",
                    help="print notifications instead of sending them")
    args = ap.parse_args()

    herdr_bin = shutil.which(args.herdr_bin)
    notify_cmd = shutil.which(args.notify_cmd)
    if not herdr_bin:
        print("agent-watch: herdr binary not found in PATH", file=sys.stderr)
        return 2
    if not notify_cmd:
        print("agent-watch: notify binary not found in PATH", file=sys.stderr)
        return 2

    # herdr: pane_id -> last needs-attention episode state
    herdr_state = {}   # pane_id -> bool (currently needs attention)
    # external: pid -> (needs_attention, last_seen)
    ext_state = {}

    last_ext_scan = 0.0
    while True:
        now = time.time()

        # --- herdr source ---
        for a in herdr_agents(herdr_bin):
            pane = a.get("pane_id")
            if not pane:
                continue
            want = needs_attention(a.get("agent_status"),
                                   a.get("focused", False))
            was = herdr_state.get(pane, False)
            if want and not was:
                notify(f"herdr: {a.get('agent', 'agent')}",
                       herdr_label(a), notify_cmd, args.dry_run)
            herdr_state[pane] = want

        # --- external source ---
        if now - last_ext_scan >= args.external_interval:
            last_ext_scan = now
            seen = set()
            for pid, comm, tty in external_agents(herdr_bin):
                seen.add(pid)
                idle = tty_idle_seconds(tty)
                want = idle is not None and idle >= args.idle_threshold
                was = ext_state.get(pid, (False, 0))[0]
                if want and not was:
                    notify(f"external: {comm}",
                           f"pid {pid} · {tty} · idle {idle:.0f}s",
                           notify_cmd, args.dry_run)
                ext_state[pid] = (want, now)
            # drop vanished pids
            for pid in [p for p in ext_state if p not in seen]:
                del ext_state[pid]

        if args.once:
            return 0
        time.sleep(args.interval)


if __name__ == "__main__":
    sys.exit(main())
