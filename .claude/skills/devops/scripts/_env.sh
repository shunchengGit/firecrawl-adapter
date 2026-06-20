#!/usr/bin/env bash
# 公共环境加载器：source 后可用 $ADAPTER_PORT、$SEARXNG_PORT 等
# 项目根 = 脚本所在目录的上四级
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"
cd "$PROJECT_ROOT" || exit 1

# 加载 .env
if [ -f .env ]; then
  set -a; . ./.env; set +a
elif [ -f .env.example ]; then
  echo "  ⚠ .env 不存在，从 .env.example 复制" >&2
  cp .env.example .env
  set -a; . ./.env; set +a
fi

# 默认值
: "${SEARXNG_PORT:=3671}"
: "${ADAPTER_HOST:=127.0.0.1}"
: "${ADAPTER_PORT:=3672}"
: "${SEARXNG_BASE:=http://127.0.0.1:${SEARXNG_PORT}}"
: "${AGENT_BROWSER_SESSION_NAME:=firecrawl-adapter}"

# Python 探测：venv > homebrew python3.13/3.12/3.11 > ADAPTER_PYTHON > python3
_find_python() {
  # 1. 项目 venv
  if [ -x "$PROJECT_ROOT/.venv/bin/python" ]; then
    echo "$PROJECT_ROOT/.venv/bin/python"
    return
  fi
  # 2. homebrew 新版 Python
  for v in 3.13 3.12 3.11; do
    if [ -x "/opt/homebrew/bin/python$v" ]; then
      echo "/opt/homebrew/bin/python$v"
      return
    fi
  done
  # 3. 显式配置的 ADAPTER_PYTHON
  if [ -n "${ADAPTER_PYTHON:-}" ] && [ -x "$ADAPTER_PYTHON" ]; then
    echo "$ADAPTER_PYTHON"
    return
  fi
  # 4. 系统 python3
  echo "python3"
}

ADAPTER_PYTHON="$(_find_python)"

# 快速验证 Python 能否 import 核心依赖（静默，仅 venv 缺失时提示）
_check_deps() {
  if ! "$ADAPTER_PYTHON" -c "import requests, bs4" 2>/dev/null; then
    echo "  ✗ Python ($ADAPTER_PYTHON) 缺少依赖，请运行: .claude/skills/devops/scripts/setup.sh" >&2
    return 1
  fi
}

export SEARXNG_PORT ADAPTER_HOST ADAPTER_PORT SEARXNG_BASE AGENT_BROWSER_SESSION_NAME ADAPTER_PYTHON PROJECT_ROOT
