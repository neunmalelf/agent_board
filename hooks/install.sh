#!/usr/bin/env bash
# Install hooks/pre-commit into .git/hooks/pre-commit (copied, not
# symlinked, so it works on Windows without developer-mode symlinks).
# Run from anywhere inside the repo:  bash hooks/install.sh

__VERSION__="1.3.20260909162500Z"

set -euo pipefail

# Resolve the repo root (this script lives in <root>/hooks/).
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

cp "$ROOT/hooks/pre-commit" "$ROOT/.git/hooks/pre-commit"
chmod +x "$ROOT/.git/hooks/pre-commit"

echo "Installed pre-commit hook ($ROOT/.git/hooks/pre-commit)."
echo "Modular hook supporting: version, ruff, mypy, tests, and build check modules."
echo "Re-run 'bash hooks/install.sh' after editing hooks/pre-commit."
