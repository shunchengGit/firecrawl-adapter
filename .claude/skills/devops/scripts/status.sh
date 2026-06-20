#!/usr/bin/env bash
. "$(dirname "$0")/_env.sh"

echo "=== SearXNG (Docker, port ${SEARXNG_PORT}) ==="
if curl -sf "http://127.0.0.1:${SEARXNG_PORT}/" -o /dev/null 2>&1; then
  echo "  ✓ reachable"
else
  echo "  ✗ down"
fi
docker compose ps 2>/dev/null | tail -n +2 | sed 's/^/  /'

echo
echo "=== adapter (port ${ADAPTER_PORT}) ==="
if curl -sf "http://127.0.0.1:${ADAPTER_PORT}/healthz" 2>/dev/null; then
  echo "  ✓ healthy"
  [ -f /tmp/mockfirecrawl-adapter.pid ] && echo "  pid: $(cat /tmp/mockfirecrawl-adapter.pid)"
else
  echo "  ✗ down"
fi

echo
echo "=== agent-browser ==="
if command -v agent-browser >/dev/null 2>&1; then
  echo "  binary: $(command -v agent-browser)"
  echo "  session_name: ${AGENT_BROWSER_SESSION_NAME:-（未设，默认 default）}"
  if [ -d ~/.agent-browser/sessions ]; then
    echo "  saved sessions:"
    ls -1 ~/.agent-browser/sessions/ 2>/dev/null | sed 's/^/    /' || echo "    （无）"
  fi
else
  echo "  ✗ 未安装"
fi
