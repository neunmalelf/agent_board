# Proposal — a "proper Python project" template: tests, hooks, and hardening tooling

Status: proposal, 2026-09-13. Written after restructuring `agent_board` into a
properly packaged project (PEP 621 `pyproject.toml`, src/ layout, helper
scripts, modular pre-commit hook — see `history.md`, entry
`2.3.20260913092333Z`) and researching how larger Python projects set up
their tooling. A prior draft exists as `proposal_gemini.md`; this document
supersedes it where they disagree and names the disagreements explicitly.

Scope: the setup template for future Python projects in this workspace
(`1_ddpico`-style toolset as the base), with emphasis on the two questions
asked: **which tests**, and **which tools beyond ruff and mypy** harden the
code, catch bugs, and keep it fast.

---

## 1. Baseline we just shipped (and reuse everywhere)

| Piece | Choice | Notes |
|---|---|---|
| Packaging | PEP 621 `pyproject.toml`, setuptools, src/ layout | stdlib-only `dependencies = []` where the tool allows it |
| Tests | pytest (`[tool.pytest.ini_options]`, `pythonpath = ["src"]`) | one runner everywhere; no unittest discovery split |
| Lint | ruff (E/F/I/UP/B/SIM, line-length 100) | single fast linter+formatter; matches pytest/pip/Home-Assistant |
| Types | mypy | keep as the base; see §4 for the second checker |
| Hooks | modular bash `hooks/pre-commit` (version, ruff, mypy, tests, drop-ins) + `hooks/install.sh` | 1_ddpico pattern; §6 compares with the pre-commit framework |
| Versioning | `Major.Minor.YYYYMMDDhhmmssZ` stamp, enforced by `_check_version` | unique to this workspace; see §7 |
| History | `history.md` release log (newest first) + `history/` archives | rules in `.agentrules` |
| Docs | README + MkDocs (Material) via `_docs` | matches textual/uv/pydantic docs stacks |

## 2. What big projects actually do (verified from their configs)

Findings from reading the real pre-commit configs, CI workflows, and
pyprojects of pytest, Django, Home Assistant, pip, and Textualize/textual
(2026-09; URLs in the source index):

- **One lint pipeline.** The pre-commit config in the repo root owns
  formatting/hygiene, and CI re-runs the same hooks (Home Assistant runs
  pre-commit via the Rust runner *prek* as a CI job; pip's nox lint session
  is just `pre-commit run`). Never maintain two different lint setups.
- **CI shape everywhere**: three OSes × supported Pythons, concurrency
  cancel, `permissions: read-only`, SHA-pinned third-party actions, and a
  final all-green aggregator job for branch protection.
- **Type checking in CI** is universal (mypy; pytest additionally runs
  pyright as a manual second checker).
- **Coverage is reported, not gated.** None of the five gates on a
  percentage. pytest collects branch coverage with
  `filterwarnings = ["error"]`; that warning-as-error mode — plus
  network-off in tests (Home Assistant: pytest-socket) — is the real
  hardening, not a coverage threshold.
- **Nobody runs mutation testing in CI.** mutmut/cosmic-ray are opt-in
  local/nightly tools even at CPython scale.
- **Release flow**: build the package once, install the built artifact in
  the test jobs (pytest does this via `build-and-inspect-python-package`).
- **Changelogs**: two of the five hand-write Keep-a-Changelog-style files
  (textual, uv); pip/pytest/attrs collect towncrier fragments per PR —
  worth it only with many contributors. CPython uses blurb, not towncrier
  (common claim is wrong).
- **Docs**: Sphinx for framework/API-autodoc projects (django, pip, attrs);
  MkDocs+Material for product/CLI projects (textual, uv, pydantic, ruff) —
  agent tools fit the MkDocs group.

What a single-maintainer project can skip without losing hardening value:
multi-DB/per-integration matrices, 10-way sharding, vendoring round-trips,
pyc-only installs, coverage fail-under, mutation gates, release-PR
automation.

## 3. Tests: the hardening ladder

Ordered by ROI for a project like `agent_board` (parser/serializer/state
logic, time-dependent chips, subprocess interaction):

1. **coverage.py + pytest-cov (day 0).** Branch coverage on; use it to find
   untested branches, not as a CI gate. `pytest-cov` is the thin wrapper.
2. **`filterwarnings = ["error"]` (day 0).** One line in
   `[tool.pytest.ini_options]`; turns silent deprecations into test
   failures. The cheapest real hardening the flagship projects use.
3. **hypothesis (week 2+).** Property-based tests with shrinking for the
   parsers and state machines: `parse_reset` (durations/ISO/seconds),
   `clean_title`, card merging, `age_str`/`dur_str` round-trips. Used by
   pytest itself, cryptography, PyPy, black; highest test ROI for
   input-munging code.
4. **pytest-randomly (one-line install).** Shuffles test order, reseeds
   random per test, reproducible via `--randomly-seed`; flushes hidden
   inter-test dependencies (the current suite shares module state via a
   module-level `mod`, so ordering dependencies are plausible).
5. **time-machine (when needed).** The board renders countdowns and ages —
   time-dependent tests want C-level time freezing (O(1), 100x+ faster
   than freezegun; same author as pytest-randomly).
6. **mutmut (occasionally, never a gate).** Mutation testing finds
   assertion-free tests: mutants survive where tests pass over broken
   code. mutmut v3 is parallel, incremental, coverage-aware; prefer it over
   cosmic-ray (heavier deps, clunkier). Run before releases, not per PR.
7. **pytest-xdist (when the suite slows).** Only adopt when needed; adds
   ordering caveats.

Explicit skip: **tox/nox** for now — single interpreter, stdlib-only
runtime; plain pytest is enough until a version matrix or doc builds
materialize (nox is the one to pick then; pip, Jupyter, urllib3 use it).

## 4. Static analysis beyond ruff + mypy

### Type checking, second opinion

| Tool | Verdict | Why |
|---|---|---|
| **basedpyright** | **adopt first** | pip-installable pyright fork (bundles Node), stricter defaults, **baseline files** let you adopt strictness incrementally on an existing mypy codebase; NumPy's type-completeness CI path; pandas runs pyright in pre-commit |
| **pyrefly** | adopt (alternative) | Meta's Rust checker, stable 1.0 (2026-05), best typing-spec conformance of the new generation; default at Instagram; `pyrefly init` migrates mypy config; adopted by PyTorch/JAX |
| ty (Astral) | watch, non-blocking | 10-60x faster, but beta (0.0.x, no stable API); Astral itself gates on it; run alongside, don't gate |
| pytype | skip | sunset/maintenance mode, last supported 3.12 |

Pick **one** of basedpyright/pyrefly as the second checker; keep mypy green
until the second checker passes CI. This catches real bugs mypy misses
(uninformed casts, impossible branches, incomplete type coverage).

### Security

| Tool | Verdict | Why |
|---|---|---|
| **bandit** | adopt | zero-config AST security linter (injection, weak crypto, hardcoded creds, `shell=True`); PyPA-ecosystem default; for agent_board, `subprocess.run`/`os.execve` call sites are exactly its target class |
| **pip-audit** | adopt (scheduled) | audits the dev/test environment against PyPI Advisory DB + OSV; supply-chain surface exists even with a stdlib runtime (pytest/ruff/mypy are deps); weekly CI job, skip in pre-commit (network) |
| **gitleaks** | adopt (pre-commit) | secret scanning for commits and history; offline, fast |
| **zizmor** | adopt when CI exists | audits GitHub Actions workflows (template injection, unpinned actions, permissions); used by CPython, curl, PyPI itself, Grafana across 2000+ repos; auto-fixes most findings |
| semgrep | skip | rule curation + registry noise; bandit covers the Python floor at this size |
| trufflehog | skip | gitleaks suffices for one maintainer; revisit after any real leak |

### Bugs, dead code, dependencies

| Tool | Verdict | Why |
|---|---|---|
| **vulture** | adopt as a manual pre-release sweep | dead flags/paths accumulate in CLIs (agent_board already has flag pairs worth auditing); whitelist file keeps it quiet |
| **deptry** | adopt the moment a real runtime dep appears | checks declared-vs-imported deps; with `dependencies = []` there is nothing to check today |
| pylint | skip | heavy overlap with ruff; its astroid inference edge is better served by pyrefly/basedpyright now |
| radon/xenon | skip as gates | run once if a module looks tangled (e.g. `run_tui` at ~155 lines is the candidate); not worth CI weight |

## 5. Hooks: bash modules vs the pre-commit framework

Current state (1_ddpico pattern, now in agent_board): a custom modular bash
hook — pros: zero deps, project scripts stay the single source of truth,
`SKIP_<MODULE>=1` granularity; cons: no pinned tool versions, no env
isolation, no autoupdate, not shareable across projects.

Research verdict (what pip/pytest/Home Assistant do, incl. JAX's evaluation
that stayed on pre-commit): adopt the **pre-commit framework** as the
canonical hook config, keep the project scripts for humans:

```yaml
# .pre-commit-config.yaml (sketch for the next project)
repos:
  - repo: https://github.com/pre-commit/pre-commit-hooks
    rev: v6.0.0
    hooks: [trailing-whitespace, end-of-file-fixer, check-toml, check-yaml, debug-statements]
  - repo: https://github.com/astral-sh/ruff-pre-commit
    rev: v0.16.5
    hooks: [ruff-check, ruff-format]
  - repo: local
    hooks:
      - id: check-version
        name: version stamps
        entry: ./_check_version
        language: system
        pass_filenames: false
```

Add **pre-commit.ci** (free for OSS) for PR auto-fix and weekly autoupdate
PRs; run `pre-commit run --all-files` in CI so the same pipeline gates PRs
(pip's autoupdate schedule + `ci.skip` for network tools like pip-audit).
Watch **prek** (Rust runner, CPython migrated to it) — switch only once it
is boring. The bash hook is not wasted: it remains the fast local gate and
the drop-in directory (`hooks/pre-commit.d/`) still takes project-specific
checks.

## 6. Performance tooling (on-demand, not installed by default)

| Tool | Use when |
|---|---|
| py-spy | attach to a running/hung process (`agent_board serve`, the TUI); flamegraphs, no code changes |
| pyinstrument | measured "why is this slow" runs with call-stack context, low overhead |
| pytest-benchmark | before/after numbers for render_frame/build_columns if they ever matter; mark bench tests, skip by default |
| scalene / memray / pyperf / codspeed | skip at this size — overlaps the above; tracemalloc covers occasional memory questions; codspeed only once continuous perf tracking is a stated goal |

## 7. Docs, changelog, versioning — future projects

- **Docs**: MkDocs + Material (+ mkdocstrings for API pages) for CLI/TUI
  tools; Sphinx only when docstrings-as-API-reference dominate (frameworks).
- **Changelog**: hand-written Keep-a-Changelog `history.md` (textual/uv
  precedent) — which is exactly the current convention, including
  decision entries with rejected alternatives (a habit worth keeping).
- **Versioning**: keep the workspace's `Major.Minor.<UTC stamp>Z` convention
  (it encodes release time and sorts), enforced by `_check_version`. If a
  project ever moves to tag-driven releases, setuptools-scm is the standard
  (pytest, attrs); static semver + `uv version --bump` is the low-ceremony
  ecosystem default for small CLIs.

## 8. Recommended adoption order (for agent_board and the next projects)

1. pytest-cov + branch coverage + `filterwarnings = ["error"]` (day 0)
2. pre-commit framework config + pre-commit.ci; ruff + hygiene hooks pinned (day 0)
3. bandit (pre-commit, high+medium) + gitleaks (day 0-1)
4. pip-audit weekly scheduled job (week 1)
5. basedpyright **or** pyrefly with a baseline file, alongside mypy (week 1-2)
6. hypothesis for parsers/state machines + pytest-randomly (week 2)
7. zizmor once GitHub Actions workflows exist (week 2)
8. On-demand: py-spy/pyinstrument, vulture sweeps, mutmut before releases, pytest-xdist

Minimal core = **7 tools**: coverage.py/pytest-cov, pre-commit (+pre-commit.ci),
bandit, pip-audit, basedpyright-or-pyrefly, hypothesis, zizmor. All
pip-installable, all low-config, none requiring servers or paid tiers.

## 9. Where this proposal disagrees with `proposal_gemini.md`

| Gemini proposal | This proposal | Reason |
|---|---|---|
| replace bash hooks with pre-commit framework | adopt pre-commit config, keep bash hook as fast local gate + drop-ins | the project scripts stay authoritative; CI parity via `pre-commit run --all-files` |
| semgrep for architecture rules | skip (bandit floor) | rule curation overhead, registry noise; revisit only for a genuine custom-rule need |
| scalene + memray as standard profiling | on-demand py-spy/pyinstrument first | scalene/memray overlap them; tracemalloc covers memory at this size |
| radon/xenon complexity gate in hooks | skip as gates; audit manually | thresholds in CI create noise without catching the bugs that matter here |
| uv + nox as defaults | defer both | stdlib-only, single-env projects don't need env matrices; uv is fine for `_docs` (already used) and worth adopting for dependency management when a dep appears |
| mutmut "ultimate test" | keep, but local/nightly only | no flagship project gates PRs on mutation scores |

## Source index (primary evidence)

- pytest: `.pre-commit-config.yaml`, `.github/workflows/test.yml`, `pyproject.toml` (github.com/pytest-dev/pytest)
- Django: `.pre-commit-config.yaml`, `docs.yml` (-W + spelling), workflow set (github.com/django/django)
- Home Assistant: `.pre-commit-config.yaml` (zizmor --pedantic, prek), `ci.yaml` (github.com/home-assistant/core)
- pip: `.pre-commit-config.yaml` (towncrier hook), `ci.yml` (nox sessions), `noxfile.py` (github.com/pypa/pip)
- textual: `.pre-commit-config.yaml`, `CHANGELOG.md` (Keep a Changelog), mkdocs stack (github.com/Textualize/textual)
- NumPy type-completeness: numpy/numpy#29065; pandas pyright hook: pandas-dev/pandas#43747; polars: pola-rs/polars#22965
- pyrefly 1.0: github.com/facebook/pyrefly (2026-05-12); ty beta: astral.sh/blog/ty; pytype sunset: github.com/google/pytype
- zizmor adoption: grafana.com blog (2025-06), pypa/pip-audit#851, pytest-dev/pytest-print#217
- time-machine vs freezegun: adamj.eu/tech/2026/08/03/python-time-machine-o1-freezegun-on
- CPython prek migration: python/cpython#143148/#143149; JAX hook decision: jax-ml/jax#32846
- codspeed adopters: codspeed.io (Astral, pydantic), pola-rs/polars#15537