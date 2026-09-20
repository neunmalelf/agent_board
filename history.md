# agent_board - History

> Keep this file up to date before every release: add an entry for the new
> version at the top. The latest entry doubles as the release notes.
> Decisions get their own dated entry with reasoning and rejected
> alternatives. Rules: see `.agentrules` (History Rule) and
> `docs/development.md`.

## 2.9.20260920145912Z - 2026-09-20

Requested from the board: "agents in the same tab should be sorted after each
other". Reproduced in the live 2.8 frame - the `earth` tab's two agents were
rendered at positions 3 and 7 of the compact view, interleaved with
`media_downloader`, `quizza_app`, `1_ddpico` and `admin1`, because
`build_columns()` sorted all columns by chip priority alone.

Fix: `build_columns()` now groups first, then sorts.

- Columns are collected per tab (`by_tab`), each group is sorted with the new
  `column_sort_key()` (chip priority, then card age - the key that the flat
  sort used inline before), and the groups are sorted by their first member,
  i.e. by the tab's most urgent column. The result is flattened
  group by group.
- Because the groups themselves are ordered by their best column, the board
  keeps its attention order at tab level (`working` tab first, `done` tab
  last) and stays contiguous inside every tab, even when two tabs have
  identical rank tuples - a `(rank, key)` sort key could not guarantee that,
  since two tabs with the same rank would interleave. This is why the group
  list is sorted and flattened instead of encoding the tab in the key.
- A column without a tab (`ext-*` agents outside herdr) forms its own group
  and therefore keeps its place in the flat status/age order instead of being
  pulled into a tab block.
- Effect on the live board: `1_ddpico` (working agy + idle omp), then `earth`
  (probed cline + omp), then the two freebuff tabs, then the two `done` tabs.
  In the compact view the pair of a tab now occupies adjacent rows.

Tests 82 → 83; README gains an "Order" bullet, `tldr/agent_board.md` and
`man/agent_board.1` name the grouping.

Rejected alternatives:

- Sorting by `(tab, status, age)`: tabs would be in tab-id order instead of
  attention order, so a `done` tab could appear above a `working` one.
- Sorting by `(status, age, tab)`: keeps a flat order and only breaks ties by
  tab, so the two agents of one tab still end up apart.
- Using the *lowest* chip rank of a tab as the group rank and putting the tab
  id in the key: the key would only keep agents of the same tab together when
  their rank tuples differ; equal tuples (two tabs with the same chip and the
  same age) would interleave again.

## 2.8.20260920145442Z - 2026-09-20

Reported from the board: pressing Ctrl+C in the fullscreen TUI printed

    Traceback (most recent call last):
      File ".../board.py", line 1562, in run_tui
        key = stdscr.getch()
    KeyboardInterrupt

`curses.wrapper` did restore the terminal, but the interrupt surfaced as an
unhandled traceback and exit code 1, even though quitting the board is a
normal user action.

Fix:

- `run_tui()` wraps `stdscr.getch()` in `try/except KeyboardInterrupt:
  return` and also treats the ETX byte (key 3, a terminal that hands Ctrl+C
  over as a key instead of raising SIGINT) like `q`, so the loop leaves
  through the same path as a quit.
- `main()` wraps the `curses.wrapper(run_tui, ...)` call and the
  `run_serve(...)` call in `try/except KeyboardInterrupt: pass`, which
  covers an interrupt raised *between* refreshes (for example inside the
  `herdr api snapshot` subprocess) and the headless frame writer. Both paths
  return 0 after curses restored the screen; no partial frame file is left,
  because the frame is written to a `.tmp` file and `os.replace`d.
- UI/docs: the footer reads `q/Ctrl+C quit`, and README, `tldr/agent_board.md`
  and `man/agent_board.1` name Ctrl+C next to `q`.

Verified: a pty test sends `\x03` into the running TUI - it exits 0 with an
empty stderr (against the 2.7 code the same test fails with
`waitstatus_to_exitcode(status) == -2`, i.e. the SIGINT death the user saw).
`serve` was driven with a real SIGINT under a fresh `XDG_STATE_HOME`: exit 0,
empty stderr, frame written.

Second defect found while checking the `serve` path on a fresh state
directory: `run_serve()` wrote its frame with `open(frame_path + ".tmp")`
without creating the parent directory, so `agent_board.py serve` died with
`FileNotFoundError: .../agent_board/board.txt.tmp` until some agent posted
the first card (the systemd unit would have crash-looped every 5 s).
`run_serve()` now runs `os.makedirs(os.path.dirname(frame_path) or ".",
exist_ok=True)` once before its loop, pinned by the new
`test_run_serve_creates_the_frame_dir_and_writes_a_frame`.

Tests 79 → 82.

Rejected alternatives:

- Letting the traceback stand and documenting Ctrl+C as unsupported: quitting
  a TUI with Ctrl+C is the expected reflex; a traceback after a clean
  screen-restore is noise, and the exit code lied about it (1 instead of 0).
- Exiting with 130 after handling the interrupt: the board treats Ctrl+C as
  an alias for `q`, and the test suite (and the pty test) asserts a plain 0;
  130 would have to be explained in every script that wraps the board.
- Catching `KeyboardInterrupt` inside `run_serve()` and returning early: the
  loop lives in `main()`'s dispatch, so one handler there covers `serve`,
  the TUI, and `--once` in a single place.
- Installing a SIGINT handler that only sets a flag: it would need the loop
  to poll it in several places (getch, redraw, subprocess calls) for no gain
  over the exception, which already unwinds to a safe point.
- Fixing the doubled backslashes in `man/agent_board.1` (every roff escape
  is written as `\\fB`, so `groff -man` renders a literal `\fB`): a
  pre-existing, repo-wide man-source defect unrelated to this fix; it needs
  its own commit rather than riding along with the Ctrl+C change.

## 2.7.20260920144525Z - 2026-09-20

Follow-up to the 2.5 agent-pane work, reported against the live session
(6 tabs, 20 panes, herdr 0.8.2): "in herdr tab: earth are currently running
two agents, but only one is shown" - and "we need a symbol for cline".

Reproduced live. The `earth` tab (`w1:t1Z`) hosts three panes: `w1:p6A`
(herdr-classified `omp`) and `w1:p68`, where the second agent lives *nested*:

    w1:p68 shell 3803349 (pts/30) -> mc 3962741 (foreground process)
      -> bash 3962743 (/bin/bash --rcfile .bashrc)
      -> cline 4010057 (node .../bin/cline, own pts/28)

`herdr pane process-info --pane w1:p68` reports only `mc` in
`foreground_processes`, and the 2.5 probe matched that list by process `name`
only. `mc` is not a known agent kind, so the pane produced no column and the
tab showed a single agent; the cline pane also never showed its (documented,
tested) `CL` badge.

Fix:

- **The probe follows the pane's process tree.** `pane_agents()` walks the
  `/proc` descendants of the pane's foreground processes
  (`child_pids()`/`proc_tree()`, bounded by `MAX_TREE_PROCS`) and matches an
  agent by process name *and* by argv (`proc_kind()`: argv[0], argv[1], and
  any token containing a path, with `AGENT_ARG_SUFFIXES` stripped) - so
  `node-MainThread` running `.../bin/cline`, `mc` wrapping a nested terminal
  agent, and plain `omp` all resolve. Verified live: `w1:p68` now reports
  `cline` (pid 4010065 / 1.3 GB) and the board renders the earth tab as two
  columns, `CL > - set the default also to 30s` and `π Optimize without
  changing`. The probe costs ~0.10 s for the 16 unclassified panes of the
  session.
- **One entry per agent kind.** `pane_agents()` groups the tree by kind and
  keeps the largest-RSS process of each, so an mc pane hosting two different
  agents (mc-embedded terminals are separate agent sessions) is no longer
  reduced to one column. `build_columns()` renders the extras under
  `<pane>#<kind>` and lets the kind that posted the card lead its column;
  `pane_agent()` remains the largest-entry wrapper for `note register`.
- **Tab liveness before every refresh, made explicit.** `sweep()` now also
  drops a herdr card whose recorded tab is missing from a non-empty live tab
  list (`live_tabs and tab and tab not in live_tabs`), instead of only
  reacting to a vanished pane. Verified against the live snapshot first:
  every pane's `tab_id` and every agent's `tab_id` are present in `tabs`, so
  the check cannot hide a live agent; a snapshot without a tab list keeps
  everything.
- **30 s default re-verified** (all modes) - no code change: argparse
  default, bash `view`/`view-compact`, `_run`, and the systemd `serve` unit
  all refresh every 30 s; `test_build_parser_default_refresh_is_30s` pins it.

Tests 65 → 79 (probe tree/argv matrix, nested wrapper, per-kind columns, the
earth shape, tab-liveness sweep). Found and fixed while editing the suite:
`test_self_pane_id_prefers_env` had lost its `def` line, so its assertions
ran at the end of the preceding test and `self_pane_id` was not a test of its
own.

Rejected alternatives:

- Matching the pane's `cwd` or the agent's tty instead of the process tree:
  the live cline agent runs on its own pts (`/dev/pts/28`) because `mc`
  embeds a terminal for it, and its cwd differs from the pane's - only the
  parent chain ties it to the pane.
- Walking the descendants of the pane's *shell* as well: that would surface
  deliberately backgrounded agents of a pane as columns; the foreground tree
  covers the wrapper case that was actually missed, and background agents
  still announce themselves through a posted card.
- Replacing the `CL` badge with a glyph: `CL` is documented, tested, and
  consistent with `AG`/`OC`/`FB`; the real defect was that the earth cline
  pane was never detected, so the badge had nothing to decorate.
- Matching every argv token: a token like `cline.md` (`vim cline.md`,
  `grep cline`) would fabricate columns; only argv[0], argv[1], and
  path-bearing tokens are considered, and a suffix that is not a known code
  extension stays unmatched.

## 2.6.20260920141919Z - 2026-09-20

Follow-up to 2.5, requested right after it: once every agent pane gets a
column, the board got cluttered because each column repeated up to four
`· [hh:mm] step: ...` lines - the agents' step-by-step process. The step
trail is now opt-in:

- `trail=False` by default in `column_lines()`, `render_frame()`,
  `render_once()`, `run_tui()`, and `run_serve()`: head rule, meta line
  (agent/tab/pid/mem/age), current status line, closing rule.
- New `--trail` flag re-enables the last four log entries for the TUI,
  `--once`, and `serve` (`agent_board.py --trail`, `agent_board.py --trail
  --once`, `agent_board.py --trail serve`).
- Cards keep the full log (24 entries, `MAX_LOG`), so nothing is lost: the
  steps are still on disk for inspection, only the screen is quiet.
- Tests 63 → 65; README (Columns bullet, run commands, serve example),
  `man/agent_board.1`, `tldr/agent_board.md`, `NEWS.md`, `ChangeLog.md`.

Rejected alternatives:

- Dropping the log from the cards: the trail is the agents' audit trail and
  the `note step` contract depends on it; only rendering should stay quiet.
- Also hiding the meta line (pid/mem/tab): one line per column, and it
  answers "which tab and process", not "what did the agent think".
- Hiding the status line too: the board exists to show what an agent is
  doing right now, so the current line stays.

## 2.5.20260920140934Z - 2026-09-20

Board fixes requested against the live session (6 tabs, 20 panes):

- **Refresh default 2 s → 30 s.** The bash `agent_board view` wrapper
  already defaulted to `--autorefresh 30`, but the Python default was 2 s,
  so `agent_board.py`, `./_run`, `--once`, and `agent_board.py serve`
  refreshed four times faster than documented. The default now lives in
  argparse (30 s; minimum 1 s still enforced via `max(1.0, ...)`), and
  parser construction moved into `build_parser()` so a test asserts it.
  `serve` inherits 30 s too; `serve --poll-period 2` restores the lively
  frame file.
- **One column per agent pane, not per tab.** Reproduced live: the
  `media_downloader` and `quizza_app` tabs were running freebuff agents,
  but herdr reported both tabs as `agent_status: unknown` with no
  classified agent, so the board showed only a `(? unknown) <tab>`
  placeholder. Root cause: `build_columns()` iterated the herdr *agent*
  list, and `sweep()` deleted the card of any pane missing from that same
  list, so an agent posting from a pane herdr did not classify lost its
  column on the next refresh (the shape of the reported "two agents in one
  tab, only one shown"). Fix: `herdr_snapshot()` returns agents + tabs +
  panes; every unclassified pane that has a card or a known agent process
  in its foreground (`herdr pane process-info`, one ~7 ms call per such
  pane, RSS from `/proc`) gets its own column. Verified live:
  media_downloader and quizza_app now render real `FB freebuff` columns
  (pid 3632586 / 1541444) instead of placeholders.
  Limitation kept on purpose: the probe sees foreground processes only, so
  an agent that runs in the background of a pane (or headless without a
  pane, like a systemd-spawned cline connector) is shown through its own
  posted card, not through the probe.
- **Tab liveness before every refresh.** `sweep(cards, agents, tabs,
  panes)` keeps a card while its pane is live, and - when the snapshot
  carries no pane list - while its tab is live; a closed pane or tab
  removes the column immediately, and an unreachable snapshot sweeps
  nothing.
- **`CL` badge for cline** in `AGENT_BADGE`; cline and freebuff added to
  `AGENT_ALIASES`/`AGENT_KIND_BY_NAME` so the pane probe and pid/mem
  resolution know them.
- **`herdr_match()` narrowed.** It used to match a tab id as eagerly as a
  pane id, so a second agent in a tab inherited the first one's kind and
  title at register time. It now matches the exact pane first and uses a
  tab only when no pane id was given and the tab hosts exactly one agent.
- Housekeeping: the separate commit before this change lowercased the
  board skill to `skills/agent-board/skill.md`; agent-watch only moved its
  version stamp with the release (no code change).

Rejected alternatives:

- Matching agent processes by pane `cwd` through `/proc` instead of
  `herdr pane process-info`: the live probe showed agent processes whose
  cwd differs from the pane's cwd, so cwd matching would have produced
  misses and false positives.
- Relying on `herdr pane report-agent` (the custom-agent API): it requires
  the agent to report itself, while the board should show what actually
  runs in a tab.
- Creating a card automatically for every detected agent process: the
  board stays card-driven for text (what the agent says) and
  probe-driven for presence (that it runs).

## 2.4.20260915185906Z - 2026-09-15

`agent_watch.py` launcher shim removed. `~/sbin/agent-watch` now points
directly at `src/agent_board/watch.py` (executable + shebang kept), so
the systemd unit runs the module file itself; `agent_board.py` remains as
the only launcher shim. References dropped from README (intro, layout,
install, uninstall), `.agentrules` src-layout rule, `docs/index.md`,
`tldr/agent-watcher.md`, the package docstring, and
`man/agent_board.1` SEE ALSO (now `agent-watch (1)`). On this machine
the missing hyphen-named `~/sbin/agent-watch` symlink was the real
reason the unit had been crash-looping with 203/EXEC; created it and the
service is active again.

## 2.4.20260915185529Z - 2026-09-15

README: "Live board" section reworked with the run commands
(`agent_board view` / `agent_board view-compact`) next to their
screenshots. Stray `.README.md.kate-swp` and `problem layout view.png`
removed; hyphen spacing artifacts from the em-dash sweep fixed.

## 2.4.20260915185022Z - 2026-09-15

`requirements-dev.txt` deleted: it duplicated
`pyproject.toml [project.optional-dependencies].dev` exactly and nothing
consumed it. README now points at `python3 -m pip install -e ".[dev]"`;
`.agentrules` mentions only the pyproject extras.

## 2.4.20260915184915Z - 2026-09-15

Dash rule adopted: em dashes (U+2014) replaced with plain hyphens across
all markdown docs, docstrings, help texts, and shell/Python strings
(README, NEWS, ChangeLog, history, AGENTS.md, .agentrules, skills, docs/,
src, launcher shims, the `agent_board` service manager). New "Dash Rule"
section in `.agentrules` (1.0 -> 1.1 stamp); box-drawing characters are
exempt.

## 2.4.20260915184630Z - 2026-09-15

README: the two live-board screenshots (`view.jpg` fullscreen,
`view-compact.jpg` compact) are embedded as proper markdown images with
alt text instead of bare file names.

## 2.4.20260915184045Z - 2026-09-15

Bug fix - fullscreen TUI (normal view): the column head rendered one
segment per line (number, `┌─`, chip, tab label, badge, header stacked
vertically). `column_lines` now emits the whole rule head as a single row
of (text, kind) segments; `run_tui` draws rows via `draw_parts()`, keeping
per-segment colors (badge/tab/grey/desc). `accent_attr` gains the
"meta"/"text"/"trail" kinds for the meta/status/trail lines. Two new
tests (single-row head, width truncation); 51 pass. Verified live in
tmux at 72 cols.

## 2.4.20260915174736Z - 2026-09-15

Repository published: created the public GitHub repo
`neunmalelf/agent_board` and pushed master; `pyproject.toml [project.urls]`
now carries Repository and Issues links per the agent rules.

## 2.4.20260915182613Z - 2026-09-15

README intro: states up front that agent_board works on top of Herdr
(linked to https://herdr.dev) and is a POSIX tool - Linux fully
supported, macOS with reduced process discovery, Windows via WSL2.

## 2.4.20260915173031Z - 2026-09-15

Release documentation:

- **NEWS.md**: user-facing highlights per release (2.4, 2.3).
- **ChangeLog.md**: all notable changes newest-first, derived from
  `history.md` and the git log (1.0 → 2.4); points to `history.md` for
  decisions.
- **README.md**: Columns section documents herdr's custom-agent API for
  agents outside the built-in list (freebuff) and the `FB` badge.

## 2.4.20260915172753Z - 2026-09-15

Documentation: platform coverage, man/tldr install steps, stale paths:

- **README "Platforms"** section: Linux (fully supported), macOS
  (partial: no `/proc` so pid/mem + external-tty discovery are blind, no
  systemd so the user units don't apply - note/TUI/cards work), Windows
  (not supported natively: no `curses` in Windows CPython, no `/proc`,
  POSIX-only helpers; run inside WSL2 with systemd enabled).
- **README "man + tldr pages"** install block: install
  `man/agent_board.1` + `man/agent-watcher.1` into
  `~/.local/share/man/man1/` (watcher page under its .SH NAME,
  `agent-watch.1`) and both `tldr/` pages into the client's custom page
  dir. The directories existed but no install instructions did.
- **Stale paths fixed**: `tldr/agent-watcher.md` and
  `man/agent-watcher.1` still pointed at the pre-restructure
  `~/projects/agent-watcher/` tree and a nonexistent
  `agent-watcher-readme.md`; corrected to `agent_board` paths
  (`agent_watch.py` shim, `src/agent_board/watch.py`, repo README/man).
- agent-watch version 1.2 → 1.3 with the release stamp.
- **view-compact spacing**: the left column's agent rows now draw one
  space in, so the menu number no longer sits flush at column 0
  (`run_tui` compact path only; full frame blocks unchanged).
- **freebuff badge**: `AGENT_BADGE` gains `"freebuff": ("FB", ())` and
  `clean_title` drops a leading "Freebuff:" brand label, so herdr
  custom-reported freebuff agents render like every other agent
  (`(bento) FB continue`). Verified live: herdr
  `pane report-agent --agent freebuff` makes the board classify the tab;
  the freebuff agent itself posts via the installed agent-board skill.

## 2.3.20260913092333Z - 2026-09-13

Proper Python project packaging: src/ layout, tooling gates, helper scripts, hooks, docs:

- **src/ layout**: implementation moved into `src/agent_board/` (`board.py`,
  `watch.py`). The root-level `agent_board.py` / `agent_watch.py` are now
  thin launcher shims (sys.path bootstrap + `main()` call), so the
  `~/sbin` symlinks and both systemd units keep working unchanged. The
  package lives under `src/` because the root file `agent_board` (the bash
  service manager) blocks a root-level package directory.
- **pyproject.toml**: PEP 621 metadata (setuptools backend), console
  scripts `agent-board` / `agent-watch`, `[tool.ruff]` (E/F/I/UP/B/SIM,
  line-length 100), `[tool.mypy]`, `[tool.pytest.ini_options]`
  (pythonpath = src). Runtime stays stdlib-only (`dependencies = []`).
  Packaging version carries the stamp without the trailing Z (PEP 440
  forbids the Z); module `__version__` keeps it - `_check_version`
  enforces the pairing.
- **Tooling gates green**: `ruff check src tests` and
  `mypy src/agent_board` pass; ~40 lint/type findings fixed along the way
  (`contextlib.suppress`, `with open`, typed `row_map`/state dicts,
  f-string, nested `def`s replacing assigned lambdas, one `needs_attention`
  simplification). 49 pytest tests pass.
- **Helper scripts** (1_ddpico toolset): `_tests` (pytest + ruff + mypy),
  `_run`, `_menu`, `_git` (timestamp commits), `_install` (editable pip +
  hook wiring), `_build` (metadata + stamp checks; no artifacts by
  design), `_docs` (MkDocs), `_check_version`.
- **Hooks**: modular `hooks/pre-commit` (modules: version, ruff, mypy,
  tests, build, drop-ins) + `hooks/install.sh`; replaces the copied
  ddpico hook that referenced nonexistent `ddpico` paths and `_skill_sync`.
- **Docs**: `README.md` (replaces `agent_board_readme.md`), `docs/` +
  `mkdocs.yml`, `AGENTS.md`, `.agentrules`, MIT `LICENSE`,
  `requirements-dev.txt`, `.gitattributes` (LF).
- **History rules**: this release log (newest first) plus `history/`
  archive dirs (`prompts/ changes/ todo/ plans/ tests/ ideas/ goals/`).
- **Fixes**: `agent_board` wrapper installed a wrong unit filename
  (`agent-board.service` → actual `agent_board.service`); watch version
  bumped 1.1 → 1.2 with the release stamp.

## 2026-09-13 - Decision: no textual; the TUI stays curses

Evaluated the Python module `textual` (8.2.8, already installed on this machine) as a
replacement for the fullscreen TUI (`agent_board view` / `view-compact`) in
`agent_board.py`. Decision: **not adopted**. The board keeps its stdlib-only curses UI
(`run_tui` and its draw helpers), and `render_frame` / `serve` / `--once` / `note` are
untouched regardless.

Deciding factors:

- **stdlib-only invariant**: the project advertises "both Python 3, stdlib only".
  textual would add a real runtime dependency (textual + rich + transitive) and a
  `pip install` step to the fresh-machine install, plus lazy-import hygiene so
  `note`/`serve`/`--once` would still run on machines without it.
- **the ASCII column frame is the design**: the hand-drawn `┌─│└` columns would not
  survive textual's Panel/border widgets literally - adopting it meant accepting a
  visual redesign as part of the deal.
- **no pain to fix**: the curses layer is ~270 lines, works, and has no reported
  friction. The textual gains (free scrolling/wrapping, widget-based click handling,
  pilot-testable interaction) are conveniences, not answers to a current problem.

Findings from the assessment, quoted (2026-09-13 session):

> Costs:
>
> 1. **Breaks "stdlib only"** - readme line 5 and the install requirements. The dep
>    (textual + rich + a few transitive) is view-only, but it's real: fresh-machine
>    install gains a `pip install` step.
> 2. **Import hygiene required** - `curses` is currently top-level (:25). textual must
>    be lazily imported inside the view path, or `note`/`serve`/`--once` on a machine
>    without the dep break. This is the one non-obvious design decision.
> 3. **API churn** - textual majors fast; pin a version floor.
> 4. **Startup ~0.5 s** vs instant curses. Negligible for a board you open and leave.
> 5. **The ASCII frame (`┌─│└`) won't survive literally** - you'd get Panels/borders
>    that look better but different. A visual refresh is part of the deal, not
>    optional.
>
> Recommendation:
>
> Worth it, scoped exactly like the sketch: textual replaces only the fullscreen view;
> `render_frame`/serve/`--once`/`note` stay stdlib. You lose ~270 lines of the most
> hand-rolled, least-tested code in the file and gain real scrolling, wrapping, and
> testable interaction - for one lazily-imported dep. If the ASCII column aesthetic
> matters more to you than the interaction gains, the current curses layer is doing
> its job fine and I'd leave it.

The final call followed the closing condition of that recommendation: the ASCII column
aesthetic and the stdlib-only invariant matter more here than the interaction gains.

Revisit if: a needed feature outgrows curses (rich text wrapping, robust resize,
interaction tests), the stdlib-only constraint is dropped, or the curses layer starts
accumulating bugs.