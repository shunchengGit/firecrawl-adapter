#!/usr/bin/env bash
. "$(dirname "$0")/_env.sh"

if [ -n "$1" ]; then
  ${ADAPTER_PYTHON} -m pytest "$1" -v
else
  ${ADAPTER_PYTHON} -m pytest -q
fi
