#!/usr/bin/env bash
# 停止 adapter + SearXNG（不关 agent-browser daemon）
. "$(dirname "$0")/_env.sh"

echo "==> 停止 adapter"
if [ -f /tmp/firecrawl-adapter.pid ]; then
  PID=$(cat /tmp/firecrawl-adapter.pid)
  if kill -0 "$PID" 2>/dev/null; then
    kill "$PID" && echo "    killed pid $PID"
  else
    echo "    pid $PID 已不存在"
  fi
  rm -f /tmp/firecrawl-adapter.pid
fi
pkill -f "python.*-m adapter" 2>/dev/null && echo "    pkill 兜底清理" || true

echo "==> 停止 SearXNG + Redis (Docker)"
docker compose down

echo "==> 完成（agent-browser daemon 未受影响）"
