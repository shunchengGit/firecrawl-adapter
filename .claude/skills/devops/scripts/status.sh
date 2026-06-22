#!/usr/bin/env bash
# 查看 SearXNG / adapter / agent-browser 状态
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
  [ -f /tmp/firecrawl-adapter.pid ] && echo "  pid: $(cat /tmp/firecrawl-adapter.pid)"
else
  echo "  ✗ down"
fi

echo
echo "=== agent-browser ==="
if command -v agent-browser >/dev/null 2>&1; then
  echo "  binary: $(command -v agent-browser)"
  echo "  SESSION_NAME: ${AGENT_BROWSER_SESSION_NAME:-（未设）}"
  if [ -f ~/.agent-browser/config.json ]; then
    echo "  config: $(cat ~/.agent-browser/config.json)"
  fi
  if [ -d ~/.agent-browser/sessions ]; then
    echo "  state 文件:"
    ls -1 ~/.agent-browser/sessions/*.json 2>/dev/null | while read f; do
      cookies=$(python3 -c "import json;d=json.load(open('$f'));print(len(d.get('cookies',[])))" 2>/dev/null || echo "?")
      echo "    $(basename "$f") ($cookies cookies)"
    done
    if [ "$(ls ~/.agent-browser/sessions/*.json 2>/dev/null | wc -l)" -eq 0 ]; then echo "    （无）"; fi
  fi
else
  echo "  ✗ 未安装"
fi
