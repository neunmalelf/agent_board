<!-- __version__: 1.0.20260913092333Z -->

# AGENTS.md

Entry file for AI coding agents working in this repository.

See `.agentrules` for the project rules (stdlib-only runtime, src/ layout,
version stamping, commit-before-changes, tests-before-commit, history
handling, docstring style, LF line endings).

## Checks

```sh
./_tests        # pytest + ruff + mypy — must pass before every commit
./_check_version
```

The git pre-commit hook (`hooks/install.sh`) enforces the same checks.

## Project Skills

| Skill | Description | Load |
|---|---|---|
| `agent-board` | Teaches agents to post to the board: register at task start, post each step (esp. per todo item), update on change, done at end, input/quota when blocked. | always |
| `python_comment_style` | Enforces the strict docstring/function-header format (typed signature, usage/returns/errors lines, Google-style Args, executable example) on every created or changed Python function. | always |

Skills live in `skills/`. The `agent-board` skill is also installed globally
to `~/.agents/skills/agent-board` for agent-side posting (see README).