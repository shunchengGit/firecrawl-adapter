#!/usr/bin/env bash
. "$(dirname "$0")/_env.sh"

SESSION="${AGENT_BROWSER_SESSION_NAME:-default}"
echo "==> 关闭 agent-browser daemon"
agent-browser close --all 2>/dev/null || true

echo "==> 清空 session state ($SESSION)"
if [ -d ~/.agent-browser/sessions ]; then
  rm -f ~/.agent-browser/sessions/${SESSION}-default.json
  echo "    已删除 ${SESSION}-default.json"
else
  echo "    无 sessions 目录"
fi
echo "==> 完成（所有登录态已清除）"
