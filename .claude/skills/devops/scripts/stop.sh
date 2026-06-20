#!/usr/bin/env bash
. "$(dirname "$0")/_env.sh"

echo "==> 停止 adapter"
if [ -f /tmp/mockfirecrawl-adapter.pid ]; then
  PID=$(cat /tmp/mockfirecrawl-adapter.pid)
  if kill -0 "$PID" 2>/dev/null; then
    kill "$PID" && echo "    killed pid $PID"
  else
    echo "    pid $PID 已不存在"
  fi
  rm -f /tmp/mockfirecrawl-adapter.pid
fi
# 兜底：按命令名杀
pkill -f "python3 -m adapter" 2>/dev/null && echo "    pkill 兜底清理" || true

echo "==> 停止 agent-browser daemon"
agent-browser close --all 2>/dev/null && echo "    browser daemon closed" || true

echo "==> 停止 SearXNG + Redis (Docker)"
docker compose down
echo "==> 完成"
