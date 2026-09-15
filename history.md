# agent_board - History

> Keep this file up to date before every release: add an entry for the new
> version at the top. The latest entry doubles as the release notes.
> Decisions get their own dated entry with reasoning and rejected
> alternatives. Rules: see `.agentrules` (History Rule) and
> `docs/development.md`.

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