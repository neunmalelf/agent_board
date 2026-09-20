"""Tests for the agent-board CLI (src/agent_board package).

Run with:  python3 -m pytest tests/ -q
All filesystem state lives in temp dirs; herdr is never invoked (patched
or pointed at a nonexistent binary), so the suite is fast and isolated.
"""
import argparse
import json
import os
import re
import subprocess
import sys
import time
import unittest.mock as mock
from pathlib import Path

import pytest

from agent_board import board as mod

REPO = Path(__file__).resolve().parent.parent
MODULE_PATH = REPO / "agent_board.py"  # launcher shim, exercised by subprocess tests
HERDR_MISSING = "/nonexistent-herdr"


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def ns(action: str, msg: str | None = None, pane: str = "t1",
       tab: str | None = None, header: str | None = None,
       agent: str | None = None, reset: str | None = None) -> argparse.Namespace:
    """Build an argparse.Namespace shaped like the agent-board CLI arguments.

    usage: ns <ACTION> [MSG] [PANE] [TAB] [HEADER] [AGENT] [RESET]
    returns: An argparse.Namespace populated with the given action fields.

    Args:
        action (str): Note subcommand, e.g. "register", "step", "quota".
        msg (str, optional): Message payload for the action. Defaults to None.
        pane (str, optional): Pane id the note targets. Defaults to "t1".
        tab (str, optional): Tab id override. Defaults to None.
        header (str, optional): Column header override. Defaults to None.
        agent (str, optional): Agent name override. Defaults to None.
        reset (str, optional): Relative reset duration for quota notes. Defaults to None.

    Example:
        ns("step", "todo 2/5")
    """
    return argparse.Namespace(action=action, msg=msg, pane=pane, tab=tab,
                              header=header, agent=agent, reset=reset)


def col(chip: str = "working", **over) -> dict:
    """Build a column dict from defaults overridden per test.

    usage: col [CHIP] [OVER...]
    returns: A column dict with pane, agent, tab, chip, text, and friends set.

    Args:
        chip (str, optional): Status chip for the column. Defaults to "working".
        over (object): Extra column fields merged over the defaults.

    Example:
        col(chip="idle", text="working on it")
    """
    base = dict(pane="p1", agent="omp", tab="w1:t1", tab_name="tab",
                header="Title", chip=chip, focused=False, text="",
                log=[], age=None, pid=None, rss=None)
    base.update(over)
    return base


@pytest.fixture
def state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect agent-board state into a temp dir; yields the state dir path.

    usage: state <TMP_PATH> <MONKEYPATCH>
    returns: Path to the isolated state directory.

    Args:
        tmp_path (Path): pytest-provided temporary directory.
        monkeypatch (pytest.MonkeyPatch): pytest monkeypatch fixture.

    Example:
        def test_card_roundtrip(state):
            mod.save_card({"pane_id": "p1"})
    """
    monkeypatch.setattr(mod, "STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setattr(mod, "FRAME_PATH", str(tmp_path / "state" / "board.txt"))
    return tmp_path / "state"


# ---------------------------------------------------------------------------
# text helpers
# ---------------------------------------------------------------------------

def test_clean_title_strips_spinner_and_collapses_space():
    """clean_title strips the spinner glyph and collapses runs of spaces.

    usage: test_clean_title_strips_spinner_and_collapses_space
    returns: None.

    Example:
        test_clean_title_strips_spinner_and_collapses_space()
    """
    assert mod.clean_title("π \u280b Use parentheses in view modes") == \
        "π Use parentheses in view modes"
    assert mod.clean_title("a   b") == "a b"
    assert mod.clean_title("Freebuff: continue") == "continue"
    assert mod.clean_title("freebuff:12s") == "12s"
    assert mod.clean_title(None) == ""
    assert mod.clean_title("") == ""


def test_age_str_format():
    """age_str renders seconds as a compact human-readable age.

    usage: test_age_str_format
    returns: None.

    Example:
        test_age_str_format()
    """
    assert mod.age_str(None) == ""
    assert mod.age_str(5) == "5s"
    assert mod.age_str(120) == "2m"
    assert mod.age_str(3 * 3600 + 5 * 60) == "3h05m"


def test_dur_str_countdown():
    """dur_str renders seconds as an HH:MM:SS countdown with a day prefix.

    usage: test_dur_str_countdown
    returns: None.

    Example:
        test_dur_str_countdown()
    """
    assert mod.dur_str(0) == "00:00:00"
    assert mod.dur_str(-5) == "00:00:00"
    assert mod.dur_str(3 * 3600 + 5 * 60 + 4) == "03:05:04"
    assert mod.dur_str(2 * 86400 + 3 * 3600) == "2d 03:00:00"


def test_rss_str():
    """rss_str renders a KiB memory figure as an M- or G-suffixed string.

    usage: test_rss_str
    returns: None.

    Example:
        test_rss_str()
    """
    assert mod.rss_str(None) == ""
    assert mod.rss_str(512) == "0M"
    assert mod.rss_str(569 * 1024) == "569M"
    assert mod.rss_str(2 * 1024 * 1024) == "2.0G"


def test_status_text_appends_live_countdown():
    """status_text appends a live reset countdown only while the card is stopped.

    usage: test_status_text_appends_live_countdown
    returns: None.

    Example:
        test_status_text_appends_live_countdown()
    """
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
def test_parse_reset_durations(text: str, expected: int):
    """parse_reset converts relative reset durations into an absolute epoch.

    usage: test_parse_reset_durations <TEXT> <EXPECTED>
    returns: None.

    Args:
        text (str): Relative duration such as "90m" or "2d 3h".
        expected (int): Expected seconds offset from the reference now.

    Example:
        test_parse_reset_durations("90m", 5400)
    """
    now = 1000.0
    assert mod.parse_reset(text, now) == pytest.approx(now + expected)


def test_parse_reset_iso_absolute():
    """parse_reset converts an absolute ISO-8601 UTC timestamp to epoch time.

    usage: test_parse_reset_iso_absolute
    returns: None.

    Example:
        test_parse_reset_iso_absolute()
    """
    assert mod.parse_reset("2026-09-13T08:00:00Z", 1000.0) == \
        pytest.approx(1789286400.0)


def test_parse_reset_garbage_and_empty():
    """parse_reset returns None for empty, None, or unparseable input.

    usage: test_parse_reset_garbage_and_empty
    returns: None.

    Example:
        test_parse_reset_garbage_and_empty()
    """
    assert mod.parse_reset("", 0) is None
    assert mod.parse_reset(None, 0) is None
    assert mod.parse_reset("not a time", 0) is None


# ---------------------------------------------------------------------------
# card storage
# ---------------------------------------------------------------------------

def test_card_roundtrip(state: Path):
    """Card save/read/load/drop round-trips through the isolated state dir.

    usage: test_card_roundtrip <STATE>
    returns: None.

    Args:
        state (Path): Isolated state directory fixture.

    Example:
        test_card_roundtrip(Path("/tmp/pytest-state"))
    """
    card = {"pane_id": "p1", "status": "hello", "log": []}
    mod.save_card(card)
    assert mod.read_card(mod.card_path("p1"))["status"] == "hello"
    assert mod.load_cards()["p1"]["status"] == "hello"
    mod.drop_card("p1")
    assert mod.load_cards() == {}


def test_read_card_corrupt_json(state: Path):
    """A corrupt card file yields None from read_card and {} from load_cards.

    usage: test_read_card_corrupt_json <STATE>
    returns: None.

    Args:
        state (Path): Isolated state directory fixture.

    Example:
        test_read_card_corrupt_json(Path("/tmp/pytest-state"))
    """
    path = Path(mod.card_path("bad"))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{not json")
    assert mod.read_card(path) is None
    assert mod.load_cards() == {}


def test_herdr_match():
    """herdr_match resolves an agent by pane id or tab id, tolerating blanks.

    usage: test_herdr_match
    returns: None.

    Example:
        test_herdr_match()
    """
    agents = [{"pane_id": "w1:p41", "tab_id": "w1:tV"},
              {"pane_id": "w1:p3R", "tab_id": "w1:t15"}]
    assert mod.herdr_match(agents, "w1:p3R", "")["tab_id"] == "w1:t15"
    assert mod.herdr_match(agents, "", "w1:tV")["pane_id"] == "w1:p41"
    assert mod.herdr_match(agents, "", "") is None
    assert mod.herdr_match(None, "x", "y") is None


def test_herdr_agents_parses_snapshot(monkeypatch: pytest.MonkeyPatch):
    """herdr_agents unwraps the herdr snapshot JSON into agents and tabs.

    usage: test_herdr_agents_parses_snapshot <MONKEYPATCH>
    returns: None.

    Args:
        monkeypatch (pytest.MonkeyPatch): Patches mod.subprocess.run.

    Example:
        test_herdr_agents_parses_snapshot(pytest.MonkeyPatch())
    """
    snap = {"agents": [{"pane_id": "p"}], "tabs": [{"tab_id": "t",
                                                    "label": "L"}]}
    fake = mock.Mock(returncode=0,
                     stdout=json.dumps({"result": {"snapshot": snap}}))
    monkeypatch.setattr(mod.subprocess, "run", lambda *a, **k: fake)
    agents, tabs = mod.herdr_agents("herdr")
    assert agents == [{"pane_id": "p"}]
    assert tabs == [{"tab_id": "t", "label": "L"}]


def test_herdr_agents_failures(monkeypatch: pytest.MonkeyPatch):
    """herdr_agents returns (None, []) on nonzero exit, missing binary, or bad JSON.

    usage: test_herdr_agents_failures <MONKEYPATCH>
    returns: None.

    Args:
        monkeypatch (pytest.MonkeyPatch): Patches mod.subprocess.run.

    Example:
        test_herdr_agents_failures(pytest.MonkeyPatch())
    """
    monkeypatch.setattr(mod.subprocess, "run",
                        mock.Mock(returncode=1, stdout=""))
    assert mod.herdr_agents("herdr") == (None, [])
    monkeypatch.setattr(mod.subprocess, "run",
                        mock.Mock(side_effect=FileNotFoundError))
    assert mod.herdr_agents("herdr") == (None, [])
    monkeypatch.setattr(mod.subprocess, "run",
                        mock.Mock(returncode=0, stdout="{bad json"))
    assert mod.herdr_agents("herdr") == (None, [])


def test_herdr_snapshot_parses_panes(monkeypatch: pytest.MonkeyPatch):
    """herdr_snapshot unwraps agents, tabs, and panes from the snapshot JSON.

    Args:
        monkeypatch: pytest fixture patching mod.subprocess.run.
    """
    snap = {"agents": [{"pane_id": "p1"}], "tabs": [{"tab_id": "t1"}],
            "panes": [{"pane_id": "p1", "tab_id": "t1"},
                      {"pane_id": "p2", "tab_id": "t1"}]}
    fake = mock.Mock(returncode=0,
                     stdout=json.dumps({"result": {"snapshot": snap}}))
    monkeypatch.setattr(mod.subprocess, "run", lambda *a, **k: fake)
    agents, tabs, panes = mod.herdr_snapshot("herdr")
    assert agents == [{"pane_id": "p1"}]
    assert tabs == [{"tab_id": "t1"}]
    assert [p["pane_id"] for p in panes] == ["p1", "p2"]
    assert mod.herdr_agents("herdr") == ([{"pane_id": "p1"}], [{"tab_id": "t1"}])


def test_herdr_snapshot_unreachable_returns_no_panes(
        monkeypatch: pytest.MonkeyPatch):
    """herdr_snapshot reports (None, [], []) when herdr cannot be queried.

    Args:
        monkeypatch: pytest fixture patching mod.subprocess.run.
    """
    monkeypatch.setattr(mod.subprocess, "run",
                        mock.Mock(side_effect=FileNotFoundError))
    assert mod.herdr_snapshot("herdr") == (None, [], [])


def test_herdr_match_pane_first_and_unambiguous_tab():
    """herdr_match prefers the exact pane and refuses ambiguous tab lookups."""
    agents = [{"pane_id": "w1:p1", "tab_id": "w1:t1"},
              {"pane_id": "w1:p2", "tab_id": "w1:t1"},
              {"pane_id": "w1:p3", "tab_id": "w1:t2"}]
    assert mod.herdr_match(agents, "w1:p3", "w1:t1")["pane_id"] == "w1:p3"
    assert mod.herdr_match(agents, "w1:p9", "w1:t1") is None   # stale pane id
    assert mod.herdr_match(agents, "", "w1:t1") is None        # two in the tab
    assert mod.herdr_match(agents, "", "w1:t2")["pane_id"] == "w1:p3"
    assert mod.herdr_match(None, "x", "y") is None


def test_pane_agent_picks_largest_known_process(monkeypatch: pytest.MonkeyPatch):
    """pane_agent reports the largest known agent process running in a pane.

    Args:
        monkeypatch: pytest fixture patching the pane probe and /proc reader.
    """
    procs = [{"name": "bash", "pid": 1}, {"name": "cline", "pid": 2},
             {"name": "node-MainThread", "pid": 3},
             {"name": "freebuff", "pid": 4}]
    monkeypatch.setattr(mod, "herdr_pane_processes", lambda b, p: procs)
    monkeypatch.setattr(mod, "pid_rss", lambda pid: {2: 100, 4: 4096}.get(pid))
    assert mod.pane_agent("herdr", "w1:p1") == ("freebuff", 4, 4096)
    monkeypatch.setattr(mod, "pid_rss", lambda pid: None)
    assert mod.pane_agent("herdr", "w1:p1") == ("cline", 2, None)  # first wins
    monkeypatch.setattr(mod, "herdr_pane_processes",
                        lambda b, p: [{"name": "nvtop", "pid": 9}])
    assert mod.pane_agent("herdr", "w1:p1") == ("", None, None)


def test_pid_rss_reads_proc_and_tolerates_garbage():
    """pid_rss reads this process's RSS and returns None for junk ids."""
    assert mod.pid_rss(os.getpid()) > 0
    assert mod.pid_rss(None) is None and mod.pid_rss(0) is None


def test_detect_pane_agents_skips_classified_panes(monkeypatch: pytest.MonkeyPatch):
    """detect_pane_agents probes only the panes herdr did not classify.

    Args:
        monkeypatch: pytest fixture patching mod.pane_agents.
    """
    calls: list = []

    def fake_pane_agents(herdr_bin: str, pane: str) -> list:
        """Record the probed pane and report one cline process.

        Args:
            herdr_bin: Unused herdr binary name.
            pane: Pane id being probed.

        Returns:
            A fixed single-entry probe result.
        """
        calls.append(pane)
        return [{"agent": "cline", "pid": 7, "rss": 128}]

    monkeypatch.setattr(mod, "pane_agents", fake_pane_agents)
    panes = [{"pane_id": "p1"}, {"pane_id": "p2"}, {"pane_id": ""}]
    found = mod.detect_pane_agents("herdr", panes, [{"pane_id": "p1"}])
    assert calls == ["p2"]
    assert found == {"p2": [{"agent": "cline", "pid": 7, "rss": 128}]}


def test_probe_entries_normalizes_probe_results():
    """probe_entries accepts an entry list, a single entry, and junk."""
    entry = {"agent": "omp", "pid": 5, "rss": 4096}
    assert mod.probe_entries([entry]) == [entry]
    assert mod.probe_entries(entry) == [entry]      # single entry, wrapped
    assert mod.probe_entries(None) == [] and mod.probe_entries("x") == []
    assert mod.probe_entries([entry, None]) == [entry]



@pytest.mark.parametrize("proc,expected", [
    ({"name": "omp", "argv": ["/home/fmann/.local/bin/omp", "--model", "x"]}, "omp"),
    ({"name": "node-MainThread",
      "argv": ["node", "/home/fmann/.nvm/versions/node/v26.8.1/bin/cline"]},
     "cline"),
    ({"name": "node-MainThread", "argv": ["node", "/usr/lib/cline.js"]}, "cline"),
    ({"name": "agy", "argv": ["antigravity"]}, "agy"),
    ({"name": "mc", "argv": ["/home/fmann/.local/opt/mc-ts/bin/mc", "-P",
                             "/tmp/mc.pwd.X"]}, ""),
    ({"name": "grep", "argv": ["grep", "cline.md"]}, ""),
])
def test_proc_kind_matches_name_and_argv(proc: dict, expected: str):
    """proc_kind resolves wrapper/interpreter processes through their argv."""
    assert mod.proc_kind(proc) == expected


def test_proc_tree_walks_descendants_of_the_foreground_processes(
        monkeypatch: pytest.MonkeyPatch):
    """proc_tree reads the roots and their descendants, bounded by limit.

    Args:
        monkeypatch: pytest fixture patching the /proc readers.
    """
    children = {1: [2], 2: [3], 3: []}
    procs = {1: {"name": "mc", "pid": 1, "argv": ["/opt/mc"]},
             2: {"name": "bash", "pid": 2, "argv": ["/bin/bash"]},
             3: {"name": "node-MainThread", "pid": 3,
                 "argv": ["node", "/opt/bin/cline"]}}
    monkeypatch.setattr(mod, "child_pids", lambda pid: children.get(pid, []))
    monkeypatch.setattr(mod, "read_proc", lambda pid: procs.get(pid))
    assert [p["pid"] for p in mod.proc_tree([1])] == [1, 2, 3]
    assert [p["pid"] for p in mod.proc_tree([3])] == [3]
    assert [p["pid"] for p in mod.proc_tree([1], limit=2)] == [1, 2]
    assert mod.proc_tree([]) == [] and mod.proc_tree([99]) == []
    assert mod.proc_tree(["x", None]) == []       # non-pids are ignored


def test_proc_tree_reads_a_real_proc_entry():
    """The /proc readers return this very process (name, pid, argv)."""
    tree = mod.proc_tree([os.getpid()])
    assert tree and tree[0]["pid"] == os.getpid()
    assert tree[0]["name"] and tree[0]["argv"]
    assert mod.read_proc(0) is None


def test_pane_agents_finds_agent_nested_behind_a_wrapper(
        monkeypatch: pytest.MonkeyPatch):
    """A cline agent below a wrapper (mc) still yields that pane's column.

    Args:
        monkeypatch: pytest fixture patching the pane probe and /proc readers.
    """
    procs = [{"name": "mc", "pid": 10,
              "argv": ["/home/fmann/.local/opt/mc-ts/bin/mc", "-P",
                       "/tmp/mc.pwd.X"]}]
    tree = procs + [{"name": "bash", "pid": 11, "argv": ["/bin/bash"]},
                    {"name": "node-MainThread", "pid": 12,
                     "argv": ["node", "/home/fmann/.nvm/bin/cline"]}]
    monkeypatch.setattr(mod, "herdr_pane_processes", lambda b, p: procs)
    monkeypatch.setattr(mod, "proc_tree", lambda pids: tree)
    monkeypatch.setattr(mod, "pid_rss",
                        lambda pid: {10: 20480, 12: 1966080}.get(pid))
    assert mod.pane_agents("herdr", "w1:p68") == [
        {"agent": "cline", "pid": 12, "rss": 1966080}]
    assert mod.pane_agent("herdr", "w1:p68") == ("cline", 12, 1966080)
    monkeypatch.setattr(mod, "herdr_pane_processes", lambda b, p: [])
    assert mod.pane_agents("herdr", "w1:p68") == []
    assert mod.pane_agent("herdr", "w1:p68") == ("", None, None)


def test_pane_agents_keeps_one_entry_per_kind(monkeypatch: pytest.MonkeyPatch):
    """A pane running two agents of one kind reports a single largest entry.

    Args:
        monkeypatch: pytest fixture patching the pane probe and /proc readers.
    """
    procs = [{"name": "node-MainThread", "pid": 1, "argv": ["node", "/b/cline"]},
             {"name": "cline", "pid": 2, "argv": ["/b/cline"]},
             {"name": "omp", "pid": 3, "argv": ["/b/omp"]}]
    monkeypatch.setattr(mod, "herdr_pane_processes", lambda b, p: procs)
    monkeypatch.setattr(mod, "proc_tree", lambda pids: [])
    monkeypatch.setattr(mod, "pid_rss", lambda pid: {1: 10, 2: 30, 3: 20}[pid])
    assert mod.pane_agents("herdr", "w1:p1") == [
        {"agent": "cline", "pid": 2, "rss": 30},
        {"agent": "omp", "pid": 3, "rss": 20}]


def test_self_pane_id_prefers_env(monkeypatch: pytest.MonkeyPatch):
    """self_pane_id prefers HERDR_PANE_ID and falls back to an external tty id.

    usage: test_self_pane_id_prefers_env <MONKEYPATCH>
    returns: None.

    Args:
        monkeypatch (pytest.MonkeyPatch): Sets HERDR_PANE_ID and patches ttyname.

    Example:
        test_self_pane_id_prefers_env(pytest.MonkeyPatch())
    """
    monkeypatch.setenv("HERDR_PANE_ID", "w1:pX")
    assert mod.self_pane_id() == "w1:pX"
    monkeypatch.delenv("HERDR_PANE_ID")
    monkeypatch.setattr(mod.os, "ttyname", mock.Mock(side_effect=OSError))
    assert mod.self_pane_id() == f"ext-anon-{os.getppid()}"


# ---------------------------------------------------------------------------
# note actions
# ---------------------------------------------------------------------------

def test_note_register_update_step_trail(state: Path):
    """cmd_note register/step/update/done/stop drive the full card lifecycle.

    usage: test_note_register_update_step_trail <STATE>
    returns: None.

    Args:
        state (Path): Isolated state directory fixture.

    Example:
        test_note_register_update_step_trail(Path("/tmp/pytest-state"))
    """
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
    """cmd_note rejects a note action without a message with exit code 2.

    usage: test_note_requires_msg
    returns: None.

    Example:
        test_note_requires_msg()
    """
    assert mod.cmd_note(ns("step", None), HERDR_MISSING) == 2


def test_note_input_flag_and_clear(state: Path):
    """cmd_note input sets the input flag and a later step clears it.

    usage: test_note_input_flag_and_clear <STATE>
    returns: None.

    Args:
        state (Path): Isolated state directory fixture.

    Example:
        test_note_input_flag_and_clear(Path("/tmp/pytest-state"))
    """
    mod.cmd_note(ns("register", "goal"), HERDR_MISSING)
    mod.cmd_note(ns("input", "A) keep B) revert?"), HERDR_MISSING)
    card = mod.load_cards()["t1"]
    assert card["input"] is True
    assert card["log"][-1]["k"] == "input"
    assert card["log"][-1]["m"] == "A) keep B) revert?"

    mod.cmd_note(ns("step", "resumed"), HERDR_MISSING)
    card = mod.load_cards()["t1"]
    assert card["input"] is False


def test_note_quota_flag_and_clear(state: Path):
    """cmd_note quota records a stop reset time and a later update clears it.

    usage: test_note_quota_flag_and_clear <STATE>
    returns: None.

    Args:
        state (Path): Isolated state directory fixture.

    Example:
        test_note_quota_flag_and_clear(Path("/tmp/pytest-state"))
    """
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


def test_note_stop_missing_column(state: Path, capsys: pytest.CaptureFixture):
    """cmd_note stop for an unknown pane is a no-op printing a no-column note.

    usage: test_note_stop_missing_column <STATE> <CAPSYS>
    returns: None.

    Args:
        state (Path): Isolated state directory fixture.
        capsys (pytest.CaptureFixture): Captures stdout for the message check.

    Example:
        test_note_stop_missing_column(Path("/tmp/pytest-state"), pytest.CaptureFixture())
    """
    assert mod.cmd_note(ns("stop", pane="ghost"), HERDR_MISSING) == 0
    assert "no column" in capsys.readouterr().out


def test_note_header_and_agent_overrides(state: Path):
    """cmd_note register honors header and agent overrides.

    usage: test_note_header_and_agent_overrides <STATE>
    returns: None.

    Args:
        state (Path): Isolated state directory fixture.

    Example:
        test_note_header_and_agent_overrides(Path("/tmp/pytest-state"))
    """
    mod.cmd_note(ns("register", "goal", header="Custom", agent="droid"),
                 HERDR_MISSING)
    card = mod.load_cards()["t1"]
    assert card["header"] == "Custom"
    assert card["agent"] == "droid"


# ---------------------------------------------------------------------------
# build_columns
# ---------------------------------------------------------------------------

def test_build_columns_chip_priority_and_badge():
    """build_columns prefers the done chip over snapshot status and maps labels.

    usage: test_build_columns_chip_priority_and_badge
    returns: None.

    Example:
        test_build_columns_chip_priority_and_badge()
    """
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
    """build_columns marks stopped cards and appends a reset countdown to text.

    usage: test_build_columns_stopped_chip_and_countdown_text
    returns: None.

    Example:
        test_build_columns_stopped_chip_and_countdown_text()
    """
    agents = [{"pane_id": "p1", "tab_id": "t1", "agent": "omp",
               "agent_status": "working", "cwd": "/x"}]
    cards = {"p1": {"pane_id": "p1", "status": "Individual quota reached.",
                    "stopped": {"reset": 1000.0 + 86400 + 3600}}}
    cols = mod.build_columns(agents, cards, 1000.0, 600)
    assert cols[0]["chip"] == "stopped"
    assert cols[0]["text"].endswith("Resets in 1d 01:00:00")


def test_build_columns_ext_cards_and_sweep(state: Path):
    """build_columns renders ext cards as columns and sweep prunes dead herdr panes.

    usage: test_build_columns_ext_cards_and_sweep <STATE>
    returns: None.

    Args:
        state (Path): Isolated state directory fixture.

    Example:
        test_build_columns_ext_cards_and_sweep(Path("/tmp/pytest-state"))
    """
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
    """build_columns adds fallback columns for tabs without an agent.

    usage: test_build_columns_tab_fallback_covers_every_tab
    returns: None.

    Example:
        test_build_columns_tab_fallback_covers_every_tab()
    """
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
    """build_columns orders columns by chip priority, working first and done last.

    usage: test_build_columns_sort_order
    returns: None.

    Example:
        test_build_columns_sort_order()
    """
    chips = ["idle", "blocked", "input", "working", "stopped", "done"]
    agents = [{"pane_id": f"p{i}", "tab_id": f"t{i}", "agent": "omp",
               "agent_status": chip, "cwd": ""}
              for i, chip in enumerate(chips)]
    cols = mod.build_columns(agents, {}, 1000.0, 600)
    assert [c["chip"] for c in cols] == \
        ["working", "input", "stopped", "blocked", "idle", "done"]


def test_build_columns_shows_second_agent_in_same_tab():
    """build_columns renders every agent pane of a tab, not only herdr's pick."""
    agents = [{"pane_id": "p1", "tab_id": "t1", "agent": "omp",
               "agent_status": "working", "cwd": "/x"}]
    panes = [{"pane_id": "p1", "tab_id": "t1", "cwd": "/x"},
             {"pane_id": "p2", "tab_id": "t1", "cwd": "/y",
              "terminal_title_stripped": "> fix the build"}]
    cards = {"p2": {"pane_id": "p2", "tab_id": "t1", "header": "earth",
                    "agent": "cline", "status": "editing board.py",
                    "updated": 990.0}}
    tabs = [{"tab_id": "t1", "label": "earth"}]
    cols = mod.build_columns(agents, cards, 1000.0, 600, tabs=tabs, panes=panes)
    by_pane = {c["pane"]: c for c in cols}
    assert set(by_pane) == {"p1", "p2"}
    assert by_pane["p2"]["agent"] == "cline"
    assert by_pane["p2"]["header"] == "earth"
    assert by_pane["p2"]["tab_name"] == "earth"
    assert by_pane["p2"]["text"] == "editing board.py"
    assert by_pane["p2"]["chip"] == "unknown"  # herdr has no state for it


def test_build_columns_probes_pane_processes_and_keeps_tab_fallback():
    """A probed pane agent yields a column; agent-less tabs still fall back."""
    panes = [{"pane_id": "p1", "tab_id": "t1", "agent_status": "unknown",
              "cwd": "/x", "terminal_title_stripped": "media ui"},
             {"pane_id": "p2", "tab_id": "t2", "agent_status": "unknown",
              "cwd": "/z", "terminal_title_stripped": "plain shell"}]
    tabs = [{"tab_id": "t1", "label": "media"}, {"tab_id": "t2", "label": "quizza"}]
    cols = mod.build_columns([], {}, 1000.0, 600, tabs=tabs, panes=panes,
                             pane_agents={"p1": {"agent": "freebuff",
                                                 "pid": 42, "rss": 2048}})
    by_pane = {c["pane"]: c for c in cols}
    assert by_pane["p1"]["agent"] == "freebuff"
    assert by_pane["p1"]["pid"] == 42 and by_pane["p1"]["rss"] == 2048
    assert by_pane["p1"]["header"] == "media ui"
    assert by_pane["t2"]["header"] == "quizza"  # no agent: fallback column


def test_build_columns_lists_omp_and_nested_cline_of_one_tab():
    """The live 'earth' shape: a classified omp pane plus a cline behind mc."""
    agents = [{"pane_id": "p8", "tab_id": "t1", "agent": "omp",
               "agent_status": "working", "cwd": "/earth"}]
    panes = [{"pane_id": "p8", "tab_id": "t1", "cwd": "/earth",
              "terminal_title_stripped": "π Optimize without changing"},
             {"pane_id": "p6", "tab_id": "t1", "cwd": "/earth",
              "agent_status": "unknown",
              "terminal_title_stripped": "> - set the default also to 30s"}]
    tabs = [{"tab_id": "t1", "label": "earth"}]
    cols = mod.build_columns(agents, {}, 1000.0, 600, tabs=tabs, panes=panes,
                             pane_agents={"p6": [{"agent": "cline", "pid": 12,
                                                  "rss": 1966080}]})
    by_pane = {c["pane"]: c for c in cols}
    assert set(by_pane) == {"p8", "p6"}
    assert by_pane["p8"]["agent"] == "omp" and by_pane["p8"]["chip"] == "working"
    assert by_pane["p6"]["agent"] == "cline"      # probed behind the mc wrapper
    assert by_pane["p6"]["tab_name"] == "earth"
    assert by_pane["p6"]["pid"] == 12
    assert "CL" in mod.compact_line(by_pane["p6"], 60)   # cline badge
    assert "π" in mod.compact_line(by_pane["p8"], 60)    # omp badge in place


def test_build_columns_shows_every_agent_kind_of_a_pane():
    """Two agent kinds in one pane render two columns; the card leads its own."""
    panes = [{"pane_id": "p1", "tab_id": "t1", "agent_status": "unknown",
              "cwd": "/x", "terminal_title_stripped": "> - set the default"}]
    cards = {"p1": {"pane_id": "p1", "tab_id": "t1", "agent": "cline",
                    "header": "earth", "status": "editing board.py",
                    "updated": 990.0}}
    tabs = [{"tab_id": "t1", "label": "earth"}]
    cols = mod.build_columns([], cards, 1000.0, 600, tabs=tabs, panes=panes,
                             pane_agents={"p1": [
                                 {"agent": "omp", "pid": 5, "rss": 4096},
                                 {"agent": "cline", "pid": 7, "rss": 100}]})
    by_pane = {c["pane"]: c for c in cols}
    assert set(by_pane) == {"p1", "p1#omp"}
    assert by_pane["p1"]["agent"] == "cline"      # the card's agent leads
    assert by_pane["p1"]["text"] == "editing board.py"
    assert by_pane["p1"]["pid"] == 7
    assert by_pane["p1"]["age"] == 10.0
    assert by_pane["p1#omp"]["agent"] == "omp"
    assert by_pane["p1#omp"]["pid"] == 5 and by_pane["p1#omp"]["rss"] == 4096
    assert by_pane["p1#omp"]["text"] == "" and by_pane["p1#omp"]["age"] is None


def test_build_columns_hides_herdr_cards_without_a_live_pane():
    """A herdr card whose pane is gone renders no column at all."""
    cards = {"p1": {"pane_id": "p1", "herdr": True, "status": "stale"}}
    panes = [{"pane_id": "p2", "tab_id": "t1", "agent_status": "working",
              "cwd": "/x"}]
    assert mod.build_columns([], cards, 1000.0, 600, tabs=[], panes=panes) == []


def test_sweep_drops_only_truly_dead_panes(state: Path):
    """sweep keeps a card while its pane or tab is live and drops it otherwise.

    Args:
        state: Isolated state directory fixture.
    """
    mod.save_card({"pane_id": "p2", "herdr": True, "tab_id": "t1"})
    tabs = [{"tab_id": "t1"}]
    # snapshot without a pane list: the live tab keeps the unclassified card
    mod.sweep(mod.load_cards(), [{"pane_id": "p1"}], tabs, [])
    assert "p2" in mod.load_cards()
    # pane list is authoritative: the vanished pane drops the card
    mod.sweep(mod.load_cards(), [{"pane_id": "p1"}], tabs,
              [{"pane_id": "p1", "tab_id": "t1"}])
    assert "p2" not in mod.load_cards()
    # the pane is listed again: the card survives
    mod.save_card({"pane_id": "p2", "herdr": True, "tab_id": "t1"})
    mod.sweep(mod.load_cards(), [], [], [{"pane_id": "p2", "tab_id": "t1"}])
    assert "p2" in mod.load_cards()
    # pane and tab both gone: dropped
    mod.sweep(mod.load_cards(), [], [{"tab_id": "t9"}],
              [{"pane_id": "p1", "tab_id": "t1"}])
    assert "p2" not in mod.load_cards()
    # cards outside herdr are never swept
    mod.save_card({"pane_id": "ext-tty1", "herdr": False})
    mod.sweep(mod.load_cards(), [], [], [])
    assert "ext-tty1" in mod.load_cards()
    # a live pane whose recorded herdr tab is gone: the tab check removes it
    mod.save_card({"pane_id": "p3", "herdr": True, "tab_id": "t1"})
    mod.sweep(mod.load_cards(), [], [{"tab_id": "t9"}],
              [{"pane_id": "p3", "tab_id": "t9"}])
    assert "p3" not in mod.load_cards()
    # no live tab list at all (older snapshot): the live pane is enough
    mod.save_card({"pane_id": "p4", "herdr": True, "tab_id": "t1"})
    mod.sweep(mod.load_cards(), [], [], [{"pane_id": "p4", "tab_id": "t1"}])
    assert "p4" in mod.load_cards()


def test_gather_columns_refreshes_and_sweeps(state: Path,
                                             monkeypatch: pytest.MonkeyPatch):
    """gather_columns merges snapshot, cards, and probes into fresh columns.

    Args:
        state: Isolated state directory fixture.
        monkeypatch: pytest fixture stubbing the herdr snapshot and /proc scan.
    """
    mod.save_card({"pane_id": "p2", "herdr": True, "tab_id": "t1",
                   "header": "earth", "agent": "cline", "status": "board work",
                   "updated": 995.0})
    mod.save_card({"pane_id": "p9", "herdr": True, "tab_id": "tGone"})
    monkeypatch.setattr(mod, "scan_procs", lambda: ({}, {}))
    monkeypatch.setattr(mod, "detect_pane_agents", lambda b, p, a: {})
    monkeypatch.setattr(mod, "herdr_snapshot", lambda b: (
        [{"pane_id": "p1", "tab_id": "t1", "agent": "omp",
          "agent_status": "working", "cwd": "/x"}],
        [{"tab_id": "t1", "label": "earth"}],
        [{"pane_id": "p1", "tab_id": "t1"}, {"pane_id": "p2", "tab_id": "t1"}]))
    cols, herdr_ok = mod.gather_columns("herdr", 1000.0, 600)
    assert herdr_ok is True
    assert {c["pane"] for c in cols} == {"p1", "p2"}
    assert "p9" not in mod.load_cards()   # dead tab swept from disk
    assert "p2" in mod.load_cards()

    monkeypatch.setattr(mod, "herdr_snapshot", lambda b: (None, [], []))
    cols, herdr_ok = mod.gather_columns("herdr", 1000.0, 600)
    assert herdr_ok is False
    assert cols == []                     # herdr cards hidden while unreachable
    assert "p2" in mod.load_cards()       # but never deleted


# ---------------------------------------------------------------------------
# rendering
# ---------------------------------------------------------------------------

def test_head_parts_badge_extraction_and_prepend():
    """head_parts builds styled segments with a per-agent badge before the header.

    usage: test_head_parts_badge_extraction_and_prepend
    returns: None.

    Example:
        test_head_parts_badge_extraction_and_prepend()
    """
    omp = col(agent="omp", header="π > Fix GUI geometry validation")
    assert [s for s, _ in mod.head_parts(omp)] == \
        ["(● working)", " (", "tab", ")", " π", " > Fix GUI geometry validation"]

    oc = col(agent="opencode", header="OpenCode")
    assert [s for s, _ in mod.head_parts(oc)][-1] == " OpenCode"

    agy = col(agent="agy", header="fmann@amd:~/x")
    parts = mod.head_parts(agy)
    assert parts[-2][1] == "badge" and parts[-2][0].endswith("AG")
    assert parts[-1][1] == "desc"
    fb = col(agent="freebuff", header="continue", tab_name="")
    parts = mod.head_parts(fb)
    assert parts[-2][1] == "badge" and parts[-2][0].endswith("FB")
    assert parts[-1] == (" continue", "desc")

    unknown = col(agent="weird", header="whatever", tab_name="")
    assert [k for _, k in mod.head_parts(unknown)] == [None, "desc"]


def test_cline_badge_symbol_and_agent_aliases():
    """cline and freebuff are known agent kinds carrying a CL/FB badge."""
    assert mod.AGENT_ALIASES["cline"] == {"cline"}
    assert mod.AGENT_ALIASES["freebuff"] == {"freebuff"}
    assert mod.AGENT_KIND_BY_NAME["freebuff"] == "freebuff"
    assert mod.AGENT_BADGE["cline"] == ("CL", ())
    cl = col(chip="unknown", agent="cline", header="> fix the build")
    assert (" CL", "badge") in mod.head_parts(cl)
    assert "CL" in mod.compact_line(cl, 60)


def test_column_lines_header_on_one_row():
    """column_lines renders the whole rule head on a single row.

    The step trail is opt-in, so the default block ends after the status line.
    """
    c = col(chip="idle", text="a", age=1,
            log=[{"t": 1000.0, "k": "step", "m": "todo"}])
    block = mod.column_lines(c, 80, num=4)
    assert "".join(t for t, _ in block[0]) == "4 ┌─ (○ idle) (tab) π Title"
    assert len(block) == 4  # head, meta, text, └
    assert block[1] == [("│ omp · w1:t1 · updated 1s", "meta")]
    assert not any(k == "trail" for row in block for _, k in row)


def test_column_lines_trail_is_opt_in():
    """column_lines draws the step trail only when trail=True is passed."""
    c = col(chip="idle", text="a", age=1,
            log=[{"t": 1000.0, "k": "step", "m": "todo"}])
    block = mod.column_lines(c, 80, num=4, trail=True)
    assert len(block) == 5  # head, meta, text, trail, └
    assert block[3][0][1] == "trail"
    assert block[3][0][0].endswith("step: todo")


def test_column_lines_truncates_head_to_width():
    """column_lines clips head segments at the given width.

    usage: test_column_lines_truncates_head_to_width
    returns: None.

    Example:
        test_column_lines_truncates_head_to_width()
    """
    block = mod.column_lines(col(chip="idle"), 10, num=4)
    assert "".join(t for t, _ in block[0]) == "4 ┌─ (○ id"


def test_compact_line_segments_and_width():
    """compact_line joins column segments and truncates to the given width.

    usage: test_compact_line_segments_and_width
    returns: None.

    Example:
        test_compact_line_segments_and_width()
    """
    c = col(text="status text")
    assert mod.compact_line(c, 200) == \
        "(● working) (tab) π Title · status text"
    wide = col(header="x" * 100)
    assert mod.compact_line(wide, 20) == \
        mod.compact_line(wide, 20)[:20]


def test_render_frame_trail_is_opt_in():
    """render_frame hides the step trail unless trail=True is passed."""
    c = col(chip="working", text="editing board.py",
            log=[{"t": 1000.0, "k": "step", "m": "todo 2/5"}])
    plain = mod.render_frame([c], herdr_ok=True, color=False)
    assert "● editing board.py" in plain
    assert "todo 2/5" not in plain
    with_trail = mod.render_frame([c], herdr_ok=True, color=False, trail=True)
    assert "· [" in with_trail and "step: todo 2/5" in with_trail


def test_render_frame_plain_and_active_count():
    """render_frame emits no ANSI escapes in plain mode and counts active agents.

    usage: test_render_frame_plain_and_active_count
    returns: None.

    Example:
        test_render_frame_plain_and_active_count()
    """
    cols = [col(chip="working", text="a", age=1),
            col(chip="input", text="question?", age=1),
            col(chip="stopped", text="quota", age=1),
            col(chip="idle", age=1)]
    frame = mod.render_frame(cols, herdr_ok=True, color=False)
    assert "\x1b[" not in frame
    head = frame.splitlines()[0]
    assert "4 agents" in head and "2 active" in head


def test_render_frame_colors():
    """render_frame colorizes stopped and input chips when color is enabled.

    usage: test_render_frame_colors
    returns: None.

    Example:
        test_render_frame_colors()
    """
    red = mod.render_frame([col(chip="stopped")], True, color=True)
    assert "\x1b[31m(■ stopped)" in red
    yellow = mod.render_frame([col(chip="input")], True, color=True)
    assert "\x1b[33m(❯ needs input)" in yellow


def test_render_frame_compact_rows():
    """render_frame packs columns into compact multi-column rows.

    usage: test_render_frame_compact_rows
    returns: None.

    Example:
        test_render_frame_compact_rows()
    """
    cols = [col(pane=f"p{i}", chip="idle") for i in range(7)]
    frame = mod.render_frame(cols, herdr_ok=True, color=False, compact=True,
                             width=118)
    lines = [ln for ln in frame.splitlines() if ln.strip()]
    assert len(lines) == 5  # header + 4 rows for 7 agents (odd -> last single)
    assert lines[1].count("│") == 1 and lines[-1].count("│") == 0


def test_render_frame_herdr_unreachable_banner():
    """render_frame shows a banner when the herdr snapshot is unreachable.

    usage: test_render_frame_herdr_unreachable_banner
    returns: None.

    Example:
        test_render_frame_herdr_unreachable_banner()
    """
    frame = mod.render_frame([], herdr_ok=False, color=False)
    assert "herdr snapshot unreachable" in frame


# ---------------------------------------------------------------------------
# help coloring
# ---------------------------------------------------------------------------

def test_colorize_help_respects_env(monkeypatch: pytest.MonkeyPatch):
    """colorize_help disables coloring under NO_COLOR and forces it under FORCE_COLOR.

    usage: test_colorize_help_respects_env <MONKEYPATCH>
    returns: None.

    Args:
        monkeypatch (pytest.MonkeyPatch): Sets and clears the color env vars.

    Example:
        test_colorize_help_respects_env(pytest.MonkeyPatch())
    """
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
    """resolve_proc matches a process by agent alias and cwd, preferring higher pid.

    usage: test_resolve_proc_aliases_and_cwd
    returns: None.

    Example:
        test_resolve_proc_aliases_and_cwd()
    """
    procs = ({}, {("omp", "/proj"): [(10, "omp", 100), (11, "omp", 900)],
                  ("claude", "/proj"): [(12, "claude", 50)]})
    assert mod.resolve_proc("omp", "/proj", procs) == (11, 900)
    assert mod.resolve_proc("claude", "/nowhere", procs) == (None, None)


def test_resolve_ext_proc_by_tty():
    """resolve_ext_proc resolves an external pane id to a pid via the tty map.

    usage: test_resolve_ext_proc_by_tty
    returns: None.

    Example:
        test_resolve_ext_proc_by_tty()
    """
    procs = ({"pts-3": [(21, "opencode", 700)]}, {})
    assert mod.resolve_ext_proc("ext-pts-3", procs) == (21, 700)
    assert mod.resolve_ext_proc("ext-pts-9", ({}, {})) == (None, None)


def test_scan_procs_shape():
    """scan_procs returns two dictionaries keyed by tty and by agent kind.

    usage: test_scan_procs_shape
    returns: None.

    Example:
        test_scan_procs_shape()
    """
    by_tty, by_kind = mod.scan_procs()
    assert isinstance(by_tty, dict) and isinstance(by_kind, dict)


# ---------------------------------------------------------------------------
# CLI end-to-end (subprocess, isolated state)
# ---------------------------------------------------------------------------

@pytest.fixture
def run(tmp_path: Path):
    """Yield a helper that runs the agent_board CLI in an isolated subprocess.

    usage: run <TMP_PATH>
    returns: Callable invoking agent_board.py with XDG_STATE_HOME under tmp_path.

    Args:
        tmp_path (Path): pytest temporary directory backing the isolated state.

    Example:
        run("--version", check=True)
    """
    env = dict(os.environ, XDG_STATE_HOME=str(tmp_path / "xdgstate"))
    env.pop("HERDR_PANE_ID", None)

    def run(*args, check=False) -> subprocess.CompletedProcess:
        """Run agent_board.py with the given CLI arguments.

        usage: run <ARGS...> [CHECK]
        returns: The completed subprocess as a subprocess.CompletedProcess.
        errors: AssertionError when check is True and the exit code is nonzero.

        Args:
            args (str): CLI arguments passed to agent_board.py.
            check (bool, optional): Require a zero exit code. Defaults to False.

        Example:
            run("--herdr-bin", HERDR_MISSING, "note", "step", "-m", "resumed")
        """
        proc = subprocess.run([sys.executable, str(MODULE_PATH), *args],
                              capture_output=True, text=True, env=env,
                              timeout=30)
        if check:
            assert proc.returncode == 0, proc.stderr
        return proc
    return run


def test_cli_note_lifecycle_and_frames(run):
    """CLI note subcommands drive the card lifecycle and rendered frames track it.

    usage: test_cli_note_lifecycle_and_frames <RUN>
    returns: None.

    Args:
        run: Subprocess runner fixture bound to an isolated state dir.

    Example:
        test_cli_note_lifecycle_and_frames(run)
    """
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
    """The CLI exits with code 2 when given an unknown note action.

    usage: test_cli_bad_action_rejected <RUN>
    returns: None.

    Args:
        run: Subprocess runner fixture bound to an isolated state dir.

    Example:
        test_cli_bad_action_rejected(run)
    """
    proc = run("note", "explode", "-m", "x")
    assert proc.returncode == 2


def test_build_parser_default_refresh_is_30s():
    """The CLI defaults to a 30 s refresh and accepts explicit overrides."""
    ap = mod.build_parser()
    assert ap.parse_args([]).poll_period == 30.0
    assert ap.parse_args(["--autorefresh", "5"]).poll_period == 5.0
    assert ap.parse_args(["--poll-period", "2"]).poll_period == 2.0
    assert ap.parse_args(["serve"]).cmd == "serve"
    assert ap.parse_args([]).trail is False       # step trails stay hidden
    assert ap.parse_args(["--trail"]).trail is True


def test_wrapper_help():
    """The bash wrapper forwards help and rejects unknown subcommands with code 2.

    usage: test_wrapper_help
    returns: None.

    Example:
        test_wrapper_help()
    """
    proc = subprocess.run(["bash", str(REPO / "agent_board"), "help"],
                          capture_output=True, text=True, timeout=10)
    assert proc.returncode == 0
    assert "view-compact" in proc.stdout
    proc = subprocess.run(["bash", str(REPO / "agent_board"), "bogus"],
                          capture_output=True, text=True, timeout=10)
    assert proc.returncode == 2 and "usage:" in proc.stderr

def test_version_flag_and_header(run):
    """--version prints the module version and the frame header shows it.

    usage: test_version_flag_and_header <RUN>
    returns: None.

    Args:
        run: Subprocess runner fixture bound to an isolated state dir.

    Example:
        test_version_flag_and_header(run)
    """
    proc = run("--version")
    assert proc.returncode == 0
    assert mod.__version__ in proc.stdout and "agent_board" in proc.stdout
    plain = mod.render_frame([], herdr_ok=True, color=False)
    assert plain.splitlines()[0].endswith(f"  ({mod.__version__})")
    colored = mod.render_frame([], herdr_ok=True, color=True)
    assert f"\x1b[37m  ({mod.__version__})\x1b[0m" in colored


def test_wrapper_version():
    """The bash wrapper --version prints the module version and script name.

    usage: test_wrapper_version
    returns: None.

    Example:
        test_wrapper_version()
    """
    proc = subprocess.run(["bash", str(REPO / "agent_board"), "--version"],
                          capture_output=True, text=True, timeout=10)
    assert proc.returncode == 0
    assert mod.__version__ in proc.stdout and "agent_board" in proc.stdout


# ---------------------------------------------------------------------------
# click-to-focus
# ---------------------------------------------------------------------------

def test_column_at_click_compact_mapping():
    """column_at_click maps compact-row clicks to columns, splitting at the separator.

    usage: test_column_at_click_compact_mapping
    returns: None.

    Example:
        test_column_at_click_compact_mapping()
    """
    row_map = {2: (0, 3), 3: (1, None)}
    assert mod.column_at_click(row_map, 2, 10, True, 48) == 0     # left
    assert mod.column_at_click(row_map, 2, 48, True, 48) == 0     # │ column
    assert mod.column_at_click(row_map, 2, 50, True, 48) == 3     # right
    assert mod.column_at_click(row_map, 2, 60, True, 48) == 3
    assert mod.column_at_click(row_map, 3, 60, True, 48) == 1     # no right
    assert mod.column_at_click(row_map, 9, 10, True, 48) is None  # off-board


def test_column_at_click_fullscreen_mapping():
    """column_at_click maps fullscreen rows directly to a column index.

    usage: test_column_at_click_fullscreen_mapping
    returns: None.

    Example:
        test_column_at_click_fullscreen_mapping()
    """
    assert mod.column_at_click({4: 1, 5: 1, 6: 1}, 5, 0, False, 48) == 1
    assert mod.column_at_click({}, 5, 0, False, 48) is None


def test_tui_click_focuses_herdr_tab(tmp_path: Path):
    """The TUI focuses a herdr tab on both mouse click and number jump.

    usage: test_tui_click_focuses_herdr_tab <TMP_PATH>
    returns: None.

    Args:
        tmp_path (Path): pytest temporary directory for the fake herdr binary.

    Example:
        test_tui_click_focuses_herdr_tab(Path("/tmp/pytest-tui"))
    """
    log = tmp_path / "herdr-log"
    fake = tmp_path / "fake-herdr"
    snap = json.dumps({"result": {"snapshot": {
        "agents": [{"pane_id": "p1", "tab_id": "w1:tX", "agent": "omp",
                    "agent_status": "working", "cwd": "/x"},
                   {"pane_id": "p2", "tab_id": "w1:tY", "agent": "claude",
                    "agent_status": "idle", "cwd": "/y"}],
        "tabs": [{"tab_id": "w1:tX", "label": "Test"},
                 {"tab_id": "w1:tY", "label": "Second"}],
        "panes": []}}})
    fake.write_text(
        "#!/bin/bash\necho \"$@\" >> " + str(log) + "\n"
        "if [ \"$1\" = api ] && [ \"$2\" = snapshot ]; then\n"
        "    echo '" + snap.replace("'", "") + "'\nfi\n")
    fake.chmod(0o755)

    import pty
    import select as sel
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
    assert "1 (" in clean and "2 (" in clean  # both columns numbered

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
