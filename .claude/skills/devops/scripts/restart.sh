#!/usr/bin/env bash
. "$(dirname "$0")/_env.sh"

echo "==> 重启 adapter"
if [ -f /tmp/mockfirecrawl-adapter.pid ]; then
  PID=$(cat /tmp/mockfirecrawl-adapter.pid)
  kill "$PID" 2>/dev/null && echo "    killed pid $PID"
  rm -f /tmp/mockfirecrawl-adapter.pid
fi
pkill -f "${ADAPTER_PYTHON} -m adapter" 2>/dev/null || true
sleep 1

nohup ${ADAPTER_PYTHON} -m adapter > /tmp/mockfirecrawl-adapter.log 2>&1 &
echo $! > /tmp/mockfirecrawl-adapter.pid
for i in $(seq 1 10); do
  if curl -sf "http://127.0.0.1:${ADAPTER_PORT}/healthz" -o /dev/null 2>&1; then
    echo "    adapter ready (pid $(cat /tmp/mockfirecrawl-adapter.pid))"
    exit 0
  fi
  sleep 1
done
echo "    ✗ adapter 启动超时，看日志: $0 logs adapter"
exit 1
