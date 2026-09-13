# agent_board — history

## 2026-09-13 — Decision: no textual; the TUI stays curses

Evaluated the Python module `textual` (8.2.8, already installed on this machine) as a
replacement for the fullscreen TUI (`agent_board view` / `view-compact`) in
`agent_board.py`. Decision: **not adopted**. The board keeps its stdlib-only curses UI
(`run_tui` and its draw helpers in `agent_board.py`), and `render_frame` /
`serve` / `--once` / `note` are untouched regardless.

Deciding factors:

- **stdlib-only invariant**: the project advertises "both Python 3, stdlib only"
  (readme). textual would add a real runtime dependency (textual + rich + transitive)
  and a `pip install` step to the fresh-machine install, plus lazy-import hygiene so
  `note`/`serve`/`--once` would still run on machines without it.
- **the ASCII column frame is the design**: the hand-drawn `┌─│└` columns would not
  survive textual's Panel/border widgets literally — adopting it meant accepting a
  visual redesign as part of the deal.
- **no pain to fix**: the curses layer is ~270 lines, works, and has no reported
  friction. The textual gains (free scrolling/wrapping, widget-based click handling,
  pilot-testable interaction) are conveniences, not answers to a current problem.

Findings from the assessment, quoted (2026-09-13 session):

> Costs:
>
> 1. **Breaks "stdlib only"** — readme line 5 and the install requirements. The dep
>    (textual + rich + a few transitive) is view-only, but it's real: fresh-machine
>    install gains a `pip install` step.
> 2. **Import hygiene required** — `curses` is currently top-level (:25). textual must
>    be lazily imported inside the view path, or `note`/`serve`/`--once` on a machine
>    without the dep break. This is the one non-obvious design decision.
> 3. **API churn** — textual majors fast; pin a version floor.
> 4. **Startup ~0.5 s** vs instant curses. Negligible for a board you open and leave.
> 5. **The ASCII frame (`┌─│└`) won't survive literally** — you'd get Panels/borders
>    that look better but different. A visual refresh is part of the deal, not
>    optional.
>
> Recommendation:
>
> Worth it, scoped exactly like the sketch: textual replaces only the fullscreen view;
> `render_frame`/serve/`--once`/`note` stay stdlib. You lose ~270 lines of the most
> hand-rolled, least-tested code in the file and gain real scrolling, wrapping, and
> testable interaction — for one lazily-imported dep. If the ASCII column aesthetic
> matters more to you than the interaction gains, the current curses layer is doing
> its job fine and I'd leave it.

The final call followed the closing condition of that recommendation: the ASCII column
aesthetic and the stdlib-only invariant matter more here than the interaction gains.

Revisit if: a needed feature outgrows curses (rich text wrapping, robust resize,
interaction tests), the stdlib-only constraint is dropped, or the curses layer starts
accumulating bugs.