#!/usr/bin/env bash
. "$(dirname "$0")/_env.sh"

${ADAPTER_PYTHON} -m mypy adapter/
