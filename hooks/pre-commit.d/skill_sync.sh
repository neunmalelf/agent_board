#!/usr/bin/env bash
# skill_sync.sh - pre-commit drop-in: verify the AGENTS.md skill index is in
# sync with .agents/skills/. Fails the commit when stale; regenerate with
# `./_skill_sync`. Skip with SKIP_SKILL_SYNC=1.

__VERSION__="1.0.20260906172413Z"

set -u
set -o pipefail

if [[ "${SKIP_SKILL_SYNC:-0}" == "1" ]]; then
    echo "skill_sync: skipped via SKIP_SKILL_SYNC=1"
    exit 0
fi

ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
SYNC_SCRIPT="$ROOT/_skill_sync"

if [[ ! -x "$SYNC_SCRIPT" ]]; then
    echo "skill_sync: $SYNC_SCRIPT not found or not executable - SKIPPED" >&2
    exit 0
fi

"$SYNC_SCRIPT" --check
