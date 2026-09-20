#!/usr/bin/env python3
"""agent-board - a live status board for coding agents.

Agents running under herdr (or in any shell) register themselves and post a
one-line status of what they are doing, updating it until the task is closed:

  agent_board.py note register -m "refactoring auth module"
  agent_board.py note step     -m "todo 2/5: rewrite token refresh"
  agent_board.py note update   -m "running pytest -k auth"
  agent_board.py note done     -m "PR #12 opened, tests green"
  agent_board.py note input    -m "A) keep B) revert?"  # waiting on user
  agent_board.py note quota    -m "quota reached" --reset 2d 3h

Each agent is one vertical column; the column header is the agent's herdr
tab title ("project name"), captured at register time. herdr's api snapshot
is the source of truth for liveness: a column disappears the moment its pane
(and with it its tab) closes. Every agent pane of a tab gets its own column,
so one tab can show several agents side by side: herdr-classified agents,
agents that only posted a card, and known agent processes found in the pane's
process tree (herdr pane process-info plus its /proc descendants) even when
herdr did not classify them - including an agent started inside a wrapper
(a node/python launcher or a terminal tool such as mc). A pane hosting several
agent kinds shows one column per kind.
Cards carry the free-text progress ("what is it doing", "what has it done").
Agents outside herdr get a column too; it disappears on `note stop` or after
--stale-seconds without an update.

Run `agent-board` for the fullscreen TUI; `agent_board.py --once` prints a
single frame (useful for logging or `watch`).
"""
import argparse
import contextlib
import curses
import glob
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import time
from datetime import datetime

__version__ = "2.8.20260920145442Z"

STATE_DIR = os.path.join(
    os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state"),
    "agent_board",
)
FRAME_PATH = os.path.join(STATE_DIR, "board.txt")

CHIP_SYMBOL = {"working": "●", "blocked": "×", "idle": "○", "done": "✓",
               "input": "❯", "stopped": "■", "unknown": "?", "ext": "+",
               "stale": "!"}
CHIP_LABEL = {"working": "working", "blocked": "blocked", "idle": "idle",
              "done": "done", "input": "needs input",
              "stopped": "stopped", "unknown": "unknown", "ext": "external",
              "stale": "stale"}
CHIP_COLOR = {"working": 1, "blocked": 2, "idle": 3, "done": 1,
              "input": 4, "stopped": 2, "unknown": 4, "ext": 4, "stale": 2}
STATUS_ORDER = {"working": 0, "input": 1, "stopped": 2, "blocked": 3,
                "unknown": 4, "ext": 5, "stale": 5, "idle": 6, "done": 7}
MAX_LOG = 24
MAX_HEADER = 80
MAX_MSG = 200
SPINNER_RE = re.compile(r"[⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏]")
# Agents started through an interpreter or a wrapper are matched by argv too
# ("node /home/.../bin/cline"), so these suffixes are stripped from a token.
AGENT_ARG_SUFFIXES = (".js", ".mjs", ".cjs", ".ts", ".py", ".exe")
# Upper bound of /proc entries read per probed pane (foreground tree walk).
MAX_TREE_PROCS = 64


def clean_title(text: str) -> str:
    """Tab title without transient spinner glyphs or the freebuff brand label.

    usage: clean_title <TEXT>
    returns: The cleaned title, or "" when text is empty. A leading
        "Freebuff:" label is dropped because the board prepends the FB badge.

    Args:
        text (str): Raw tab title, possibly with transient spinner glyphs.

    Example:
        clean_title("π Refactoring auth ⠹")
    """
    stripped = re.sub(r"\s{2,}", " ", SPINNER_RE.sub(" ", text or "")).strip()
    return re.sub(r"^Freebuff:\s*", "", stripped, flags=re.IGNORECASE)


# --------------------------------------------------------------------------
# state: one JSON card per agent under ~/.local/state/agent-board/
# --------------------------------------------------------------------------

def card_path(pane_id: str) -> str:
    """Filesystem path of the JSON state card for a pane.

    usage: card_path <PANE_ID>
    returns: "<safe>.json" under STATE_DIR, unsafe characters replaced with "_".

    Args:
        pane_id (str): Pane identifier used as the card file stem.

    Example:
        card_path("p-1a2b")
    """
    safe = re.sub(r"[^A-Za-z0-9._-]", "_", pane_id)
    return os.path.join(STATE_DIR, safe + ".json")


def read_card(path: str) -> dict | None:
    """Load one JSON card file.

    usage: read_card <PATH>
    returns: The card as a dict, or None when unreadable or invalid.
    errors: None on OSError (missing/unreadable file) or ValueError (invalid JSON).

    Args:
        path (str): Path to a card JSON file.

    Example:
        card = read_card(card_path("p-1a2b"))
    """
    try:
        with open(path) as f:
            card = json.load(f)
        return card if isinstance(card, dict) else None
    except (OSError, ValueError):
        return None


def load_cards() -> dict:
    """Read every card file in STATE_DIR.

    usage: load_cards
    returns: Dict mapping pane_id to its card; empty when the directory is unreadable.

    Example:
        cards = load_cards()
    """
    cards: dict = {}
    try:
        names = os.listdir(STATE_DIR)
    except OSError:
        return cards
    for name in names:
        if not name.endswith(".json"):
            continue
        card = read_card(os.path.join(STATE_DIR, name))
        if card and card.get("pane_id"):
            cards[str(card["pane_id"])] = card
    return cards


def save_card(card: dict) -> None:
    """Atomically write one card to its JSON file under STATE_DIR.

    usage: save_card <CARD>
    returns: None on success.
    errors: OSError when STATE_DIR cannot be created or the card cannot be written.

    Args:
        card (dict): Card mapping; must contain "pane_id".

    Example:
        save_card({"pane_id": "p-1a2b", "status": "running tests", "log": []})
    """
    os.makedirs(STATE_DIR, exist_ok=True)
    path = card_path(card["pane_id"])
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(card, f)
    os.replace(tmp, path)


def drop_card(pane_id: str) -> None:
    """Delete the card file for a pane, ignoring a missing file.

    usage: drop_card <PANE_ID>
    returns: None; a missing card file is silently ignored.

    Args:
        pane_id (str): Pane whose card should be removed.

    Example:
        drop_card("p-1a2b")
    """
    with contextlib.suppress(OSError):
        os.remove(card_path(pane_id))


# --------------------------------------------------------------------------
# herdr snapshot: the authoritative agent registry
# --------------------------------------------------------------------------

def herdr_json(herdr_bin: str, *args: str, timeout: float = 10) -> dict | None:
    """Run one herdr subcommand and parse its JSON output.

    Args:
        herdr_bin: Path or name of the herdr binary to run.
        args: herdr subcommand and options, e.g. "api", "snapshot".
        timeout: Seconds before herdr is killed.

    Returns:
        The parsed JSON object, or None when herdr exits nonzero, cannot be
        run, times out, or emits invalid JSON.

    Example:
        data = herdr_json("herdr", "api", "snapshot")
    """
    try:
        out = subprocess.run([herdr_bin, *args], capture_output=True,
                             text=True, timeout=timeout)
        if out.returncode != 0:
            return None
        data = json.loads(out.stdout)
        return data if isinstance(data, dict) else None
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


def herdr_snapshot(herdr_bin: str) -> tuple[list | None, list, list]:
    """Read the live herdr session as (agents, tabs, panes).

    Args:
        herdr_bin: Path or name of the herdr binary to query.

    Returns:
        The agent, tab, and pane lists of the snapshot. Agents is None when
        the snapshot is unreachable; tabs and panes are then empty. The pane
        list covers every pane of every tab, so agents herdr did not classify
        stay visible to the board.

    Example:
        agents, tabs, panes = herdr_snapshot("herdr")
    """
    data = herdr_json(herdr_bin, "api", "snapshot")
    snap = ((data or {}).get("result") or {}).get("snapshot") or {}
    agents = snap.get("agents", [])
    if data is None or not snap or not isinstance(agents, list):
        return None, [], []
    tabs = [t for t in snap.get("tabs") or [] if t.get("tab_id")]
    panes = [p for p in snap.get("panes") or [] if p.get("pane_id")]
    return agents, tabs, panes


def herdr_agents(herdr_bin: str) -> tuple[list | None, list]:
    """Read the live herdr agents together with the snapshot tab list.

    Args:
        herdr_bin: Path or name of the herdr binary to query.

    Returns:
        (agents, tabs) from herdr_snapshot(); agents is None when the
        snapshot cannot be read.

    Example:
        agents, tabs = herdr_agents("herdr")
    """
    agents, tabs, _ = herdr_snapshot(herdr_bin)
    return agents, tabs


def herdr_pane_processes(herdr_bin: str, pane_id: str) -> list:
    """List the foreground processes of one herdr pane.

    Args:
        herdr_bin: Path or name of the herdr binary to query.
        pane_id: Pane whose foreground processes should be listed.

    Returns:
        The process dicts (name, pid, cwd, argv) reported by
        `herdr pane process-info`, or [] when the pane is unknown to herdr or
        herdr cannot be queried.

    Example:
        procs = herdr_pane_processes("herdr", "w1:p68")
    """
    data = herdr_json(herdr_bin, "pane", "process-info", "--pane", pane_id,
                      timeout=5)
    info = ((data or {}).get("result") or {}).get("process_info") or {}
    procs = info.get("foreground_processes")
    return procs if isinstance(procs, list) else []


def pid_rss(pid: int | None) -> int | None:
    """Read the resident-set size of one process from /proc.

    Args:
        pid: Process id to inspect; None short-circuits to None.

    Returns:
        VmRSS in KiB, or None when the pid is missing or unreadable.

    Example:
        pid_rss(4242)
    """
    if not pid:
        return None
    try:
        with open(f"/proc/{pid}/status") as f:
            for line in f:
                if line.startswith("VmRSS:"):
                    return int(line.split()[1])
    except (OSError, ValueError, IndexError):
        return None
    return None


def read_proc(pid: int) -> dict | None:
    """Read one process's name and argv from /proc.

    usage: read_proc <PID>
    returns: {"name", "pid", "argv"}, or None when the pid has no readable entry.

    Args:
        pid (int): Process id to read.

    Example:
        read_proc(os.getpid())
    """
    try:
        with open(f"/proc/{pid}/comm") as fh:
            name = fh.read().strip()
        with open(f"/proc/{pid}/cmdline", "rb") as fh:
            argv = [a.decode("utf-8", "replace")
                    for a in fh.read().split(b"\0") if a]
    except OSError:
        return None
    return {"name": name, "pid": pid, "argv": argv}


def child_pids(pid: int) -> list[int]:
    """List the direct children of a process, read from /proc.

    usage: child_pids <PID>
    returns: Child pids in file order; empty when the pid or its children are gone.

    Args:
        pid (int): Parent process id.

    Example:
        child_pids(os.getpid())
    """
    kids: list[int] = []
    for path in glob.glob(f"/proc/{pid}/task/*/children"):
        try:
            with open(path) as fh:
                kids += [int(x) for x in fh.read().split() if x.isdigit()]
        except (OSError, ValueError):
            continue
    return kids


def proc_tree(pids: list, limit: int = MAX_TREE_PROCS) -> list[dict]:
    """Read the given processes plus all of their descendants.

    usage: proc_tree <PIDS> [LIMIT]
    returns: Process dicts (name, pid, argv) breadth-first, roots first, at
        most `limit` entries; vanished processes are skipped.

    Args:
        pids (list): Root pids, e.g. a pane's foreground processes.
        limit (int, optional): Maximum number of processes to read. Defaults
            to MAX_TREE_PROCS.

    Example:
        tree = proc_tree([p.get("pid") for p in procs])
    """
    out: list[dict] = []
    seen: set[int] = set()
    queue = [int(p) for p in pids if isinstance(p, int) and p]
    while queue and len(out) < limit:
        pid = queue.pop(0)
        if pid in seen:
            continue
        seen.add(pid)
        proc = read_proc(pid)
        if proc is None:
            continue
        out.append(proc)
        queue += [k for k in child_pids(pid) if k not in seen]
    return out


def proc_kind(proc: dict) -> str:
    """Agent kind of one process, matched by its name and by its argv.

    Args:
        proc: Process dict from herdr pane process-info or read_proc().

    Returns:
        The agent kind from AGENT_KIND_BY_NAME, or "" when neither the process
        name nor an interpreter/wrapper argument names a known agent binary -
        "node /home/fmann/.local/bin/cline" resolves through its argv, and an
        agent binary path anywhere in argv wins over an unknown wrapper name.

    Example:
        proc_kind({"name": "node-MainThread", "argv": ["node", "/opt/bin/cline"]})
    """
    argv = [str(a) for a in proc.get("argv") or []]
    tokens = [str(proc.get("name") or "")] + argv[:2]
    tokens += [a for a in argv if "/" in a]
    for token in tokens:
        base = os.path.basename(token).lower()
        if base.endswith(AGENT_ARG_SUFFIXES):
            base = base.rsplit(".", 1)[0]
        kind = AGENT_KIND_BY_NAME.get(base)
        if kind:
            return kind
    return ""


def herdr_match(agents: list | None, pane_id: str, tab_id: str) -> dict | None:
    """Find the herdr agent of a pane, or of a tab that hosts exactly one.

    Args:
        agents: herdr agent dicts; None or empty searches nothing.
        pane_id: Pane id to match; empty skips the pane lookup.
        tab_id: Tab id to match when no pane id was given; a tab hosting
            several agents is ambiguous and matches nothing.

    Returns:
        The matching agent dict, or None when no unambiguous entry matches.

    Example:
        agent = herdr_match(agents, "w1:p6A", "")
    """
    for a in agents or []:
        if pane_id and a.get("pane_id") == pane_id:
            return a
    if tab_id and not pane_id:
        in_tab = [a for a in agents or [] if a.get("tab_id") == tab_id]
        if len(in_tab) == 1:
            return in_tab[0]
    return None


# --------------------------------------------------------------------------
# agent side: `agent_board.py note ...`
# --------------------------------------------------------------------------

def self_pane_id() -> str:
    """Derive this process's pane id without contacting herdr.

    usage: self_pane_id
    returns: $HERDR_PANE_ID, "ext-<tty basename>", or "ext-anon-<ppid>".

    Example:
        pane = self_pane_id()
    """
    env = os.environ.get("HERDR_PANE_ID")
    if env:
        return env
    try:
        tty = os.ttyname(0)
    except (OSError, ValueError):
        tty = None
    if tty:
        return "ext-" + re.sub(r"[^A-Za-z0-9._-]", "-",
                               os.path.basename(tty)).lstrip("-")
    return f"ext-anon-{os.getppid()}"


def parse_reset(text: str | None, now: float) -> float | None:
    """--reset value: ISO time, a duration (2d 4h 30m / 90m), or seconds.

    usage: parse_reset <TEXT> <NOW>
    returns: Absolute epoch timestamp of the reset, or None when empty/unparseable.

    Args:
        text (str, optional): Raw --reset value; None or empty yields None.
        now (float): Current epoch time, the base for durations and bare seconds.

    Example:
        reset_at = parse_reset("2d 3h", time.time())
    """
    t = (text or "").strip()
    if not t:
        return None
    m = re.fullmatch(
        r"(?:(\d+)\s*d(?:ay)?s?[\s,]+)?(\d{1,3}):(\d{2}):(\d{2})", t, re.I)
    if m:
        return (now + int(m.group(1) or 0) * 86400
                + int(m.group(2)) * 3600 + int(m.group(3)) * 60
                + int(m.group(4)))
    m = re.fullmatch(
        r"(?:(\d+)\s*d(?:ay)?s?)?\s*(?:(\d+)\s*h(?:our)?s?)?"
        r"\s*(?:(\d+)\s*m(?:in)?s?)?\s*(?:(\d+)\s*s(?:ec)?s?)?", t, re.I)
    if m and any(m.groups()):
        days, hours, mins, secs = (int(g) if g else 0 for g in m.groups())
        return now + days * 86400 + hours * 3600 + mins * 60 + secs
    try:
        return now + float(t)  # bare number = seconds from now
    except ValueError:
        pass
    try:
        dt = datetime.fromisoformat(t.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.astimezone()
        return dt.timestamp()
    except ValueError:
        return None


def cmd_note(ns: argparse.Namespace, herdr_bin: str) -> int:
    """Handle the note actions: create, update, or remove this agent's card.

    Args:
        ns: Parsed `note` subcommand arguments.
        herdr_bin: herdr binary used to look up the agent snapshot.

    Returns:
        0 after posting, updating, or removing the card; 2 when -m/--msg is
        missing for an action that requires it.

    Example:
        cmd_note(ns, "herdr")
    """
    pane = ns.pane or self_pane_id()
    tab = ns.tab if ns.tab is not None else (
        os.environ.get("HERDR_TAB_ID") or "" if ns.pane is None else "")
    path = card_path(pane)
    now = time.time()

    if ns.action == "stop":
        if os.path.exists(path):
            os.remove(path)
            print(f"agent_board: removed column {pane}")
        else:
            print(f"agent_board: no column for {pane}")
        return 0

    if not ns.msg:
        print("agent_board: -m/--msg required for this action", file=sys.stderr)
        return 2
    msg = ns.msg.strip()[:MAX_MSG]

    agents, _tabs, panes = herdr_snapshot(herdr_bin)
    match = herdr_match(agents, pane, tab)
    pane_info = next((p for p in panes if str(p.get("pane_id")) == pane), None)
    card = read_card(path)

    if ns.action == "register" or card is None:
        header = (ns.header or "").strip()
        source = match or pane_info or {}
        if not header:
            title = clean_title(source.get("terminal_title_stripped")
                                or source.get("terminal_title") or "")
            header = title or f"{socket.gethostname()}:{os.getcwd()}"
        if not tab and pane_info:
            tab = str(pane_info.get("tab_id") or "")
        kind = ns.agent or (match or {}).get("agent") or ""
        if not kind and pane_info:
            kind = pane_agent(herdr_bin, pane)[0]  # herdr did not classify it
        card = {"pane_id": pane, "tab_id": tab, "header": header[:MAX_HEADER],
                "agent": kind,
                "herdr": bool((ns.pane is None
                               and os.environ.get("HERDR_PANE_ID"))
                              or pane_info),
                "status": "", "log": [], "created": now, "updated": now,
                "done": False}
        if ns.action == "register":
            card["log"] = [{"t": now, "k": "register", "m": msg}] if msg else []

    card["status"] = msg
    card["updated"] = now
    if ns.header:
        card["header"] = ns.header.strip()[:MAX_HEADER]
    if ns.agent:
        card["agent"] = ns.agent
    if tab:
        card["tab_id"] = tab
    if ns.action in ("step", "done", "input", "quota"):
        card["log"] = (card.get("log") or []) + [{"t": now, "k": ns.action,
                                                  "m": msg}]
        card["log"] = card["log"][-MAX_LOG:]
    if ns.action == "done":
        card["done"] = True
    if ns.action == "input":
        card["input"] = True
    elif ns.action in ("update", "step", "done"):
        card["input"] = False
    if ns.action == "quota":
        card["stopped"] = {"reset": parse_reset(ns.reset, now)}
    elif ns.action in ("update", "step", "done"):
        card.pop("stopped", None)
    card["pane_id"] = pane

    save_card(card)
    print(f"agent_board: [{pane}] {ns.action}: {msg}")
    return 0


# --------------------------------------------------------------------------
# process info: pid + memory per agent (herdr snapshot carries no pid)
# --------------------------------------------------------------------------

AGENT_ALIASES = {
    "omp": {"omp"}, "hermes": {"hermes"}, "opencode": {"opencode"},
    "agy": {"agy", "antigravity", "antigravity-cli"},
    "codex": {"codex"}, "claude": {"claude"}, "gemini": {"gemini"},
    "amp": {"amp"}, "droid": {"droid"}, "grok": {"grok"}, "kimi": {"kimi"},
    "cursor": {"cursor"}, "devin": {"devin"}, "qwen": {"qwen", "qwen-code"},
    "kilo": {"kilo"}, "qoder": {"qoder"}, "cline": {"cline"},
    "freebuff": {"freebuff"},
}
# Reverse map: process name -> agent kind, for the pane process probe.
AGENT_KIND_BY_NAME = {name: kind for kind, names in AGENT_ALIASES.items()
                      for name in names}


def rss_str(kb: int | None) -> str:
    """Format a resident-set size in KiB for the meta line.

    usage: rss_str <KB>
    returns: "" when kb is None, else "<N>M" or "<X.X>G".

    Args:
        kb (int, optional): RSS in KiB from /proc/<pid>/status; None means unknown.

    Example:
        rss_str(3_500_000)
    """
    if kb is None:
        return ""
    if kb < 1024 * 1024:
        return f"{kb // 1024}M"
    return f"{kb / 1024 / 1024:.1f}G"


def scan_procs() -> tuple[dict, dict]:
    """One /proc pass: (by_pts_basename, by_(comm, cwd)) of (pid, comm, rss_kb).

    usage: scan_procs
    returns: (by_tty, by_kind) mapping pts basenames and (comm, cwd) pairs
        to lists of (pid, comm, rss_kb) tuples.

    Example:
        by_tty, by_kind = scan_procs()
    """
    by_tty: dict = {}
    by_kind: dict = {}
    for d in glob.glob("/proc/[0-9]*"):
        try:
            pid = int(d.rsplit("/", 1)[-1])
            with open(d + "/comm") as fh:
                comm = fh.read().strip().lower()
            with open(d + "/status") as f:
                rss = 0
                for line in f:
                    if line.startswith("VmRSS:"):
                        rss = int(line.split()[1])
                        break
        except (OSError, ValueError, IndexError):
            continue
        if not rss:
            continue
        try:
            cwd = os.readlink(d + "/cwd")
        except OSError:
            cwd = ""
        try:
            tty = os.readlink(d + "/fd/0")
        except OSError:
            tty = ""
        if tty.startswith("/dev/pts/"):
            by_tty.setdefault(tty.rsplit("/", 1)[-1], []).append((pid, comm, rss))
        by_kind.setdefault((comm, cwd), []).append((pid, comm, rss))
    return by_tty, by_kind


def resolve_proc(kind: str, cwd: str, procs: tuple | None) -> tuple[int | None, int | None]:
    """Best-effort (pid, rss_kb) for a herdr agent: comm aliases + cwd match.

    usage: resolve_proc <KIND> <CWD> <PROCS>
    returns: (pid, rss_kb) of the largest-RSS candidate, or (None, None).

    Args:
        kind (str): Agent kind label looked up in AGENT_ALIASES.
        cwd (str): Working directory matched against process cwds.
        procs (tuple, optional): (by_tty, by_kind) from scan_procs(); None/empty short-circuits.

    Example:
        pid, rss = resolve_proc("omp", "/home/fmann/projects/auth", procs)
    """
    if not procs:
        return None, None
    by_tty, by_kind = procs
    names = AGENT_ALIASES.get(kind, set()) | {str(kind).lower()}
    best = None
    for name in names:
        for cand in by_kind.get((name, cwd or ""), ()):
            if best is None or cand[2] > best[2]:
                best = cand  # the agent's main process has the largest RSS
    return (best[0], best[2]) if best else (None, None)


def resolve_ext_proc(pane_id: str, procs: tuple | None) -> tuple[int | None, int | None]:
    """ext-<pts basename> card: find the agent process holding that tty.

    usage: resolve_ext_proc <PANE_ID> <PROCS>
    returns: (pid, rss_kb) of the largest-RSS known agent on that tty, or (None, None).

    Args:
        pane_id (str): Card pane id starting with "ext-"; others short-circuit to (None, None).
        procs (tuple, optional): (by_tty, by_kind) from scan_procs(); None short-circuits.

    Example:
        pid, rss = resolve_ext_proc("ext-3", procs)
    """
    if not procs or not pane_id.startswith("ext-"):
        return None, None
    known = set()
    for names in AGENT_ALIASES.values():
        known |= names
    best = None
    for pid, comm, rss in procs[0].get(pane_id[4:], []):
        if comm in known and (best is None or rss > best[2]):
            best = (pid, comm, rss)
    return (best[0], best[2]) if best else (None, None)


def pane_agents(herdr_bin: str, pane_id: str) -> list[dict]:
    """Find every known agent process running in one herdr pane.

    Args:
        herdr_bin: Path or name of the herdr binary to query.
        pane_id: Pane whose foreground processes and their /proc descendants
            are checked, so an agent started inside a wrapper (a launcher or a
            terminal tool such as mc) is found as well.

    Returns:
        One {"agent", "pid", "rss"} entry per agent kind found, largest RSS
        first; [] when no known agent runs in the pane.

    Example:
        pane_agents("herdr", "w1:p68")
    """
    procs = herdr_pane_processes(herdr_bin, pane_id)
    if not procs:
        return []
    tree: list[dict] = list(procs)
    known = {p.get("pid") for p in procs}
    tree += [p for p in proc_tree([p.get("pid") for p in procs])
             if p["pid"] not in known]
    best: dict = {}
    for proc in tree:
        kind = proc_kind(proc)
        if not kind:
            continue
        pid = proc.get("pid")
        pid = pid if isinstance(pid, int) else None
        rss = pid_rss(pid)
        if kind not in best or (rss or 0) > (best[kind]["rss"] or 0):
            best[kind] = {"agent": kind, "pid": pid, "rss": rss}
    entries = list(best.values())
    entries.sort(key=lambda e: e["rss"] or 0, reverse=True)
    return entries


def pane_agent(herdr_bin: str, pane_id: str) -> tuple[str, int | None, int | None]:
    """Find the largest agent process of a pane, whether herdr classified it.

    Args:
        herdr_bin: Path or name of the herdr binary to query.
        pane_id: Pane whose process tree is checked.

    Returns:
        (kind, pid, rss_kb) of the largest known agent process running in the
        pane, or ("", None, None) when no known agent runs there.

    Example:
        kind, pid, rss = pane_agent("herdr", "w1:p68")
    """
    found = pane_agents(herdr_bin, pane_id)
    if not found:
        return "", None, None
    top = found[0]
    return str(top["agent"]), top["pid"], top["rss"]


def detect_pane_agents(herdr_bin: str, panes: list, agents: list | None) -> dict:
    """Probe the panes herdr did not classify for known agent processes.

    Args:
        herdr_bin: Path or name of the herdr binary to query.
        panes: Snapshot pane dicts to inspect.
        agents: Snapshot agent dicts; herdr-classified panes are skipped.

    Returns:
        {pane_id: [{"agent", "pid", "rss"}, ...]} for every unclassified pane
        that runs at least one known agent process, else {}. A pane hosting
        several agent kinds reports one entry per kind, largest RSS first.

    Example:
        found = detect_pane_agents("herdr", panes, agents)
    """
    classified = {str(a.get("pane_id")) for a in agents or [] if a.get("pane_id")}
    found: dict = {}
    for p in panes:
        pane = str(p.get("pane_id"))
        if not pane or pane in classified:
            continue
        entries = pane_agents(herdr_bin, pane)
        if entries:
            found[pane] = entries
    return found


def probe_entries(found: object) -> list[dict]:
    """Normalize one pane's probe result into a list of agent entries.

    usage: probe_entries <FOUND>
    returns: The entries as a list; a single entry dict is wrapped, and
        None or any other value yields [].

    Args:
        found (object): Value of the pane_agents map for one pane: a list of
            entries, a single entry dict, or None.

    Example:
        probe_entries({"agent": "cline", "pid": 7, "rss": 128})
    """
    if isinstance(found, dict):
        return [found]
    if isinstance(found, list):
        return [e for e in found if isinstance(e, dict)]
    return []


def card_chip(card: dict, fallback: str) -> str:
    """Chip state of a card, falling back to a herdr status.

    usage: card_chip <CARD> <FALLBACK>
    returns: "done"/"stopped"/"input" when the card says so, else fallback,
        else "unknown".

    Args:
        card (dict): Card mapping with optional done/stopped/input flags.
        fallback (str): herdr status ("working", "idle", ...) used when the
            card carries no flag.

    Example:
        card_chip({"input": True}, "working")
    """
    if card.get("done"):
        return "done"
    if card.get("stopped"):
        return "stopped"
    if card.get("input"):
        return "input"
    return fallback or "unknown"


# --------------------------------------------------------------------------
# viewer: merge snapshot + cards into columns
# --------------------------------------------------------------------------

def build_columns(agents: list | None, cards: dict, now: float, stale_after: float,
                  procs: tuple | None = None, tabs: list | None = None,
                  panes: list | None = None, pane_agents: dict | None = None) -> list:
    """Merge herdr agents, panes, and posted cards into board columns.

    Args:
        agents: herdr agent dicts; None means the snapshot is unavailable, so
            herdr-owned cards are hidden (unknown liveness) but not deleted.
        cards: Posted cards keyed by pane_id.
        now: Current epoch time, base for card ages and staleness.
        stale_after: External card age in seconds before the "stale" chip.
        procs: (by_tty, by_kind) from scan_procs() for pid/RSS lookup.
        tabs: Snapshot tab list; every tab without an agent gets a fallback
            column (agent kind unknown) so no herdr tab can go missing.
        panes: Snapshot pane list; panes without a herdr-classified agent but
            with a card or a probed agent process of their own get a column,
            so a tab can show every agent running in it - one column per agent
            kind found in the pane.
        pane_agents: {pane_id: [{"agent", "pid", "rss"}, ...]} from
            detect_pane_agents() for the panes herdr did not classify.

    Returns:
        Column dicts sorted by status priority, then card age.

    Example:
        cols = build_columns(agents, cards, time.time(), 600.0, tabs=tabs,
                             panes=panes, pane_agents=found)
    """
    labels = {t["tab_id"]: t.get("label") or "" for t in tabs or []
              if t.get("tab_id")}
    cols = []
    for a in agents or []:
        pane = str(a.get("pane_id") or "")
        card = cards.get(pane) or {}
        header = (card.get("header")
                  or clean_title(a.get("terminal_title_stripped"))
                  or a.get("cwd") or pane)
        kind = a.get("agent") or card.get("agent") or "?"
        pid, rss = resolve_proc(kind, a.get("cwd") or card.get("cwd") or "", procs)
        tab = str(a.get("tab_id") or card.get("tab_id") or "")
        cols.append({
            "pane": pane,
            "agent": kind,
            "tab": tab,
            "tab_name": labels.get(tab, ""),
            "header": header[:MAX_HEADER],
            "chip": card_chip(card, str(a.get("agent_status") or "unknown")),
            "focused": bool(a.get("focused")),
            "text": status_text(card, now),
            "log": card.get("log") or [],
            "age": (now - card["updated"]) if card.get("updated") else None,
            "pid": pid, "rss": rss,
        })

    covered = {c["pane"] for c in cols}
    for p in panes or []:
        pane = str(p.get("pane_id") or "")
        if not pane or pane in covered:
            continue  # herdr already classified this pane, or it is empty
        card = cards.get(pane) or {}
        probed = probe_entries((pane_agents or {}).get(pane))
        if not card and not probed:
            continue  # plain shell or tool pane: not an agent
        card_kind = str(card.get("agent") or "")
        if card_kind:
            # the agent that posted the card leads its column
            probed.sort(key=lambda e: str(e.get("agent")) != card_kind)
        header = (card.get("header")
                  or clean_title(p.get("terminal_title_stripped")
                                 or p.get("terminal_title") or "")
                  or p.get("cwd") or pane)
        tab = str(p.get("tab_id") or card.get("tab_id") or "")
        entries = probed or [{"agent": card_kind, "pid": None, "rss": None}]
        for i, e in enumerate(entries):
            kind = str(e.get("agent") or card_kind)
            pid, rss = e.get("pid"), e.get("rss")
            if pid is None and kind:
                pid, rss = resolve_proc(kind, str(p.get("cwd") or ""), procs)
            cols.append({
                # a second agent kind in the same pane gets a derived column id
                "pane": pane if i == 0 else f"{pane}#{kind}",
                "agent": kind,
                "tab": tab,
                "tab_name": labels.get(tab, ""),
                "header": header[:MAX_HEADER],
                "chip": card_chip(card, str(p.get("agent_status") or "unknown")),
                "focused": bool(p.get("focused")),
                "text": status_text(card, now) if i == 0 else "",
                "log": (card.get("log") or []) if i == 0 else [],
                "age": ((now - card["updated"])
                        if i == 0 and card.get("updated") else None),
                "pid": pid, "rss": rss,
            })

    seen = {c["pane"] for c in cols}
    for pane, card in cards.items():
        if pane in seen:
            continue
        if card.get("herdr"):
            continue  # herdr pane gone from snapshot = agent stopped
        age = now - (card.get("updated") or now)
        if card.get("done"):
            chip = "done"
        elif card.get("stopped"):
            chip = "stopped"
        elif card.get("input"):
            chip = "input"
        elif age > stale_after:
            chip = "stale"
        else:
            chip = "ext"
        pid, rss = resolve_ext_proc(pane, procs)
        tab = str(card.get("tab_id") or "")
        cols.append({
            "pane": pane,
            "agent": card.get("agent") or "external",
            "tab": tab,
            "tab_name": labels.get(tab, ""),
            "header": (card.get("header") or pane)[:MAX_HEADER],
            "chip": chip, "focused": False,
            "text": status_text(card, now),
            "log": card.get("log") or [], "age": age,
            "pid": pid, "rss": rss,
        })

    seen_tabs = {c["tab"] for c in cols if c["tab"]}
    for t in tabs or []:
        tab = str(t.get("tab_id") or "")
        if tab in seen_tabs:
            continue
        cols.append({
            "pane": tab,
            "agent": "",
            "tab": tab,
            "tab_name": "",
            "header": (t.get("label") or tab)[:MAX_HEADER],
            "chip": t.get("agent_status") or "unknown",
            "focused": bool(t.get("focused")),
            "text": "", "log": [], "age": None,
            "pid": None, "rss": None,
        })

    cols.sort(key=lambda c: (STATUS_ORDER.get(str(c["chip"]), 9),
                             c["age"] if c["age"] is not None else 1e12))
    return cols


def sweep(cards: dict, agents: list | None, tabs: list | None = None,
          panes: list | None = None) -> None:
    """Delete cards whose herdr tab or pane has closed.

    Args:
        cards: Cards keyed by pane_id, as returned by load_cards().
        agents: Live herdr agent dicts; None disables sweeping because the
            snapshot is unreachable.
        tabs: Live snapshot tab dicts; a card whose recorded tab is no longer
            among them drops even while its pane is still listed, so a closed
            herdr tab leaves the view on the next refresh.
        panes: Live snapshot pane dicts; when present, pane liveness is
            authoritative and a vanished pane drops its card.

    Returns:
        None; matching card files are removed.

    Example:
        sweep(cards, agents, tabs, panes)
    """
    if agents is None:
        return  # snapshot unavailable: keep everything
    live_panes = {str(a.get("pane_id")) for a in agents if a.get("pane_id")}
    if panes:
        live_panes |= {str(p.get("pane_id")) for p in panes if p.get("pane_id")}
    live_tabs = {str(t.get("tab_id")) for t in tabs or [] if t.get("tab_id")}
    for pane, card in cards.items():
        if not card.get("herdr"):
            continue  # external card: herdr does not own it
        tab = str(card.get("tab_id") or "")
        if live_tabs and tab and tab not in live_tabs:
            drop_card(pane)  # its herdr tab is gone: out of the view
            continue
        if pane in live_panes:
            continue
        if not panes and tab and tab in live_tabs:
            continue  # no pane list in this snapshot: its live tab is enough
        drop_card(pane)


def gather_columns(herdr_bin: str, now: float, stale_after: float) -> tuple[list, bool]:
    """Refresh the whole board: snapshot, liveness sweep, probe, then merge.

    Args:
        herdr_bin: Path or name of the herdr binary to query.
        now: Current epoch time for card ages and the quota countdown.
        stale_after: External card age in seconds before the "stale" chip.

    Returns:
        (columns, herdr_ok); herdr_ok is False when the snapshot was
        unreachable, in which case herdr-owned cards are kept but not shown.

    Example:
        cols, herdr_ok = gather_columns("herdr", time.time(), 600.0)
    """
    agents, tabs, panes = herdr_snapshot(herdr_bin)
    cards = load_cards()
    sweep(cards, agents, tabs, panes)
    pane_agents = detect_pane_agents(herdr_bin, panes, agents) if panes else {}
    cols = build_columns(agents, cards, now, stale_after, procs=scan_procs(),
                         tabs=tabs, panes=panes, pane_agents=pane_agents)
    return cols, agents is not None


def age_str(seconds: float | None) -> str:
    """Humanize a card age for the meta line.

    usage: age_str <SECONDS>
    returns: "" when seconds is None, else e.g. "42s", "5m", or "3h07m".

    Args:
        seconds (float, optional): Age in seconds; None means unknown.

    Example:
        age_str(12540.0)
    """
    if seconds is None:
        return ""
    if seconds < 60:
        return f"{int(seconds)}s"
    if seconds < 3600:
        return f"{int(seconds // 60)}m"
    return f"{int(seconds // 3600)}h{int(seconds % 3600 // 60):02d}m"


def dur_str(seconds: float) -> str:
    """Countdown as d hh:mm:ss; days shown only when nonzero.

    usage: dur_str <SECONDS>
    returns: Formatted countdown, e.g. "04:12:33" or "2d 04:12:33".

    Args:
        seconds (float): Seconds remaining; negative values are clamped to 0.

    Example:
        dur_str(2 * 86400 + 3 * 3600 + 600)
    """
    seconds = max(0, int(seconds))
    days, rem = divmod(seconds, 86400)
    hours, rem = divmod(rem, 3600)
    mins, secs = divmod(rem, 60)
    return (f"{days}d " if days else "") + f"{hours:02d}:{mins:02d}:{secs:02d}"


def status_text(card: dict, now: float) -> str:
    """Card status with the live quota-reset countdown appended.

    usage: status_text <CARD> <NOW>
    returns: The status line, plus " · Resets in <countdown>" when a reset is set.

    Args:
        card (dict): Card mapping with optional "status" and "stopped" keys.
        now (float): Current epoch time for the countdown.

    Example:
        status_text({"status": "quota reached", "stopped": {"reset": 1757800000.0}},
                    1757796400.0)
    """
    text = card.get("status") or ""
    reset = (card.get("stopped") or {}).get("reset")
    if reset:
        text = f"{text} · Resets in {dur_str(reset - now)}"
    return text


def chip_str(col: dict) -> str:
    """Render a column's chip symbol and label, "*" prefixed when focused.

    usage: chip_str <COL>
    returns: e.g. "*● working" or "○ idle".

    Args:
        col (dict): Column dict with "focused" and "chip" keys.

    Example:
        chip_str({"focused": True, "chip": "working"})
    """
    star = "*" if col["focused"] else ""
    return f"{star}{CHIP_SYMBOL.get(col['chip'], '?')} {CHIP_LABEL[col['chip']]}"


ACCENT_ANSI = {"badge": "36", "grey": "37", "tab": "35", "desc": "97"}
AGENT_BADGE = {
    # kind -> (badge symbol, tab-title prefixes to color in place);
    # agents whose titles carry no prefix get the symbol prepended
    "omp": ("π", ("π",)),
    "opencode": ("OC", ("OpenCode", "OC")),
    "agy": ("AG", ()),
    "freebuff": ("FB", ()),
    "cline": ("CL", ()),
}


def head_parts(col: dict) -> list[tuple[str, str | None]]:
    """Rule segments: chip state, grey (), magenta tab, cyan badge, white desc.

    usage: head_parts <COL>
    returns: (text, kind) segments; kind is an ACCENT_ANSI key or None for plain.

    Args:
        col (dict): Column dict with chip, tab_name, agent, and header keys.

    Example:
        head_parts({"focused": False, "chip": "working", "tab_name": "auth",
                    "agent": "omp", "header": "π refactoring"})
    """
    parts: list[tuple[str, str | None]] = [(f"({chip_str(col)})", None)]
    if col.get("tab_name"):
        parts.append((" (", "grey"))
        parts.append((col["tab_name"], "tab"))
        parts.append((")", "grey"))
    header = col["header"]
    symbol, prefixes = AGENT_BADGE.get(col["agent"], ("", ()))
    prefix = next((p for p in prefixes if header.startswith(p)), "")
    if prefix:
        parts.append((f" {prefix}", "badge"))
        rest = header[len(prefix):]
        if rest:
            parts.append((rest, "desc"))
    elif symbol:
        parts.append((f" {symbol}", "badge"))
        parts.append((f" {header}", "desc"))
    else:
        parts.append((f" {header}", "desc"))
    return parts


def meta_str(col: dict) -> str:
    """Build the "agent · tab · pid · mem · updated" metadata line.

    usage: meta_str <COL>
    returns: " · "-joined metadata string, omitting absent fields.

    Args:
        col (dict): Column dict with agent, tab, pid, rss, and age keys.

    Example:
        meta_str({"agent": "omp", "tab": "t-9", "pid": 4242,
                  "rss": 3500000, "age": 90.0})
    """
    parts = [col["agent"]] if col["agent"] else []
    if col["tab"]:
        parts.append(col["tab"])
    if col.get("pid"):
        parts.append(f"pid {col['pid']}")
    if col.get("rss"):
        parts.append("mem " + rss_str(col["rss"]))
    if col["age"] is not None:
        parts.append("updated " + age_str(col["age"]))
    return " · ".join(parts)


# --------------------------------------------------------------------------
# one-shot ANSI render
# --------------------------------------------------------------------------

def compact_parts(col: dict) -> list[tuple[str, str | None]]:
    """Compact-line segments: rule head plus the current status tail.

    usage: compact_parts <COL>
    returns: (text, kind) segments ending with the status text when present.

    Args:
        col (dict): Column dict; its "text" is appended when non-empty.

    Example:
        compact_parts({"focused": False, "chip": "working", "text": "todo 2/5"})
    """
    parts = head_parts(col)
    if col["text"]:
        parts += [(" · ", "grey"), (col["text"], "desc")]
    return parts


def compact_line(col: dict, width: int) -> str:
    """Plain one-line summary for one-shot / service frames.

    usage: compact_line <COL> <WIDTH>
    returns: Concatenated segment texts truncated to width columns.

    Args:
        col (dict): Column dict to summarize.
        width (int): Maximum line width in columns.

    Example:
        compact_line(cols[0], 58)
    """
    return "".join(t for t, _ in compact_parts(col))[:width]


def render_frame(cols: list, herdr_ok: bool, color: bool,
                 compact: bool = False, width: int = 118,
                 trail: bool = False) -> str:
    """Render the whole board as a text frame.

    Args:
        cols: Column dicts from build_columns().
        herdr_ok: False appends "herdr snapshot unreachable" to the header.
        color: When True, segments are wrapped in ANSI color escapes.
        compact: One line per agent in two columns.
        width: Frame width in columns.
        trail: Also print each column's last four step entries; off by
            default so the frame stays on the current status line.

    Returns:
        The frame text: a header line plus one block per agent (or compact rows).

    Example:
        print(render_frame(cols, herdr_ok=True, color=False, compact=True))
    """
    ansi = {1: "32", 2: "31", 3: "36", 4: "33"}
    on = (lambda code, s: f"\x1b[{code}m{s}\x1b[0m") if color else (lambda code, s: s)
    active = sum(1 for c in cols
                 if c["chip"] in ("working", "blocked", "input"))
    head = f"agent_board · {len(cols)} agents · {active} active · {time.strftime('%H:%M:%S')}"
    if herdr_ok is False:
        head += " · herdr snapshot unreachable"
    lines = [on("1", head) + on(ACCENT_ANSI["grey"], f"  ({__version__})")]
    if compact:
        half = max(24, (width - 3) // 2)
        split = (len(cols) + 1) // 2
        for i in range(split):
            left = cols[i]
            row = compact_line(left, half).ljust(half)
            if split + i < len(cols):
                right = cols[split + i]
                row += " │ " + compact_line(right, half)
            lines.append(row)
        return "\n".join(lines)
    for i, c in enumerate(cols):
        code = ansi.get(CHIP_COLOR.get(c["chip"], 0), "0")
        lines.append(on(code, "┌─ ") + "".join(
            on(ACCENT_ANSI.get(k or "", code), t) for t, k in head_parts(c)))
        lines.append("│ " + meta_str(c))
        if c["text"]:
            lines.append("│ " + on(code, "● ") + c["text"])
        for e in (c["log"][-4:] if trail else []):
            ts = time.strftime("%H:%M", time.localtime(e["t"]))
            lines.append(f"│   · [{ts}] {e['k']}: {e['m']}")
        lines.append("└")
        if i < len(cols) - 1:
            lines.append("")  # exactly one empty line between agents
    return "\n".join(lines)


def render_once(cols: list, herdr_ok: bool, compact: bool = False,
                trail: bool = False) -> None:
    """Print one ANSI-colored frame to stdout (--once mode).

    Args:
        cols: Column dicts from build_columns().
        herdr_ok: False appends "herdr snapshot unreachable" to the header.
        compact: One line per agent in two columns.
        trail: Also print each column's step entries; off by default.

    Example:
        render_once(cols, herdr_ok=True, compact=True)
    """
    print(render_frame(cols, herdr_ok, color=True, compact=compact,
                       trail=trail))


# --------------------------------------------------------------------------
# fullscreen TUI
# --------------------------------------------------------------------------

def accent_attr(kind: str | None, chip: int) -> int:
    """curses attr for a rule segment kind; chip attr for the state.

    usage: accent_attr <KIND> <CHIP>
    returns: A curses attribute int usable with addnstr().

    Args:
        kind (str, optional): Segment kind ("badge", "tab", "grey", "desc",
            "meta", "text", "trail") or None.
        chip (int): Fallback curses attribute used when kind is None.

    Example:
        accent_attr("badge", curses.A_BOLD)
    """
    if kind == "badge":
        return curses.color_pair(3) | curses.A_BOLD
    if kind == "tab":
        return curses.color_pair(5) | curses.A_BOLD
    if kind == "grey":
        return curses.color_pair(6)
    if kind == "desc":
        return curses.color_pair(6) | curses.A_BOLD
    if kind == "meta":
        return curses.A_DIM
    if kind == "text":
        return curses.A_BOLD
    if kind == "trail":
        return curses.A_NORMAL
    return chip


def draw_parts(stdscr, y: int, x: int, parts: list[tuple[str, str | None]],
               chip: int, limit: int) -> int:
    """Draw (text, kind) segments left to right within `limit` columns.

    usage: draw_parts <STDSCR> <Y> <X> <PARTS> <CHIP> <LIMIT>
    returns: The x position after the last drawn segment.

    Args:
        stdscr: curses window to draw on.
        y (int): Row to draw on.
        x (int): Starting column.
        parts (list): (text, kind) segments from head_parts()/compact_parts().
        chip (int): Fallback curses attribute for unstyled segments.
        limit (int): Rightmost column; drawing stops there.

    Example:
        x = draw_parts(stdscr, 2, 0, head_parts(col), chip, 60)
    """
    for text, kind in parts:
        if x >= limit:
            break
        n = min(len(text), limit - x)
        stdscr.addnstr(y, x, text, n, accent_attr(kind, chip))
        x += n
    return x


def column_lines(col: dict, width: int, num: int = 0,
                 trail: bool = False) -> list[list[tuple[str, str | None]]]:
    """Pre-render one column as rows of (text, kind) segments for the TUI.

    Args:
        col: Column dict to render.
        width: Rightmost column; head segments are truncated there.
        num: 1-based column number shown in the rule.
        trail: Also append the last four step entries of the column; off by
            default so the column stays on the current status line.

    Returns:
        Rows: rule head (number, "┌─", chip, tab, badge, header segments on
        ONE row), meta line, optional status and trail lines, closing "└".
        Kinds are draw_parts()/accent_attr() keys; the consumer supplies the
        chip color.

    Example:
        block = column_lines(cols[0], 80, num=1)
    """
    head: list[tuple[str, str | None]] = []
    x = 0
    segs = [(f"{num} ", "grey")] if num else []
    for text, kind in segs + [("┌─ ", None)] + head_parts(col):
        if x >= width:
            break
        n = min(len(text), width - x)
        head.append((text[:n], kind))
        x += n
    rows: list[list[tuple[str, str | None]]] = [head]
    rows.append([("│ " + meta_str(col), "meta")])
    if col["text"]:
        rows.append([("│ ● " + col["text"], "text")])
    for e in (col["log"][-4:] if trail else []):
        ts = time.strftime("%H:%M", time.localtime(e["t"]))
        rows.append([(f"│   · [{ts}] {e['k']}: {e['m']}", "trail")])
    rows.append([("└", "meta")])
    return rows


def column_at_click(row_map: dict, my: int, mx: int, compact: bool, half: int) -> int | None:
    """Column index under a mouse click, or None when nothing was hit.

    usage: column_at_click <ROW_MAP> <MY> <MX> <COMPACT> <HALF>
    returns: Column index; in compact mode the right half selects the row's second column.

    Args:
        row_map (dict): Row (y) to column index, or (left, right) pair in compact mode.
        my (int): Click row.
        mx (int): Click column.
        compact (bool): Whether the compact two-column layout is active.
        half (int): Width of each compact half.

    Example:
        ci = column_at_click(row_map, my, mx, compact, half)
    """
    hit = row_map.get(my)
    if hit is None:
        return None
    if compact:
        left, right = hit
        if mx > half + 1 and right is not None:
            return right
        return left
    return hit


def run_tui(stdscr, herdr_bin: str, poll_period: float, stale_after: float,
            compact: bool = False, trail: bool = False) -> None:
    """Fullscreen curses board loop: poll, render, and handle keys/mouse.

    Args:
        stdscr: curses standard screen handed over by curses.wrapper().
        herdr_bin: herdr binary for snapshots and tab focus.
        poll_period: Seconds between snapshot/card refreshes.
        stale_after: External card age in seconds before the "stale" chip.
        compact: One line per agent in two columns.
        trail: Also draw each column's step entries; off by default so the
            board stays on the current status lines.

    Example:
        curses.wrapper(run_tui, "herdr", 30.0, 600.0, False)
    """
    curses.curs_set(0)
    curses.start_color()
    curses.use_default_colors()
    for pair, fg in ((1, curses.COLOR_GREEN), (2, curses.COLOR_RED),
                     (3, curses.COLOR_CYAN), (4, curses.COLOR_YELLOW),
                     (5, curses.COLOR_MAGENTA), (6, curses.COLOR_WHITE)):
        curses.init_pair(pair, fg, -1)
    try:
        curses.mousemask(curses.BUTTON1_CLICKED | curses.BUTTON1_RELEASED
                         | curses.BUTTON1_DOUBLE_CLICKED)
        curses.mouseinterval(150)
    except curses.error:
        pass  # terminal without mouse support: keyboard only

    offset = 0
    last_poll = 0.0
    row_map: dict = {}
    half = 0
    focus_buf = ""
    cols: list = []
    herdr_ok: bool | None = None
    while True:
        now = time.time()
        if now - last_poll >= poll_period:
            cols, herdr_ok = gather_columns(herdr_bin, now, stale_after)
            last_poll = now

        h, w = stdscr.getmaxyx()
        if compact:
            total = (len(cols) + 1) // 2
        else:
            blocks = [column_lines(c, w, num=i + 1, trail=trail)
                      for i, c in enumerate(cols)]
            total = sum(len(b) + 1 for b in blocks)
        offset = max(0, min(offset, total - (h - 4)))
        active = sum(1 for c in cols
                     if c["chip"] in ("working", "blocked", "input"))
        head = f" agent_board · {len(cols)} agents · {active} active"
        if herdr_ok is False:
            head += " · herdr snapshot unreachable"
        stdscr.erase()
        stdscr.addnstr(0, 0, head, w - 1, curses.A_BOLD)
        if len(head) + 2 < w - 1:
            stdscr.addnstr(0, len(head), f"  ({__version__})",
                           w - len(head) - 1, curses.color_pair(6))
        if compact:
            half = max(24, (w - 3) // 2)
            split = (len(cols) + 1) // 2
            y = 2 - offset
            for i in range(split):
                right = split + i if split + i < len(cols) else None
                if 1 <= y < h - 1:
                    row_map[y] = (i, right)
                    left = cols[i]
                    chip = curses.color_pair(
                        CHIP_COLOR.get(left["chip"], 0)) | curses.A_BOLD
                    draw_parts(stdscr, y, 1,
                               [(f"{i + 1} ", "grey")] + compact_parts(left),
                               chip, min(half, w - 1))
                if right is not None and 1 <= y < h - 1:
                    right_col = cols[right]
                    stdscr.addnstr(y, half + 1, "│", w - 1, curses.A_DIM)
                    chip = curses.color_pair(
                        CHIP_COLOR.get(right_col["chip"], 0)) | curses.A_BOLD
                    draw_parts(stdscr, y, half + 3,
                               [(f"{right + 1} ", "grey")]
                               + compact_parts(right_col),
                               chip, half + 3 + min(half, w - half - 3))
                y += 1
        else:
            y = 2 - offset
            for bi, block in enumerate(blocks):
                chip = curses.color_pair(
                    CHIP_COLOR.get(cols[bi]["chip"], 0)) | curses.A_BOLD
                for row in block:
                    if 1 <= y < h - 1:
                        draw_parts(stdscr, y, 0, row, chip, w - 1)
                        row_map[y] = bi
                    y += 1
                y += 1
        foot = " q/Ctrl+C quit · ↑/↓ or j/k scroll · click column = focus tab "
        if focus_buf:
            foot = f" focus #{focus_buf} - Enter jumps, Esc cancels ·"
        stdscr.addnstr(h - 1, 0, foot, w - 1, curses.A_DIM)
        stdscr.refresh()

        stdscr.timeout(250)
        try:
            key = stdscr.getch()
        except KeyboardInterrupt:
            return  # Ctrl+C quits the board; curses.wrapper restores the tty
        if key == 3:
            return  # a terminal handing Ctrl+C over as a key, not as SIGINT
        if key == curses.KEY_MOUSE:
            try:
                _, mx, my, _, bstate = curses.getmouse()
            except curses.error:
                continue
            if bstate & (curses.BUTTON1_CLICKED | curses.BUTTON1_RELEASED
                         | curses.BUTTON1_DOUBLE_CLICKED):
                ci = column_at_click(row_map, my, mx, compact, half)
                if ci is not None and cols[ci].get("tab"):
                    with contextlib.suppress(OSError, subprocess.SubprocessError):
                        subprocess.run([herdr_bin, "tab", "focus",
                                        cols[ci]["tab"]],
                                       capture_output=True, timeout=5)
                continue
        if key in (ord("q"), ord("Q")):
            return
        if key in (curses.KEY_DOWN, ord("j")):
            offset += 3
        elif key in (curses.KEY_UP, ord("k")):
            offset -= 3
        elif key == curses.KEY_NPAGE:
            offset += h - 4
        elif key == curses.KEY_PPAGE:
            offset -= h - 4
        elif key in (curses.KEY_HOME, ord("g")):
            offset = 0
        elif key in (10, 13, curses.KEY_ENTER):
            if focus_buf:
                num = int(focus_buf) if focus_buf.isdigit() else 0
                if 1 <= num <= len(cols) and cols[num - 1].get("tab"):
                    with contextlib.suppress(OSError, subprocess.SubprocessError):
                        subprocess.run([herdr_bin, "tab", "focus",
                                        cols[num - 1]["tab"]],
                                       capture_output=True, timeout=5)
                focus_buf = ""
            continue
        elif key in (curses.KEY_BACKSPACE, 127, 263):
            focus_buf = focus_buf[:-1]
            continue
        elif key == 27:  # Esc cancels the number prompt
            focus_buf = ""
            continue
        elif 48 <= key <= 57 and len(focus_buf) < 3:
            focus_buf += chr(key)
            continue


def run_serve(herdr_bin: str, poll_period: float, stale_after: float,
              frame_path: str, trail: bool = False) -> None:
    """Headless loop for the systemd service: keep the frame file fresh.

    Args:
        herdr_bin: herdr binary for the liveness snapshot.
        poll_period: Seconds between frame re-renders (minimum 1, enforced
            by main()).
        stale_after: External card age in seconds before the "stale" chip.
        frame_path: Path of the frame file rewritten atomically each cycle;
            its directory is created when it does not exist yet.
        trail: Also write each column's step entries; off by default.

    Example:
        run_serve("herdr", 30.0, 600.0, FRAME_PATH)
    """
    os.makedirs(os.path.dirname(frame_path) or ".", exist_ok=True)
    while True:
        cols, herdr_ok = gather_columns(herdr_bin, time.time(), stale_after)
        frame = render_frame(cols, herdr_ok=herdr_ok, color=False, trail=trail)
        tmp = frame_path + ".tmp"
        with open(tmp, "w") as f:
            f.write(frame + "\n")
        os.replace(tmp, frame_path)
        time.sleep(poll_period)


# --------------------------------------------------------------------------

HELP_EPILOG = """examples:
  agent_board.py                             fullscreen TUI (q or Ctrl+C quits,
                                             j/k scrolls)
  agent_board.py --trail                      TUI including the step trails
  agent_board.py --once                       print a single frame (for `watch`)
  agent_board.py --compact --once             one line per agent, two columns
  agent_board.py note register -m "goal"      open your column
  agent_board.py note step -m "todo 2/5 ..."  status line + visible trail entry
  agent_board.py note update -m "pytest -k"   replace the status line only
  agent_board.py note done -m "PR #12 green"  mark done (✓), appended to trail
  agent_board.py note input -m "A or B?"      ask the user (yellow chip)
  agent_board.py note quota -m "limit" --reset 2d 3h   stopped + countdown
  agent_board.py note stop                    remove your column
"""

NOTE_EPILOG = """actions:
  register  first post: opens the column (header = herdr tab title)
  update    replace the current status line only
  step      replace the status line and append to the visible trail
  input     waiting on the user: yellow chip + question in the trail;
            your next step/update clears it automatically
  quota     stopped by a rate/quota limit: red chip, status text plus a
            live "Resets in" countdown when --reset is given; your next
            step/update clears it automatically
  stop      remove your column (only needed outside herdr)

examples:
  agent_board.py note register -m "refactoring auth module"
  agent_board.py note step     -m "todo 2/5: rewrite token refresh"
  agent_board.py note update   -m "running pytest -k auth"
  agent_board.py note done     -m "PR #12 opened, tests green"
  agent_board.py note input    -m "A) keep B) revert?"
  agent_board.py note quota    -m "Individual quota reached." --reset 2d 3h
"""


def _use_color() -> bool:
    """Decide whether ANSI color escapes should be emitted.

    usage: _use_color
    returns: False with NO_COLOR, True with FORCE_COLOR, else stdout isatty().

    Example:
        if _use_color():
            print("\x1b[1mbold\x1b[0m")
    """
    if os.environ.get("NO_COLOR"):
        return False
    if os.environ.get("FORCE_COLOR"):
        return True
    return sys.stdout.isatty()


def colorize_help(text: str) -> str:
    """ANSI coloring for argparse output: headings, flags, metavars.

    usage: colorize_help <TEXT>
    returns: The text with ANSI escapes, or unchanged when color is disabled.

    Args:
        text (str): argparse help or usage output to colorize.

    Example:
        print(colorize_help(parser.format_help()))
    """
    if not _use_color():
        return text

    def flag(m: re.Match) -> str:
        """Cyan-wrap a matched argparse flag.

        usage: flag <MATCH>
        returns: The match wrapped in cyan ANSI escapes.

        Args:
            m (re.Match): Regex match whose group(1) holds the flag text.

        Example:
            flag(re.match(r"(--help)", "--help"))
        """
        return f"\x1b[36m{m.group(1)}\x1b[0m"

    def meta(m: re.Match) -> str:
        """Bold-yellow-wrap a matched ALL-CAPS metavariable.

        usage: meta <MATCH>
        returns: The match wrapped in bold-yellow ANSI escapes.

        Args:
            m (re.Match): Regex match whose group(1) holds the text.

        Example:
            meta(re.match(r"(POLL_PERIOD)", "POLL_PERIOD"))
        """
        return f"\x1b[1;33m{m.group(1)}\x1b[0m"

    def head(m: re.Match) -> str:
        """Bold-yellow-wrap a matched help-section heading.

        usage: head <MATCH>
        returns: The heading with a bold-yellow section name and colon.

        Args:
            m (re.Match): Regex match; group(1) indent, group(2) heading.

        Example:
            head(re.match(r"(options:)", "options:"))
        """
        return f"{m.group(1)}\x1b[1;33m{m.group(2)}\x1b[0m:"

    text = re.sub(r"(?m)^(\s*)([a-z][a-z ]*[a-z]):[ \t]*$", head, text)
    text = re.sub(r"(?m)^usage: ", "\x1b[1musage: \x1b[0m", text)
    text = re.sub(r"(?<![\w-])([A-Z][A-Z0-9_]{3,})(?![\w])", meta, text)
    text = re.sub(r"(?<![\w-])(-{1,2}[A-Za-z][\w-]*)", flag, text)
    return text


class _ColoredParser(argparse.ArgumentParser):
    """argparse parser that colorizes its help/usage on a TTY."""

    def format_help(self) -> str:
        """Return the parser help text, colorized when the output is a TTY.

        usage: format_help
        returns: The colorized help text as a string.

        Example:
            help_text = _ColoredParser(prog="agent_board").format_help()
        """
        return colorize_help(super().format_help())

    def format_usage(self) -> str:
        """Return the parser usage line, colorized when the output is a TTY.

        usage: format_usage
        returns: The colorized usage line as a string.

        Example:
            usage_line = _ColoredParser(prog="agent_board").format_usage()
        """
        return colorize_help(super().format_usage())


def build_parser() -> argparse.ArgumentParser:
    """Build the agent_board argument parser: options plus note/serve subcommands.

    Returns:
        The configured parser (colored help, all flags and subcommands).

    Example:
        args = build_parser().parse_args(["--once"])
    """
    ap = _ColoredParser(
        prog="agent_board", description=__doc__, epilog=HELP_EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--version", action="version",
                    version=f"%(prog)s {__version__}",
                    help="print the version and exit")
    ap.add_argument("--once", action="store_true",
                    help="render one frame and exit (no curses)")
    ap.add_argument("--compact", action="store_true",
                    help="compact layout: one line per agent, two columns")
    ap.add_argument("--trail", action="store_true",
                    help="also show each agent's step trail (off: status line only)")
    ap.add_argument("--poll-period", "--autorefresh", dest="poll_period",
                    type=float, default=30.0, metavar="SECONDS",
                    help="snapshot poll / frame autorefresh period (s, "
                         "default 30; minimum 1)")
    ap.add_argument("--stale-seconds", type=float, default=600,
                    metavar="SECONDS",
                    help="external card age before 'stale' (s)")
    ap.add_argument("--herdr-bin", default="herdr", metavar="BIN",
                    help="herdr binary for the liveness snapshot")
    sub = ap.add_subparsers(dest="cmd", parser_class=_ColoredParser)
    note = sub.add_parser(
        "note", formatter_class=argparse.RawDescriptionHelpFormatter,
        help="post a status to the board (agent side)",
        description="Post one status line to the board from inside the "
                    "agent; `step` and `done` also append to the column's "
                    "visible trail.",
        epilog=NOTE_EPILOG)
    note.add_argument("action",
                      choices=["register", "update", "step", "done", "input",
                               "quota", "stop"],
                      help="see the action table below")
    note.add_argument("-m", "--msg", metavar="MSG",
                      help="status line (required unless stop)")
    note.add_argument("--pane", metavar="PANE",
                      help="override pane id (default $HERDR_PANE_ID / tty)")
    note.add_argument("--reset", metavar="WHEN",
                      help="for 'quota': when the limit resets - ISO time, "
                           "duration (2d 4h 30m / 90m), or seconds")
    note.add_argument("--tab", metavar="TAB", help="override tab id")
    note.add_argument("--header", metavar="HEADER",
                      help="override column header "
                           "(default: herdr tab title at register)")
    note.add_argument("--agent", metavar="AGENT",
                      help="override agent kind label")
    sub.add_parser(
        "serve", formatter_class=argparse.RawDescriptionHelpFormatter,
        help="headless loop: keep the board frame file fresh (service mode)",
        description="Headless loop for the systemd service: re-renders the "
                    "board to ~/.local/state/agent_board/board.txt every "
                    "--poll-period seconds (default 30, minimum 1).")
    return ap


def main(argv: list[str] | None = None) -> int:
    """Parse arguments and dispatch to the TUI, frame, note, or service path.

    Args:
        argv: Command-line arguments; None uses sys.argv[1:].

    Returns:
        Process exit code: 0 on success, 2 on a missing -m/--msg. A Ctrl+C
        during the TUI or `serve` counts as a normal quit: curses has
        restored the terminal, no traceback is printed, and the exit code
        stays 0.

    Example:
        sys.exit(main(["note", "step", "-m", "todo 2/5"]))
    """
    ns = build_parser().parse_args(argv)

    if ns.cmd == "note":
        return cmd_note(ns, ns.herdr_bin)

    if ns.cmd == "serve":
        # Ctrl+C stops the frame writer without a traceback
        with contextlib.suppress(KeyboardInterrupt):
            run_serve(shutil.which(ns.herdr_bin) or ns.herdr_bin,
                      max(1.0, ns.poll_period), ns.stale_seconds, FRAME_PATH,
                      ns.trail)
        return 0
    herdr_bin = shutil.which(ns.herdr_bin) or ns.herdr_bin
    # Ctrl+C quits the board; curses.wrapper already restored the terminal
    with contextlib.suppress(KeyboardInterrupt):
        if ns.once:
            cols, herdr_ok = gather_columns(herdr_bin, time.time(),
                                            ns.stale_seconds)
            render_once(cols, herdr_ok=herdr_ok, compact=ns.compact,
                        trail=ns.trail)
            return 0
        curses.wrapper(run_tui, herdr_bin,
                       max(1.0, ns.poll_period), ns.stale_seconds, ns.compact,
                       ns.trail)
    return 0


if __name__ == "__main__":
    sys.exit(main())