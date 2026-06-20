#!/usr/bin/env bash
# 公共环境加载器：source 本文件后即可用 $ADAPTER_PORT、$SEARXNG_PORT 等
# 项目根 = 脚本所在目录的上四级（scripts/ -> devops/ -> skills/ -> .claude/ -> 项目根）
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"
cd "$PROJECT_ROOT" || exit 1

# 加载 .env（若存在）
if [ -f .env ]; then
  set -a
  # shellcheck disable=SC1091
  . ./.env
  set +a
fi

# 默认值（与 adapter/config.py、docker-compose.yml、~/.zshrc 保持一致）
: "${SEARXNG_PORT:=3671}"
: "${ADAPTER_HOST:=127.0.0.1}"
: "${ADAPTER_PORT:=3672}"
: "${SEARXNG_BASE:=http://127.0.0.1:${SEARXNG_PORT}}"
: "${AGENT_BROWSER_SESSION_NAME:=firecrawl-adapter}"
# 优先用项目 venv（setup.sh 创建），否则回退到 .env 的 ADAPTER_PYTHON 或 python3
if [ -x "$PROJECT_ROOT/.venv/bin/python" ]; then
  ADAPTER_PYTHON="$PROJECT_ROOT/.venv/bin/python"
elif [ -z "${ADAPTER_PYTHON:-}" ]; then
  ADAPTER_PYTHON="python3"
fi
export SEARXNG_PORT ADAPTER_HOST ADAPTER_PORT SEARXNG_BASE AGENT_BROWSER_SESSION_NAME ADAPTER_PYTHON PROJECT_ROOT
