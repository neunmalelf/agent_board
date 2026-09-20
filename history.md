# agent_board - History

> Keep this file up to date before every release: add an entry for the new
> version at the top. The latest entry doubles as the release notes.
> Decisions get their own dated entry with reasoning and rejected
> alternatives. Rules: see `.agentrules` (History Rule) and
> `docs/development.md`.

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