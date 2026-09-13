# Proposal: Modern Python Project Setup & Hardening

Based on an analysis of the current `ddpico` project and industry best practices for large-scale, enterprise-grade Python applications in 2024/2025, this document proposes a blueprint for a "proper Python project" setup. 

While `ddpico` already establishes a solid foundation (using `pyproject.toml`, `pytest`, `ruff`, and `mypy`), the modern Python ecosystem offers advanced tools to further harden the code, prevent regressions, enforce architecture, and optimize performance.

---

## 1. Pre-commit Framework (Replacing Custom Hooks)

Currently, `ddpico` uses custom bash scripts in `hooks/`. Larger projects have almost universally migrated to the [pre-commit](https://pre-commit.com/) framework.

*   **How it works**: Managed via a single `.pre-commit-config.yaml` file in the root.
*   **Why**: It automatically handles the installation, isolation (in virtualenvs), and execution of formatting/linting tools before every commit. It is OS-agnostic and prevents "it works on my machine" issues.
*   **Features**: You can run `ruff`, `mypy`, trailing whitespace fixers, and security scanners simultaneously without manual script maintenance. It also features an `autoupdate` command to keep tool versions current.

---

## 2. Code Hardening & Security

Beyond `ruff` (for linting/formatting) and `mypy` (for type checking), you need specialized tools to detect logical flaws, security vulnerabilities, and architectural drift.

*   **Bandit**: A security linter specifically for Python. It scans the AST (Abstract Syntax Tree) to find common security issues like hardcoded passwords, unsafe `eval()` or `exec()` usage, weak cryptography, and unsafe `subprocess` shell calls (highly relevant for a tool like `ddpico`).
*   **Semgrep**: A deeply semantic static analysis tool. Unlike regex-based linters, Semgrep understands code flow. You can write custom rules to enforce project-specific architectural patterns (e.g., "all functions in this module must return this specific type" or "never call this internal function directly").
*   **pip-audit** / **OSV-Scanner**: Tools that scan your dependency tree (even optional ones) against vulnerability databases (CVEs). They can be integrated into CI/CD to block PRs that introduce vulnerable packages.
*   **Deptry**: Analyzes your codebase to ensure your `pyproject.toml` is accurate. It flags unused dependencies, missing dependencies (where you import something but forgot to declare it), and transitive dependency misuse.

---

## 3. Advanced Testing Methodologies

Unit tests (via `pytest`) are standard, but to truly bulletproof a toolset, you should employ advanced testing strategies:

*   **Hypothesis (Property-Based Testing)**: Instead of writing fixed inputs (e.g., `test_slugify("Hello World")`), Hypothesis generates hundreds of edge-case inputs (massive strings, unexpected unicode, weird combinations) to bombard your functions. If `ddpico.string` or `ddpico.general` fails on bizarre inputs, Hypothesis will find it.
*   **Mutmut (Mutation Testing)**: This is the ultimate test of your test suite. Mutmut systematically alters your source code slightly (e.g., changes an `if a > b:` to `if a >= b:`) and runs your tests. If your tests *pass* despite the broken code, you have a "surviving mutant"—meaning your tests aren't actually asserting the behavior properly.
*   **pytest-xdist**: A plugin for `pytest` that runs your test suite in parallel across all CPU cores, drastically reducing CI pipeline times as the test suite grows.

---

## 4. Performance Optimization & Profiling

To ensure the CLI tools, daemons, and LSP server remain blazing fast, proactive profiling tools are necessary.

*   **Scalene**: A high-performance CPU, GPU, and memory profiler. It doesn't just tell you *what* function is slow; it tells you exactly *which lines* of Python code or C extensions are consuming time, and differentiates between Python time and system time.
*   **Memray**: Developed by Bloomberg, this is the premier memory profiler for Python. It tracks every single memory allocation (even in C extensions). It is critical for long-running processes (like `ddpico_lsp`) to detect memory leaks over time.
*   **Py-spy**: A sampling profiler that can attach to a *currently running* Python process without modifying the code or stopping it. Perfect for debugging a background task or process that has hung unexpectedly.

---

## 5. Architecture, Complexity, & Typing

*   **Radon / Xenon**: Tools that calculate the Cyclomatic Complexity and Maintainability Index of your code. You can integrate `xenon` into your hooks to automatically reject code (fail the build) if a function becomes too complex (e.g., too many nested `if/for` loops), forcing developers to refactor early.
*   **Pyright / Basedpyright**: While `mypy` is excellent, `pyright` (built by Microsoft) is often significantly faster and stricter. `basedpyright` is a fork that adds even more rigorous type-checking rules. Using it alongside (or instead of) `mypy` often uncovers edge-case type violations.

---

## 6. Modern Packaging & Execution

*   **uv**: Written in Rust by Astral (the makers of Ruff), `uv` is the modern standard replacing `pip`, `poetry`, and `pip-tools`. It is orders of magnitude faster for resolving and installing dependencies, managing lockfiles (`uv.lock`), and executing tools in isolated environments (`uvx`).
*   **nox**: Replaces `tox` for test matrix automation. It allows you to define testing environments (e.g., test against Python 3.10, 3.11, 3.12, 3.13) using standard Python configuration files rather than INI files, making it highly programmable.

---

## 7. Documentation Automation

*   **mkdocstrings**: `ddpico` already enforces a strict docstring format (via `skill_docstring_format`) and uses MkDocs. By adding the `mkdocstrings` plugin, you can automatically generate beautiful, searchable API documentation websites directly from your Python source code. When the docstring updates, the website updates automatically.

## Summary Checklist for the "Proper" Project Setup

1. [ ] **`uv`** for dependency resolution and virtual environments.
2. [ ] **`.pre-commit-config.yaml`** replacing custom bash hooks.
3. [ ] **`ruff`** (Linting/Formatting) + **`basedpyright`** (Strict Typing).
4. [ ] **`bandit`** + **`semgrep`** for security and architectural static analysis.
5. [ ] **`pytest`** + **`hypothesis`** (Property tests) + **`mutmut`** (Mutation tests).
6. [ ] **`scalene`** + **`memray`** for continuous performance profiling.
7. [ ] **`radon`** (Complexity gating) integrated into CI.
8. [ ] **`mkdocs-material`** + **`mkdocstrings`** for automated API docs.
