#!/usr/bin/env bash
set -e
. "$(dirname "$0")/_env.sh"

echo "==> 启动 SearXNG + Redis (Docker)"
docker compose up -d

echo "==> 等待 SearXNG 就绪 (port ${SEARXNG_PORT})"
for i in $(seq 1 15); do
  if curl -sf "http://127.0.0.1:${SEARXNG_PORT}/" -o /dev/null; then
    echo "    SearXNG ready"
    break
  fi
  sleep 1
done

echo "==> 启动 adapter (port ${ADAPTER_PORT})"
# 若已在跑，先停
if curl -sf "http://127.0.0.1:${ADAPTER_PORT}/healthz" -o /dev/null 2>&1; then
  echo "    adapter 已在运行，跳过"
else
  nohup ${ADAPTER_PYTHON} -m adapter > /tmp/firecrawl-adapter.log 2>&1 &
  echo $! > /tmp/firecrawl-adapter.pid
  for i in $(seq 1 10); do
    if curl -sf "http://127.0.0.1:${ADAPTER_PORT}/healthz" -o /dev/null 2>&1; then
      echo "    adapter ready (pid $(cat /tmp/firecrawl-adapter.pid))"
      break
    fi
    sleep 1
  done
fi

echo "==> 完成"
echo "    SearXNG:  http://127.0.0.1:${SEARXNG_PORT}"
echo "    adapter:  http://127.0.0.1:${ADAPTER_PORT}"
