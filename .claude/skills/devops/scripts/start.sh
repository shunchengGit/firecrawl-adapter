#!/usr/bin/env bash
# 启动 SearXNG (Docker) + adapter (本地)
set -e
. "$(dirname "$0")/_env.sh"

# --- 前置检查 ---
echo "==> 检查环境"

# Docker
if ! docker info >/dev/null 2>&1; then
  if command -v colima >/dev/null 2>&1; then
    echo "    Docker 未运行，尝试 colima start..."
    colima start 2>&1 | tail -1
  else
    echo "    ✗ Docker 未运行且未安装 colima"
    echo "    安装: brew install docker colima && colima start"
    exit 1
  fi
fi
echo "    ✓ Docker"

# Python 依赖
if ! "$ADAPTER_PYTHON" -c "import requests" 2>/dev/null; then
  echo "    ✗ Python 缺少依赖，运行 setup.sh ..."
  "$(dirname "$0")/setup.sh"
fi
echo "    ✓ Python ($("$ADAPTER_PYTHON" --version 2>&1))"

# --- 启动 ---
echo
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
if curl -sf "http://127.0.0.1:${ADAPTER_PORT}/healthz" -o /dev/null 2>&1; then
  echo "    adapter 已在运行"
else
  nohup "$ADAPTER_PYTHON" -m adapter > /tmp/firecrawl-adapter.log 2>&1 &
  echo $! > /tmp/firecrawl-adapter.pid
  for i in $(seq 1 10); do
    if curl -sf "http://127.0.0.1:${ADAPTER_PORT}/healthz" -o /dev/null 2>&1; then
      echo "    adapter ready (pid $(cat /tmp/firecrawl-adapter.pid))"
      break
    fi
    if [ "$i" -eq 10 ]; then
      echo "    ✗ adapter 启动超时，日志: tail /tmp/firecrawl-adapter.log"
      exit 1
    fi
    sleep 1
  done
fi

echo
echo "==> 完成"
echo "    SearXNG:  http://127.0.0.1:${SEARXNG_PORT}"
echo "    adapter:  http://127.0.0.1:${ADAPTER_PORT}"
echo "    health:   $(curl -sf "http://127.0.0.1:${ADAPTER_PORT}/healthz")"
