#!/usr/bin/env bash
# 用 headed 浏览器打开 URL，人工登录。cookie 通过 AGENT_BROWSER_SESSION_NAME
# 自动链式传递给后续所有 session（Hermes / adapter）。
# 用法: browser-login.sh <url>
set -e
. "$(dirname "$0")/_env.sh"

SESSION="firecrawl-adapter"

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

# 若自己的 daemon 已在跑（可能 headless），先关掉
agent-browser --session "$SESSION" close 2>/dev/null || true

echo "==> 用 headed 浏览器打开: $URL"
echo "    请在弹出的浏览器窗口里完成登录"
echo "    登录完成后回到这里按回车，会关闭浏览器并保存 cookie"
echo

agent-browser --session "$SESSION" --headed open "$URL"

read -r -p "登录完成？按回车关闭浏览器并保存 cookie..."
echo
agent-browser --session "$SESSION" close
echo
echo "==> cookie 已保存（agent-browser 链式传递到后续 session）"
echo "    查看已存 cookie: .claude/skills/devops/scripts/browser-session-show.sh"
