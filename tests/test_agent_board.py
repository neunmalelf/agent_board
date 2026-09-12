"""Tests for the agent-board CLI (single-module script).

Run with:  python3 -m pytest tests/ -q
All filesystem state lives in temp dirs; herdr is never invoked (patched
or pointed at a nonexistent binary), so the suite is fast and isolated.
"""
import argparse
import importlib.machinery
import importlib.util
import json
import os
import re
import subprocess
import sys
import time
import unittest.mock as mock
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
MODULE_PATH = REPO / "agent_board.py"


def _load():
    loader = importlib.machinery.SourceFileLoader("agent_board_mod",
                                                  str(MODULE_PATH))
    spec = importlib.util.spec_from_file_location("agent_board_mod",
                                                  MODULE_PATH,
                                                  loader=loader)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


mod = _load()
HERDR_MISSING = "/nonexistent-herdr"


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def ns(action, msg=None, pane="t1", tab=None, header=None, agent=None,
       reset=None):
    return argparse.Namespace(action=action, msg=msg, pane=pane, tab=tab,
                              header=header, agent=agent, reset=reset)


def col(chip="working", **over):
    base = dict(pane="p1", agent="omp", tab="w1:t1", tab_name="tab",
                header="Title", chip=chip, focused=False, text="",
                log=[], age=None, pid=None, rss=None)
    base.update(over)
    return base


@pytest.fixture
def state(tmp_path, monkeypatch):
    monkeypatch.setattr(mod, "STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setattr(mod, "FRAME_PATH", str(tmp_path / "state" / "board.txt"))
    return tmp_path / "state"


# ---------------------------------------------------------------------------
# text helpers
# ---------------------------------------------------------------------------

def test_clean_title_strips_spinner_and_collapses_space():
    assert mod.clean_title("π \u280b Use parentheses in view modes") == \
        "π Use parentheses in view modes"
    assert mod.clean_title("a   b") == "a b"
    assert mod.clean_title(None) == ""
    assert mod.clean_title("") == ""


def test_age_str_format():
    assert mod.age_str(None) == ""
    assert mod.age_str(5) == "5s"
    assert mod.age_str(120) == "2m"
    assert mod.age_str(3 * 3600 + 5 * 60) == "3h05m"


def test_dur_str_countdown():
    assert mod.dur_str(0) == "00:00:00"
    assert mod.dur_str(-5) == "00:00:00"
    assert mod.dur_str(3 * 3600 + 5 * 60 + 4) == "03:05:04"
    assert mod.dur_str(2 * 86400 + 3 * 3600) == "2d 03:00:00"


def test_rss_str():
    assert mod.rss_str(None) == ""
    assert mod.rss_str(512) == "0M"
    assert mod.rss_str(569 * 1024) == "569M"
    assert mod.rss_str(2 * 1024 * 1024) == "2.0G"


def test_status_text_appends_live_countdown():
    card = {"status": "Individual quota reached."}
    now = 1000.0
    assert mod.status_text(card, now) == "Individual quota reached."
    card["stopped"] = {"reset": now + 2 * 86400 + 3 * 3600}
    assert mod.status_text(card, now) == \
        "Individual quota reached. · Resets in 2d 03:00:00"


# ---------------------------------------------------------------------------
# parse_reset
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("text,expected", [
    ("1d 02:03:04", 93784),
    ("02:03:04", 7384),
    ("2d 3h", 183600),
    ("90m", 5400),
    ("3h20m", 12000),
    ("3600", 3600),
    ("1d 12h", 129600),
])
def test_parse_reset_durations(text, expected):
    now = 1000.0
    assert mod.parse_reset(text, now) == pytest.approx(now + expected)


def test_parse_reset_iso_absolute():
    assert mod.parse_reset("2026-09-13T08:00:00Z", 1000.0) == \
        pytest.approx(1789286400.0)


def test_parse_reset_garbage_and_empty():
    assert mod.parse_reset("", 0) is None
    assert mod.parse_reset(None, 0) is None
    assert mod.parse_reset("not a time", 0) is None


# ---------------------------------------------------------------------------
# card storage
# ---------------------------------------------------------------------------

def test_card_roundtrip(state):
    card = {"pane_id": "p1", "status": "hello", "log": []}
    mod.save_card(card)
    assert mod.read_card(mod.card_path("p1"))["status"] == "hello"
    assert mod.load_cards()["p1"]["status"] == "hello"
    mod.drop_card("p1")
    assert mod.load_cards() == {}


def test_read_card_corrupt_json(state):
    path = Path(mod.card_path("bad"))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{not json")
    assert mod.read_card(path) is None
    assert mod.load_cards() == {}


def test_herdr_match():
    agents = [{"pane_id": "w1:p41", "tab_id": "w1:tV"},
              {"pane_id": "w1:p3R", "tab_id": "w1:t15"}]
    assert mod.herdr_match(agents, "w1:p3R", "")["tab_id"] == "w1:t15"
    assert mod.herdr_match(agents, "", "w1:tV")["pane_id"] == "w1:p41"
    assert mod.herdr_match(agents, "", "") is None
    assert mod.herdr_match(None, "x", "y") is None


def test_herdr_agents_parses_snapshot(monkeypatch):
    snap = {"agents": [{"pane_id": "p"}], "tabs": [{"tab_id": "t",
                                                    "label": "L"}]}
    fake = mock.Mock(returncode=0,
                     stdout=json.dumps({"result": {"snapshot": snap}}))
    monkeypatch.setattr(mod.subprocess, "run", lambda *a, **k: fake)
    agents, tabs = mod.herdr_agents("herdr")
    assert agents == [{"pane_id": "p"}]
    assert tabs == [{"tab_id": "t", "label": "L"}]


def test_herdr_agents_failures(monkeypatch):
    monkeypatch.setattr(mod.subprocess, "run",
                        mock.Mock(returncode=1, stdout=""))
    assert mod.herdr_agents("herdr") == (None, [])
    monkeypatch.setattr(mod.subprocess, "run",
                        mock.Mock(side_effect=FileNotFoundError))
    assert mod.herdr_agents("herdr") == (None, [])
    monkeypatch.setattr(mod.subprocess, "run",
                        mock.Mock(returncode=0, stdout="{bad json"))
    assert mod.herdr_agents("herdr") == (None, [])


def test_self_pane_id_prefers_env(monkeypatch):
    monkeypatch.setenv("HERDR_PANE_ID", "w1:pX")
    assert mod.self_pane_id() == "w1:pX"
    monkeypatch.delenv("HERDR_PANE_ID")
    monkeypatch.setattr(mod.os, "ttyname", mock.Mock(side_effect=OSError))
    assert mod.self_pane_id() == f"ext-anon-{os.getppid()}"


# ---------------------------------------------------------------------------
# note actions
# ---------------------------------------------------------------------------

def test_note_register_update_step_trail(state):
    assert mod.cmd_note(ns("register", "refactoring", agent="claude"),
                        HERDR_MISSING) == 0
    card = mod.load_cards()["t1"]
    assert card["header"] and card["agent"] == "claude"
    assert card["log"][0]["k"] == "register"

    assert mod.cmd_note(ns("step", "todo 2/5"), HERDR_MISSING) == 0
    card = mod.load_cards()["t1"]
    assert card["status"] == "todo 2/5"
    assert [e["k"] for e in card["log"]] == ["register", "step"]

    assert mod.cmd_note(ns("update", "now doing X"), HERDR_MISSING) == 0
    card = mod.load_cards()["t1"]
    assert card["status"] == "now doing X"
    assert [e["k"] for e in card["log"]] == ["register", "step"]  # no entry

    assert mod.cmd_note(ns("done", "PR #12"), HERDR_MISSING) == 0
    card = mod.load_cards()["t1"]
    assert card["done"] is True

    assert mod.cmd_note(ns("stop"), HERDR_MISSING) == 0
    assert mod.load_cards() == {}


def test_note_requires_msg():
    assert mod.cmd_note(ns("step", None), HERDR_MISSING) == 2


def test_note_input_flag_and_clear(state):
    mod.cmd_note(ns("register", "goal"), HERDR_MISSING)
    mod.cmd_note(ns("input", "A) keep B) revert?"), HERDR_MISSING)
    card = mod.load_cards()["t1"]
    assert card["input"] is True
    assert card["log"][-1]["k"] == "input"
    assert card["log"][-1]["m"] == "A) keep B) revert?"

    mod.cmd_note(ns("step", "resumed"), HERDR_MISSING)
    card = mod.load_cards()["t1"]
    assert card["input"] is False


def test_note_quota_flag_and_clear(state):
    mod.cmd_note(ns("register", "goal"), HERDR_MISSING)
    mod.cmd_note(ns("quota", "Individual quota reached.", reset="2d 3h"),
                 HERDR_MISSING)
    card = mod.load_cards()["t1"]
    assert card["stopped"]["reset"] == pytest.approx(
        card["updated"] + 2 * 86400 + 3 * 3600, abs=2)
    assert card["log"][-1]["k"] == "quota"

    mod.cmd_note(ns("quota", "again"), HERDR_MISSING)  # no reset -> None
    card = mod.load_cards()["t1"]
    assert card["stopped"]["reset"] is None

    mod.cmd_note(ns("update", "moving on"), HERDR_MISSING)
    card = mod.load_cards()["t1"]
    assert "stopped" not in card


def test_note_stop_missing_column(state, capsys):
    assert mod.cmd_note(ns("stop", pane="ghost"), HERDR_MISSING) == 0
    assert "no column" in capsys.readouterr().out


def test_note_header_and_agent_overrides(state):
    mod.cmd_note(ns("register", "goal", header="Custom", agent="droid"),
                 HERDR_MISSING)
    card = mod.load_cards()["t1"]
    assert card["header"] == "Custom"
    assert card["agent"] == "droid"


# ---------------------------------------------------------------------------
# build_columns
# ---------------------------------------------------------------------------

def test_build_columns_chip_priority_and_badge():
    agents = [{"pane_id": "p1", "tab_id": "t1", "agent": "omp",
               "agent_status": "working", "cwd": "/x"},
              {"pane_id": "p2", "tab_id": "t2", "agent": "agy",
               "agent_status": "idle", "cwd": "/y"}]
    cards = {"p1": {"pane_id": "p1", "done": True, "status": "s"},
             "p2": {"pane_id": "p2", "input": True}}
    tabs = [{"tab_id": "t1", "label": "T1"},
            {"tab_id": "t2", "label": "T2"}]
    cols = mod.build_columns(agents, cards, 1000.0, 600, tabs=tabs)
    by_pane = {c["pane"]: c for c in cols}
    assert by_pane["p1"]["chip"] == "done"          # done beats working
    assert by_pane["p2"]["chip"] == "input"         # card flag on snapshot agent
    assert by_pane["p1"]["tab_name"] == "T1"


def test_build_columns_stopped_chip_and_countdown_text():
    agents = [{"pane_id": "p1", "tab_id": "t1", "agent": "omp",
               "agent_status": "working", "cwd": "/x"}]
    cards = {"p1": {"pane_id": "p1", "status": "Individual quota reached.",
                    "stopped": {"reset": 1000.0 + 86400 + 3600}}}
    cols = mod.build_columns(agents, cards, 1000.0, 600)
    assert cols[0]["chip"] == "stopped"
    assert cols[0]["text"].endswith("Resets in 1d 01:00:00")


def test_build_columns_ext_cards_and_sweep(state):
    cards = {"ext-tty1": {"pane_id": "ext-tty1", "herdr": False,
                          "status": "working on it", "updated": 1000.0},
             "p1": {"pane_id": "p1", "herdr": True, "status": "gone"}}
    cols = mod.build_columns(None, cards, 1000.0, 600)
    assert len(cols) == 1
    assert cols[0]["pane"] == "ext-tty1"
    assert cols[0]["chip"] == "ext"

    # herdr liveness truth: herdr-owned card whose pane vanished is swept
    state_cards = {"p1": {"pane_id": "p1", "herdr": True},
                   "p2": {"pane_id": "p2", "herdr": False}}
    for c in state_cards.values():
        mod.save_card(c)
    mod.sweep(state_cards, [{"pane_id": "p1"}])
    assert "p1" in mod.load_cards() and "p2" in mod.load_cards()
    mod.sweep(state_cards, [{"pane_id": "p2"}])
    assert "p1" not in mod.load_cards()
    mod.sweep(state_cards, None)  # snapshot unreachable: keep everything


def test_build_columns_tab_fallback_covers_every_tab():
    agents = [{"pane_id": "p1", "tab_id": "t1", "agent": "omp",
               "agent_status": "working", "cwd": ""}]
    tabs = [{"tab_id": "t1", "label": "covered"},
            {"tab_id": "t2", "label": "freebuff -- mediadownloader_web",
             "agent_status": "unknown"},
            {"tab_id": "t3", "agent_status": None}]
    cols = mod.build_columns(agents, {}, 1000.0, 600, tabs=tabs)
    by_tab = {c["tab"]: c for c in cols}
    assert len(cols) == 3  # p1 agent column + t2/t3 fallback
    assert by_tab["t2"]["chip"] == "unknown"
    assert by_tab["t2"]["agent"] == ""
    assert by_tab["t2"]["header"] == "freebuff -- mediadownloader_web"
    assert by_tab["t1"]["tab_name"] == "covered"
    assert by_tab["t3"]["header"] == "t3"  # label missing -> tab id


def test_build_columns_sort_order():
    chips = ["idle", "blocked", "input", "working", "stopped", "done"]
    agents = [{"pane_id": f"p{i}", "tab_id": f"t{i}", "agent": "omp",
               "agent_status": chip, "cwd": ""}
              for i, chip in enumerate(chips)]
    cols = mod.build_columns(agents, {}, 1000.0, 600)
    assert [c["chip"] for c in cols] == \
        ["working", "input", "stopped", "blocked", "idle", "done"]


# ---------------------------------------------------------------------------
# rendering
# ---------------------------------------------------------------------------

def test_head_parts_badge_extraction_and_prepend():
    omp = col(agent="omp", header="π > Fix GUI geometry validation")
    assert [s for s, _ in mod.head_parts(omp)] == \
        ["(● working)", " (", "tab", ")", " π", " > Fix GUI geometry validation"]

    oc = col(agent="opencode", header="OpenCode")
    assert [s for s, _ in mod.head_parts(oc)][-1] == " OpenCode"

    agy = col(agent="agy", header="fmann@amd:~/x")
    parts = mod.head_parts(agy)
    assert parts[-2][1] == "badge" and parts[-2][0].endswith("AG")
    assert parts[-1][1] == "desc"

    unknown = col(agent="weird", header="whatever", tab_name="")
    assert [k for _, k in mod.head_parts(unknown)] == [None, "desc"]


def test_compact_line_segments_and_width():
    c = col(text="status text")
    assert mod.compact_line(c, 200) == \
        "(● working) (tab) π Title · status text"
    wide = col(header="x" * 100)
    assert mod.compact_line(wide, 20) == \
        mod.compact_line(wide, 20)[:20]


def test_render_frame_plain_and_active_count():
    cols = [col(chip="working", text="a", age=1),
            col(chip="input", text="question?", age=1),
            col(chip="stopped", text="quota", age=1),
            col(chip="idle", age=1)]
    frame = mod.render_frame(cols, herdr_ok=True, color=False)
    assert "\x1b[" not in frame
    head = frame.splitlines()[0]
    assert "4 agents" in head and "2 active" in head


def test_render_frame_colors():
    red = mod.render_frame([col(chip="stopped")], True, color=True)
    assert "\x1b[31m(■ stopped)" in red
    yellow = mod.render_frame([col(chip="input")], True, color=True)
    assert "\x1b[33m(❯ needs input)" in yellow


def test_render_frame_compact_rows():
    cols = [col(pane=f"p{i}", chip="idle") for i in range(7)]
    frame = mod.render_frame(cols, herdr_ok=True, color=False, compact=True,
                             width=118)
    lines = [l for l in frame.splitlines() if l.strip()]
    assert len(lines) == 5  # header + 4 rows for 7 agents (odd -> last single)
    assert lines[1].count("│") == 1 and lines[-1].count("│") == 0


def test_render_frame_herdr_unreachable_banner():
    frame = mod.render_frame([], herdr_ok=False, color=False)
    assert "herdr snapshot unreachable" in frame


# ---------------------------------------------------------------------------
# help coloring
# ---------------------------------------------------------------------------

def test_colorize_help_respects_env(monkeypatch):
    plain = "usage: agent-board [-h]\n\noptions:\n  -h, --help  x\n"
    monkeypatch.delenv("FORCE_COLOR", raising=False)
    monkeypatch.setenv("NO_COLOR", "1")
    assert mod.colorize_help(plain) == plain
    monkeypatch.delenv("NO_COLOR")
    monkeypatch.setenv("FORCE_COLOR", "1")
    colored = mod.colorize_help(plain)
    assert "\x1b[36m-h\x1b[0m" in colored
    assert "\x1b[1;33m" in colored


# ---------------------------------------------------------------------------
# process resolution
# ---------------------------------------------------------------------------

def test_resolve_proc_aliases_and_cwd():
    procs = ({}, {("omp", "/proj"): [(10, "omp", 100), (11, "omp", 900)],
                  ("claude", "/proj"): [(12, "claude", 50)]})
    assert mod.resolve_proc("omp", "/proj", procs) == (11, 900)
    assert mod.resolve_proc("claude", "/nowhere", procs) == (None, None)


def test_resolve_ext_proc_by_tty():
    procs = ({"pts-3": [(21, "opencode", 700)]}, {})
    assert mod.resolve_ext_proc("ext-pts-3", procs) == (21, 700)
    assert mod.resolve_ext_proc("ext-pts-9", ({}, {})) == (None, None)


def test_scan_procs_shape():
    by_tty, by_kind = mod.scan_procs()
    assert isinstance(by_tty, dict) and isinstance(by_kind, dict)


# ---------------------------------------------------------------------------
# CLI end-to-end (subprocess, isolated state)
# ---------------------------------------------------------------------------

@pytest.fixture
def run(tmp_path):
    env = dict(os.environ, XDG_STATE_HOME=str(tmp_path / "xdgstate"))
    env.pop("HERDR_PANE_ID", None)

    def run(*args, check=False):
        proc = subprocess.run([sys.executable, str(MODULE_PATH), *args],
                              capture_output=True, text=True, env=env,
                              timeout=30)
        if check:
            assert proc.returncode == 0, proc.stderr
        return proc
    return run


def test_cli_note_lifecycle_and_frames(run):
    run("--herdr-bin", HERDR_MISSING, "note", "register", "--pane", "t1",
        "--agent", "agy", "-m", "refactoring", check=True)
    run("--herdr-bin", HERDR_MISSING, "note", "input", "--pane", "t1",
        "-m", "A) keep B) revert?", check=True)
    out = run("--herdr-bin", HERDR_MISSING, "--once", check=True).stdout
    assert "(❯ needs input)" in out
    assert "A) keep B) revert?" in out

    run("--herdr-bin", HERDR_MISSING, "note", "quota", "--pane", "t1",
        "-m", "Individual quota reached.", "--reset", "2d 3h", check=True)
    out = run("--herdr-bin", HERDR_MISSING, "--once", check=True).stdout
    assert "(■ stopped)" in out
    assert "Resets in 2d 0" in out and "Individual quota reached." in out

    run("--herdr-bin", HERDR_MISSING, "note", "step", "--pane", "t1",
        "-m", "resumed", check=True)
    out = run("--herdr-bin", HERDR_MISSING, "--once", check=True).stdout
    assert "(■ stopped)" not in out and "(❯ needs input)" not in out

    run("--herdr-bin", HERDR_MISSING, "note", "stop", "--pane", "t1",
        check=True)
    assert "refactoring" not in run("--herdr-bin", HERDR_MISSING,
                                    "--once", check=True).stdout


def test_cli_bad_action_rejected(run):
    proc = run("note", "explode", "-m", "x")
    assert proc.returncode == 2


def test_wrapper_help():
    proc = subprocess.run(["bash", str(REPO / "agent_board"), "help"],
                          capture_output=True, text=True, timeout=10)
    assert proc.returncode == 0
    assert "view-compact" in proc.stdout
    proc = subprocess.run(["bash", str(REPO / "agent_board"), "bogus"],
                          capture_output=True, text=True, timeout=10)
    assert proc.returncode == 2 and "usage:" in proc.stderr

def test_version_flag_and_header(run):
    proc = run("--version")
    assert proc.returncode == 0
    assert mod.__version__ in proc.stdout and "agent_board" in proc.stdout
    plain = mod.render_frame([], herdr_ok=True, color=False)
    assert plain.splitlines()[0].endswith(f"  ({mod.__version__})")
    colored = mod.render_frame([], herdr_ok=True, color=True)
    assert f"\x1b[37m  ({mod.__version__})\x1b[0m" in colored


def test_wrapper_version():
    proc = subprocess.run(["bash", str(REPO / "agent_board"), "--version"],
                          capture_output=True, text=True, timeout=10)
    assert proc.returncode == 0
    assert mod.__version__ in proc.stdout and "agent_board" in proc.stdout


# ---------------------------------------------------------------------------
# click-to-focus
# ---------------------------------------------------------------------------

def test_column_at_click_compact_mapping():
    row_map = {2: (0, 3), 3: (1, None)}
    assert mod.column_at_click(row_map, 2, 10, True, 48) == 0     # left
    assert mod.column_at_click(row_map, 2, 48, True, 48) == 0     # │ column
    assert mod.column_at_click(row_map, 2, 50, True, 48) == 3     # right
    assert mod.column_at_click(row_map, 2, 60, True, 48) == 3
    assert mod.column_at_click(row_map, 3, 60, True, 48) == 1     # no right
    assert mod.column_at_click(row_map, 9, 10, True, 48) is None  # off-board


def test_column_at_click_fullscreen_mapping():
    assert mod.column_at_click({4: 1, 5: 1, 6: 1}, 5, 0, False, 48) == 1
    assert mod.column_at_click({}, 5, 0, False, 48) is None


def test_tui_click_focuses_herdr_tab(tmp_path):
    log = tmp_path / "herdr-log"
    fake = tmp_path / "fake-herdr"
    snap = json.dumps({"result": {"snapshot": {
        "agents": [{"pane_id": "p1", "tab_id": "w1:tX", "agent": "omp",
                    "agent_status": "working", "cwd": "/x"}],
        "tabs": [{"tab_id": "w1:tX", "label": "Test"}],
        "panes": []}}})
    fake.write_text(
        "#!/bin/bash\necho \"$@\" >> " + str(log) + "\n"
        "if [ \"$1\" = api ] && [ \"$2\" = snapshot ]; then\n"
        "    echo '" + snap.replace("'", "") + "'\nfi\n")
    fake.chmod(0o755)

    import pty, select as sel
    pid, fd = pty.fork()
    if pid == 0:
        env = dict(os.environ, XDG_STATE_HOME=str(tmp_path / "xdgstate"),
                   TERM="xterm-256color", LINES="30", COLUMNS="100")
        env.pop("HERDR_PANE_ID", None)
        os.execve(str(MODULE_PATH),
                  ["agent_board.py", "--compact", "--poll-period", "1",
                   "--herdr-bin", str(fake)], env)
    time.sleep(2.5)
    screen = b""
    deadline = time.time() + 2
    while time.time() < deadline:
        r, _, _ = sel.select([fd], [], [], 0.3)
        if r:
            try:
                screen += os.read(fd, 65536)
            except OSError:
                break
    clean = re.sub(r"\x1b\[[0-9;?]*[a-zA-Z]", "",
                   screen.decode("utf-8", "replace"))
    clean = clean.replace("\x1b(B", "").replace("\x1b)B", "")
    assert "1 (" in clean  # columns are numbered

    os.write(fd, b"\x1b[<0;11;3M\x1b[<0;11;3m")  # click row 3 (y=2), col 11
    time.sleep(1.5)
    os.write(fd, b"1")     # type number 1
    time.sleep(0.4)
    os.write(fd, b"\r")    # Enter jumps
    time.sleep(1.5)
    os.write(fd, b"q")
    time.sleep(0.8)
    os.waitpid(pid, 0)
    content = log.read_text() if log.exists() else ""
    assert content.count("tab focus w1:tX") >= 2  # mouse click + number jump
