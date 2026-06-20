#!/usr/bin/env bash
# 用 headed（有界面）浏览器打开 URL，人工登录，cookie 自动存到 AGENT_BROWSER_SESSION_NAME session
# 用法: login.sh <url>
set -e
. "$(dirname "$0")/_env.sh"

URL="$1"
if [ -z "$URL" ]; then
  echo "用法: $0 <url>"
  echo "示例: $0 https://example.com/login"
  exit 1
fi

if ! command -v agent-browser >/dev/null 2>&1; then
  echo "✗ 未安装 agent-browser，先跑: .claude/skills/devops/scripts/setup.sh"
  exit 1
fi

SESSION="${AGENT_BROWSER_SESSION_NAME:-default}"

# 若 daemon 已在跑（可能 headless），先关掉，否则 --headed 会被忽略
agent-browser close --all 2>/dev/null || true

echo "==> 用 headed 浏览器打开: $URL"
echo "    session: $SESSION"
echo "    请在弹出的浏览器窗口里完成登录"
echo "    登录完成后回到这里按回车，会关闭浏览器并保存 cookie"
echo

agent-browser --headed open "$URL"

read -r -p "登录完成？按回车关闭浏览器并保存 cookie..."
echo
agent-browser close --all
echo
echo "==> cookie 已保存到 ~/.agent-browser/sessions/${SESSION}-default.json"
echo "    之后 adapter 抓取会自动复用登录态（headless 模式）"
echo "    查看已存 cookie: .claude/skills/devops/scripts/session-show.sh"
