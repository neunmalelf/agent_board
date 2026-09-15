#!/usr/bin/env python3
"""agent-board — a live status board for coding agents.

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
is the source of truth for liveness: a column disappears the moment the
agent's pane closes. Cards carry the free-text progress ("what is it doing",
"what has it done"). Agents outside herdr get a column too; it disappears on
`note stop` or after --stale-seconds without an update.

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

__version__ = "2.4.20260915172753Z"

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

def herdr_agents(herdr_bin: str) -> tuple[list | None, list]:
    """(live agents, snapshot tabs), or (None, []) when unreachable.

    usage: herdr_agents <HERDR_BIN>
    returns: (agents, tabs) lists parsed from the herdr api snapshot on success.
    errors: (None, []) when herdr exits nonzero, cannot be run, or returns malformed JSON.

    Args:
        herdr_bin (str): Path or name of the herdr binary to query.

    Example:
        agents, tabs = herdr_agents("herdr")
    """
    try:
        out = subprocess.run([herdr_bin, "api", "snapshot"],
                             capture_output=True, text=True, timeout=10)
        if out.returncode != 0:
            return None, []
        data = json.loads(out.stdout)
        snap = data.get("result", {}).get("snapshot", {})
        agents = snap.get("agents", [])
        if not isinstance(agents, list):
            return None, []
        tabs = [t for t in snap.get("tabs") or [] if t.get("tab_id")]
        return agents, tabs
    except (OSError, ValueError, subprocess.SubprocessError):
        return None, []


def herdr_match(agents: list | None, pane_id: str, tab_id: str) -> dict | None:
    """Find the herdr agent matching a pane or tab id.

    usage: herdr_match <AGENTS> <PANE_ID> <TAB_ID>
    returns: The matching agent dict, or None when no entry matches.

    Args:
        agents (list, optional): herdr agent dicts; None or empty searches nothing.
        pane_id (str): Pane id to match; empty skips this criterion.
        tab_id (str): Tab id to match; empty skips this criterion.

    Example:
        agent = herdr_match(agents, "p-1a2b", "")
    """
    for a in agents or []:
        if pane_id and a.get("pane_id") == pane_id:
            return a
        if tab_id and a.get("tab_id") == tab_id:
            return a
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
    """Handle `note <action>`: create, update, or remove this agent's card.

    usage: cmd_note <NS> <HERDR_BIN>
    returns: 0 after posting, updating, or removing the card.
    errors: 2 when -m/--msg is missing for an action that requires it.

    Args:
        ns (argparse.Namespace): Parsed `note` subcommand arguments.
        herdr_bin (str): herdr binary used to look up the agent snapshot.

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

    agents, _ = herdr_agents(herdr_bin)
    match = herdr_match(agents, pane, tab)
    card = read_card(path)

    if ns.action == "register" or card is None:
        header = (ns.header or "").strip()
        if not header:
            title = clean_title(match.get("terminal_title_stripped")
                                or match.get("terminal_title") or "") if match else ""
            header = title or f"{socket.gethostname()}:{os.getcwd()}"
        card = {"pane_id": pane, "tab_id": tab, "header": header[:MAX_HEADER],
                "agent": ns.agent or (match or {}).get("agent") or "",
                "herdr": ns.pane is None and bool(os.environ.get("HERDR_PANE_ID")),
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
    "kilo": {"kilo"}, "qoder": {"qoder"},
}


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


# --------------------------------------------------------------------------
# viewer: merge snapshot + cards into columns
# --------------------------------------------------------------------------

def build_columns(agents: list | None, cards: dict, now: float, stale_after: float,
                  procs: tuple | None = None, tabs: list | None = None) -> list:
    """Merge herdr agents (liveness) with posted cards (free text).

    usage: build_columns <AGENTS> <CARDS> <NOW> <STALE_AFTER> [PROCS] [TABS]
    returns: Column dicts sorted by status priority, then card age.

    Args:
        agents (list, optional): herdr agent dicts; None = snapshot unavailable, so
            herdr-owned cards are hidden (unknown liveness) but not deleted.
        cards (dict): Posted cards keyed by pane_id.
        now (float): Current epoch time, base for card ages and staleness.
        stale_after (float): External card age in seconds before the "stale" chip.
        procs (tuple, optional): (by_tty, by_kind) from scan_procs() for pid/RSS lookup.
        tabs (list, optional): Snapshot tab list; every tab without a detected agent gets
            its own column (agent kind unknown) so no herdr tab can go missing.

    Example:
        cols = build_columns(agents, cards, time.time(), 600.0, procs=procs, tabs=tabs)
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
            "chip": ("done" if card.get("done")
                     else "stopped" if card.get("stopped")
                     else "input" if card.get("input")
                     else (a.get("agent_status") or "unknown")),
            "focused": bool(a.get("focused")),
            "text": status_text(card, now),
            "log": card.get("log") or [],
            "age": (now - card["updated"]) if card.get("updated") else None,
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


def sweep(cards: dict, agents: list | None) -> None:
    """Delete herdr-owned cards whose pane has closed (agent stopped).

    usage: sweep <CARDS> <AGENTS>
    returns: None; matching card files are removed, or nothing happens when
        agents is None (snapshot unavailable: keep everything).

    Args:
        cards (dict): Cards keyed by pane_id, as returned by load_cards().
        agents (list, optional): Live herdr agent dicts; None disables sweeping.

    Example:
        sweep(cards, agents)
    """
    if agents is None:
        return  # snapshot unavailable: keep everything
    live = {str(a.get("pane_id")) for a in agents}
    for pane, card in cards.items():
        if card.get("herdr") and pane not in live:
            drop_card(pane)


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
                 compact: bool = False, width: int = 118) -> str:
    """Render the whole board as a text frame.

    usage: render_frame <COLS> <HERDR_OK> <COLOR> [COMPACT] [WIDTH]
    returns: The frame text: a header line plus one block per agent (or compact rows).

    Args:
        cols (list): Column dicts from build_columns().
        herdr_ok (bool): False appends "herdr snapshot unreachable" to the header.
        color (bool): When True, segments are wrapped in ANSI color escapes.
        compact (bool, optional): One line per agent in two columns. Defaults to False.
        width (int, optional): Frame width in columns. Defaults to 118.

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
        for e in c["log"][-4:]:
            ts = time.strftime("%H:%M", time.localtime(e["t"]))
            lines.append(f"│   · [{ts}] {e['k']}: {e['m']}")
        lines.append("└")
        if i < len(cols) - 1:
            lines.append("")  # exactly one empty line between agents
    return "\n".join(lines)


def render_once(cols: list, herdr_ok: bool, compact: bool = False) -> None:
    """Print one ANSI-colored frame to stdout (--once mode).

    usage: render_once <COLS> <HERDR_OK> [COMPACT]
    returns: None; the frame is printed to stdout in color.

    Args:
        cols (list): Column dicts from build_columns().
        herdr_ok (bool): False appends "herdr snapshot unreachable" to the header.
        compact (bool, optional): One line per agent in two columns. Defaults to False.

    Example:
        render_once(cols, herdr_ok=True, compact=True)
    """
    print(render_frame(cols, herdr_ok, color=True, compact=compact))


# --------------------------------------------------------------------------
# fullscreen TUI
# --------------------------------------------------------------------------

def accent_attr(kind: str | None, chip: int) -> int:
    """curses attr for a rule segment kind; chip attr for the state.

    usage: accent_attr <KIND> <CHIP>
    returns: A curses attribute int usable with addnstr().

    Args:
        kind (str, optional): Segment kind ("badge", "tab", "grey", "desc") or None.
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


def column_lines(col: dict, width: int, num: int = 0) -> list[tuple[str, int]]:
    """Pre-render one column as (text, attr) lines for the fullscreen TUI.

    usage: column_lines <COL> <WIDTH> [NUM]
    returns: Lines: rule head, meta line, optional status and trail, closing "└".

    Args:
        col (dict): Column dict from build_columns().
        width (int): Maximum rule width in columns.
        num (int, optional): 1-based column number shown in the rule. Defaults to 0.

    Example:
        block = column_lines(cols[0], 80, num=1)
    """
    chip = curses.color_pair(CHIP_COLOR.get(col["chip"], 0)) | curses.A_BOLD
    lines = []
    x = 0
    segs = [(f"{num} ", "grey")] if num else []
    for text, kind in segs + [("┌─ ", None)] + head_parts(col):
        if x >= width:
            break
        n = min(len(text), width - x)
        lines.append((text[:n], accent_attr(kind, chip)))
        x += n
    lines.append(("│ " + meta_str(col), curses.A_DIM))
    if col["text"]:
        lines.append(("│ ● " + col["text"], curses.A_BOLD))
    for e in col["log"][-4:]:
        ts = time.strftime("%H:%M", time.localtime(e["t"]))
        lines.append((f"│   · [{ts}] {e['k']}: {e['m']}", curses.A_NORMAL))
    lines.append(("└", curses.A_DIM))
    return lines


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
            compact: bool = False) -> None:
    """Fullscreen curses board loop: poll, render, and handle keys/mouse.

    usage: run_tui <STDSCR> <HERDR_BIN> <POLL_PERIOD> <STALE_AFTER> [COMPACT]
    returns: None when the user quits with q/Q; runs until then.

    Args:
        stdscr: curses standard screen handed over by curses.wrapper().
        herdr_bin (str): herdr binary for snapshots and tab focus.
        poll_period (float): Seconds between snapshot/card refreshes.
        stale_after (float): External card age in seconds before the "stale" chip.
        compact (bool, optional): One line per agent in two columns. Defaults to False.

    Example:
        curses.wrapper(run_tui, "herdr", 2.0, 600.0, False)
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
    cols, herdr_ok = [], None
    while True:
        now = time.time()
        if now - last_poll >= poll_period:
            agents, tabs = herdr_agents(herdr_bin)
            herdr_ok = agents is not None
            cards = load_cards()
            sweep(cards, agents)
            cols = build_columns(agents, cards, now, stale_after,
                                 procs=scan_procs(), tabs=tabs)
            last_poll = now

        h, w = stdscr.getmaxyx()
        if compact:
            total = (len(cols) + 1) // 2
        else:
            blocks = [column_lines(c, w, num=i + 1)
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
                for text, attr in block:
                    if 1 <= y < h - 1:
                        stdscr.addnstr(y, 0, text, w - 1, attr)
                        row_map[y] = bi
                    y += 1
                y += 1
        foot = " q quit · ↑/↓ or j/k scroll · click column = focus tab "
        if focus_buf:
            foot = f" focus #{focus_buf} — Enter jumps, Esc cancels ·"
        stdscr.addnstr(h - 1, 0, foot, w - 1, curses.A_DIM)
        stdscr.refresh()

        stdscr.timeout(250)
        key = stdscr.getch()
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


def run_serve(herdr_bin: str, poll_period: float, stale_after: float, frame_path: str) -> None:
    """Headless loop for the systemd service: keep the frame file fresh.

    usage: run_serve <HERDR_BIN> <POLL_PERIOD> <STALE_AFTER> <FRAME_PATH>
    returns: None; this loop never exits.

    Args:
        herdr_bin (str): herdr binary for the liveness snapshot.
        poll_period (float): Seconds between frame re-renders (minimum 1, enforced by main()).
        stale_after (float): External card age in seconds before the "stale" chip.
        frame_path (str): Path of the frame file rewritten atomically each cycle.

    Example:
        run_serve("herdr", 2.0, 600.0, FRAME_PATH)
    """
    while True:
        agents, tabs = herdr_agents(herdr_bin)
        cards = load_cards()
        sweep(cards, agents)
        cols = build_columns(agents, cards, time.time(), stale_after,
                             procs=scan_procs(), tabs=tabs)
        frame = render_frame(cols, herdr_ok=agents is not None, color=False)
        tmp = frame_path + ".tmp"
        with open(tmp, "w") as f:
            f.write(frame + "\n")
        os.replace(tmp, frame_path)
        time.sleep(poll_period)


# --------------------------------------------------------------------------

HELP_EPILOG = """examples:
  agent_board.py                             fullscreen TUI (q quits, j/k scrolls)
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


def main(argv: list[str] | None = None) -> int:
    """Parse arguments and dispatch: TUI, one-shot frame, note posting, or service loop.

    usage: main [ARGV]
    returns: Process exit code: 0 on success, 2 on a missing -m/--msg.

    Args:
        argv (list, optional): Command-line arguments; None uses sys.argv[1:]. Defaults to None.

    Example:
        sys.exit(main(["note", "step", "-m", "todo 2/5"]))
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
    ap.add_argument("--poll-period", "--autorefresh", dest="poll_period",
                    type=float, default=2.0, metavar="SECONDS",
                    help="snapshot poll / frame autorefresh period (s)")
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
                      help="for 'quota': when the limit resets — ISO time, "
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
                    "board to ~/.local/state/agent-board/board.txt every "
                    "--poll-period seconds (minimum 1).")
    ns = ap.parse_args(argv)

    if ns.cmd == "note":
        return cmd_note(ns, ns.herdr_bin)

    if ns.cmd == "serve":
        run_serve(shutil.which(ns.herdr_bin) or ns.herdr_bin,
                  max(1.0, ns.poll_period), ns.stale_seconds, FRAME_PATH)
        return 0
    herdr_bin = shutil.which(ns.herdr_bin) or ns.herdr_bin
    agents, tabs = herdr_agents(herdr_bin)
    cards = load_cards()
    sweep(cards, agents)
    cols = build_columns(agents, cards, time.time(), ns.stale_seconds,
                         procs=scan_procs(), tabs=tabs)
    if ns.once:
        render_once(cols, herdr_ok=agents is not None, compact=ns.compact)
        return 0
    curses.wrapper(run_tui, herdr_bin,
                   max(1.0, ns.poll_period), ns.stale_seconds, ns.compact)
    return 0


if __name__ == "__main__":
    sys.exit(main())