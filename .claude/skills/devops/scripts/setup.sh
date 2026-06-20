#!/usr/bin/env bash
# 一键安装依赖 + 配置环境变量。可重复运行（幂等）。
# 检查项：Docker、Python 依赖、agent-browser、.env、~/.zshrc 的 AGENT_BROWSER_SESSION_NAME
set -e
. "$(dirname "$0")/_env.sh"

echo "=== 1/6 检查 Docker ==="
if command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1; then
  echo "  ✓ Docker $(docker --version | awk '{print $3}' | tr -d ,) 已运行"
else
  echo "  ✗ Docker 未安装或未运行"
  echo "    安装: brew install --cask docker  或从 https://docker.com 下载"
  echo "    安装后启动 Docker Desktop 再重跑本脚本"
  exit 1
fi

echo
echo "=== 2/6 检查 Python (需要 3.10+) ==="
# 优先找 3.10+ 的 Python，避免系统自带的 3.9
PY_BIN=""
for candidate in python3.13 python3.12 python3.11 python3.10 python3.14 python3; do
  if command -v "$candidate" >/dev/null 2>&1; then
    VER=$($candidate -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")' 2>/dev/null || echo "0.0")
    MAJOR=${VER%%.*}
    MINOR=${VER#*.}
    if [ "$MAJOR" -gt 3 ] || { [ "$MAJOR" -eq 3 ] && [ "$MINOR" -ge 10 ]; }; then
      PY_BIN=$(command -v "$candidate")
      echo "  ✓ $PY_BIN (Python $VER)"
      break
    fi
  fi
done
if [ -z "$PY_BIN" ]; then
  echo "  ✗ 未找到 Python 3.10+"
  echo "    系统 Python 是 3.9，但 pyproject.toml 要求 3.10+"
  echo "    安装: brew install python@3.13"
  exit 1
fi

echo
echo "=== 3/6 创建 venv + 安装依赖 ==="
VENV="$PROJECT_ROOT/.venv"
if [ ! -d "$VENV" ]; then
  echo "  → 创建 venv: $VENV"
  "$PY_BIN" -m venv "$VENV"
fi
VENV_PY="$VENV/bin/python"
echo "  ✓ venv Python: $($VENV_PY --version)"

# 升级 pip 再装依赖
$VENV_PY -m pip install -q --upgrade pip
if $VENV_PY -m pip install -q -e ".[dev]" 2>&1 | tail -3; then
  echo "  ✓ 依赖安装完成（含 pytest/ruff/mypy）"
else
  echo "  ⚠ editable 安装失败，回退到直接装运行时依赖"
  $VENV_PY -m pip install -q requests beautifulsoup4 html2text lxml python-dotenv
fi
$VENV_PY -c "import requests, bs4, html2text, lxml, dotenv; print('  ✓ 运行时依赖齐全')" 2>&1

echo
echo "=== 4/6 检查 Node.js + agent-browser ==="
if ! command -v node >/dev/null 2>&1; then
  echo "  ✗ 未找到 node（agent-browser 需要 Node.js 22+）"
  echo "    安装: brew install node  或用 nvm"
  exit 1
fi
echo "  ✓ node $(node --version)"

if ! command -v agent-browser >/dev/null 2>&1; then
  echo "  → 安装 agent-browser"
  npm install -g agent-browser
fi
echo "  ✓ agent-browser $(agent-browser --version 2>&1 | head -1)"

# 检查 Chrome for Testing 是否已下载（agent-browser install 的产物）
if ! agent-browser --help >/dev/null 2>&1; then
  echo "  → 下载 Chrome for Testing（首次较慢）"
  agent-browser install || echo "    ⚠ 下载失败，可后续手动 agent-browser install；本地若有 Chrome 也会被自动检测"
fi

echo
echo "=== 5/6 配置 .env ==="
if [ ! -f .env ]; then
  cp .env.example .env
  echo "  → 从 .env.example 创建 .env"
else
  echo "  ✓ .env 已存在"
fi
echo "    当前配置:"
grep -v '^#' .env | grep -v '^$' | sed 's/^/      /'

echo
echo "=== 6/6 配置 ~/.zshrc 的 AGENT_BROWSER_SESSION_NAME ==="
ZSHRC="${ZDOTDIR:-$HOME}/.zshrc"
if grep -q "AGENT_BROWSER_SESSION_NAME" "$ZSHRC" 2>/dev/null; then
  echo "  ✓ ~/.zshrc 已配置:"
  grep "AGENT_BROWSER_SESSION_NAME" "$ZSHRC" | sed 's/^/    /'
else
  echo "  → 写入 ~/.zshrc"
  echo '' >> "$ZSHRC"
  echo '# agent-browser 默认 session（firecrawl-adapter）' >> "$ZSHRC"
  echo 'export AGENT_BROWSER_SESSION_NAME=firecrawl-adapter' >> "$ZSHRC"
  echo "  ✓ 已添加，新终端生效；当前终端运行: source ~/.zshrc"
fi

echo
echo "=== 完成 ==="
echo "  下一步: .claude/skills/devops/scripts/start.sh"
