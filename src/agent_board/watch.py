#!/usr/bin/env python3
"""agent-watch - turn "some agent beeped" into "which tab needs you".

Watches two sources and emits a desktop notification naming the exact
workspace/tab/agent that needs attention:

  1. herdr  - polls `herdr api snapshot`; notifies when a background
              (non-focused) agent pane transitions to a needs-attention
              state (blocked, done, or idle while unfocused).
  2. external - finds known coding-agent processes running OUTSIDE herdr
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

__version__ = "1.3.20260920145442Z"
# Agent binaries herdr recognizes; used to spot external (non-herdr) agents.
KNOWN_AGENTS = {
    "omp", "codex", "claude", "gemini", "opencode", "agy", "hermes",
    "cursor", "devin", "qwen", "kimi", "droid", "grok", "amp", "maki",
    "kilo", "qoder", "qwen-code",
}


def run_json(cmd: list[str], timeout: float = 10) -> dict | None:
    """Run a command, return parsed JSON, or None on any failure.

    usage: run_json <CMD> [TIMEOUT]
    returns: Parsed stdout as a dict, or None when the command exits
        nonzero, times out, raises OSError, or emits invalid JSON.

    Args:
        cmd (list[str]): Command and arguments to execute.
        timeout (float, optional): Seconds before the command is killed. Defaults to 10.

    Example:
        run_json(["herdr", "api", "snapshot"], timeout=5)
    """
    try:
        out = subprocess.run(cmd, capture_output=True, text=True,
                             timeout=timeout)
        if out.returncode != 0:
            return None
        return json_loads(out.stdout)
    except (OSError, subprocess.TimeoutExpired):
        return None


def json_loads(s: str) -> dict | None:
    """Parse a JSON string, returning None when the input is invalid.

    usage: json_loads <S>
    returns: The parsed JSON object, or None when s is not valid JSON.

    Args:
        s (str): JSON text, typically a captured command's stdout.

    Example:
        json_loads('{"result": {"snapshot": {"agents": []}}}')
    """
    import json
    try:
        return json.loads(s)
    except ValueError:
        return None


# --------------------------------------------------------------------------
# herdr source
# --------------------------------------------------------------------------

def herdr_agents(herdr_bin: str) -> list[dict]:
    """Return list of agent dicts from `herdr api snapshot`, or [] on error.

    usage: herdr_agents <HERDR_BIN>
    returns: List of agent dicts from the herdr snapshot, or [] when the
        snapshot call fails or reports no agents.

    Args:
        herdr_bin (str): Name or path of the herdr binary.

    Example:
        herdr_agents("herdr")
    """
    d = run_json([herdr_bin, "api", "snapshot"])
    if not d:
        return []
    snap = d.get("result", {}).get("snapshot", {})
    return snap.get("agents", []) or []


def needs_attention(status: str, focused: bool) -> bool:
    """True when an agent pane wants the user's eyes.

    usage: needs_attention <STATUS> <FOCUSED>
    returns: True when the pane is unfocused and its status is blocked,
        done, or idle.

    Args:
        status (str): Agent status reported by herdr ("blocked", "done",
            "idle", or other).
        focused (bool): Whether the agent's pane is currently focused.

    Example:
        needs_attention("blocked", focused=False)
    """
    if focused:
        return False  # you are already looking at it
    return status in ("blocked", "done", "idle")


def herdr_label(a: dict) -> str:
    """Build the "workspace · tab · title" label for a herdr agent record.

    usage: herdr_label <A>
    returns: Label joining workspace id, tab id, and the stripped terminal
        title (falling back to the raw title, then to "").

    Args:
        a (dict): One agent record as returned by herdr_agents().

    Example:
        herdr_label({"workspace_id": "w1", "tab_id": "t2",
                     "terminal_title": "omp"})
    """
    ws = a.get("workspace_id", "?")
    tab = a.get("tab_id", "?")
    title = a.get("terminal_title_stripped") or a.get("terminal_title") or ""
    return f"{ws} · {tab} · {title}"


# --------------------------------------------------------------------------
# external (non-herdr) source
# --------------------------------------------------------------------------

def _descendants(pid: int) -> set[int]:
    """Collect a process pid and all of its transitive children.

    usage: _descendants <PID>
    returns: Set containing pid plus every descendant pid discovered via
        /proc task children files.

    Args:
        pid (int): Root process id to start the walk from.

    Example:
        _descendants(1234)
    """
    out = {pid}
    changed = True
    while changed:
        changed = False
        for p in list(out):
            for c in glob.glob(f"/proc/{p}/task/*/children"):
                try:
                    with open(c) as fh:
                        children = fh.read().split()
                except OSError:
                    continue
                for ch_s in children:
                    ch = int(ch_s)
                    if ch not in out:
                        out.add(ch)
                        changed = True
    return out


def _tty_of(pid: int) -> str | None:
    """Resolve the controlling terminal of a process via /proc.

    usage: _tty_of <PID>
    returns: Symlink target of the process's fd/0 (e.g. "/dev/pts/3"),
        or None when it cannot be read.

    Args:
        pid (int): Process id to inspect.

    Example:
        _tty_of(1234)
    """
    try:
        return os.readlink(f"/proc/{pid}/fd/0")
    except OSError:
        return None


def herdr_ttys(herdr_bin: str) -> set[str]:
    """Set of /dev/pts/N controlling ttys owned by herdr panes.

    usage: herdr_ttys <HERDR_BIN>
    returns: Set of /dev/pts/N paths for ttys held by herdr server
        descendant processes.

    Args:
        herdr_bin (str): Name or path of the herdr binary (unused; kept for
            a uniform source API).

    Example:
        herdr_ttys("herdr")
    """
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


def external_agents(herdr_bin: str) -> list[tuple[int, str, str]]:
    """List of (pid, comm, tty) for known agents running outside herdr.

    usage: external_agents <HERDR_BIN>
    returns: List of (pid, comm, tty) tuples for KNOWN_AGENTS binaries
        running interactively on a pts outside herdr.

    Args:
        herdr_bin (str): Name or path of the herdr binary, used to exclude
            herdr-owned panes.

    Example:
        external_agents("herdr")
    """
    owned = herdr_ttys(herdr_bin)
    found = []
    for p in glob.glob("/proc/[0-9]*"):
        pid = int(p.split("/")[-1])
        try:
            with open(f"/proc/{pid}/comm") as fh:
                comm = fh.read().strip()
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


def tty_idle_seconds(tty: str) -> float | None:
    """Seconds since the pts device was last written, or None if unknown.

    usage: tty_idle_seconds <TTY>
    returns: Seconds elapsed since the tty device's mtime, or None when
        the device cannot be stat'ed.

    Args:
        tty (str): Path to a pts device, e.g. "/dev/pts/3".

    Example:
        tty_idle_seconds("/dev/pts/3")
    """
    try:
        return time.time() - os.stat(tty).st_mtime
    except OSError:
        return None


# --------------------------------------------------------------------------
# notification
# --------------------------------------------------------------------------

def notify(title: str, body: str, notify_cmd: str, dry_run: bool) -> None:
    """Send a desktop notification, or print it instead when dry_run is set.

    usage: notify <TITLE> <BODY> <NOTIFY_CMD> <DRY_RUN>
    returns: None on success.

    Args:
        title (str): Notification title, e.g. "herdr: omp".
        body (str): Notification body text.
        notify_cmd (str): Path of the notification binary to invoke.
        dry_run (bool): When True, print the notification to stdout instead
            of running notify_cmd.

    Example:
        notify("external: claude", "pid 4321 · /dev/pts/5 · idle 12s",
               "/usr/bin/notify-send", dry_run=True)
    """
    if dry_run:
        print(f"[notify] {title} :: {body}", flush=True)
        return
    subprocess.run([notify_cmd, title, body])


# --------------------------------------------------------------------------
# main loop
# --------------------------------------------------------------------------

def main() -> int:
    """Parse CLI arguments and run the agent-watch poll loop.

    usage: main
    returns: Process exit code; 0 after a single pass with --once.
    errors: 2 when the configured herdr or notify binary is not found in
        PATH.

    Example:
        sys.exit(main())
    """
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
    herdr_state: dict = {}   # pane_id -> bool (currently needs attention)
    # external: pid -> (needs_attention, last_seen)
    ext_state: dict = {}

    last_ext_scan = 0.0
    while True:
        now = time.time()

        # --- herdr source ---
        for a in herdr_agents(herdr_bin):
            pane = a.get("pane_id")
            if not pane:
                continue
            want = needs_attention(a.get("agent_status") or "",
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
