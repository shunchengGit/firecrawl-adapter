#!/usr/bin/env bash
set -e
. "$(dirname "$0")/_env.sh"

echo "==> pytest"
${ADAPTER_PYTHON} -m pytest -q
echo
echo "==> ruff check"
${ADAPTER_PYTHON} -m ruff check adapter/ tests/
echo
echo "==> mypy"
${ADAPTER_PYTHON} -m mypy adapter/
echo
echo "✓ 全部通过"
