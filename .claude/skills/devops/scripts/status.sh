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
# agent-browser 可能装在 nvm 的非默认 node 版本下，当前 PATH 找不到时去 nvm 目录兜底找
_ab_bin=""
if command -v agent-browser >/dev/null 2>&1; then
  _ab_bin="$(command -v agent-browser)"
else
  for _c in ~/.nvm/versions/node/*/bin/agent-browser; do
    [ -x "$_c" ] && _ab_bin="$_c" && break
  done
fi

echo "=== agent-browser ==="
if [ -n "$_ab_bin" ]; then
  echo "  binary: $_ab_bin"
  if [ "$(dirname "$_ab_bin")" != "$(dirname "$(command -v agent-browser 2>/dev/null)")" ] 2>/dev/null; then
    echo "  ⚠ 不在当前 PATH（位于 nvm node 版本目录），对 shell 不可见；adapter 如从含该 PATH 的环境启动则仍可用"
  fi
  echo "  SESSION_NAME: ${AGENT_BROWSER_SESSION_NAME:-（未设）}"
  if [ -f ~/.agent-browser/config.json ]; then
    echo "  config: $(cat ~/.agent-browser/config.json)"
  fi
  if [ -d ~/.agent-browser/sessions ]; then
    total=$(ls ~/.agent-browser/sessions/*.json 2>/dev/null | wc -l | tr -d ' ')
    echo "  state 文件: 共 $total 个"
    for f in $(ls -t ~/.agent-browser/sessions/*.json 2>/dev/null | head -5); do
      [ -e "$f" ] || continue
      cookies=$(python3 -c "import json;d=json.load(open('$f'));print(len(d.get('cookies',[])))" 2>/dev/null || echo "?")
      echo "    $(basename "$f") ($cookies cookies)"
    done
    [ "$total" -gt 5 ] 2>/dev/null && echo "    （仅显示最近 5 个）"
  fi
else
  echo "  ✗ 未安装"
fi

exit 0
