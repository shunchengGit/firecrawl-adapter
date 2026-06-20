#!/usr/bin/env bash
. "$(dirname "$0")/_env.sh"

if [ "$1" = "--fix" ]; then
  ${ADAPTER_PYTHON} -m ruff check --fix adapter/ tests/
else
  ${ADAPTER_PYTHON} -m ruff check adapter/ tests/
fi
