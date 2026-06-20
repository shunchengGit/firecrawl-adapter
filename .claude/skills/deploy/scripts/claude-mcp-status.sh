#!/usr/bin/env bash
# 查看 firecrawl-local MCP server 状态 + 内置 WebSearch 是否被禁用
. "$(dirname "$0")/_env.sh"

echo "=== MCP server: firecrawl-local ==="
claude mcp get firecrawl-local 2>&1 || echo "  ✗ 未注册（跑 claude-mcp-install.sh）"

echo
echo "=== 连接健康检查 ==="
claude mcp list 2>&1 | grep -E "firecrawl-local" || echo "  ✗ 未连接"

echo
echo "=== 内置 WebSearch 禁用状态 ==="
SETTINGS=~/.claude/settings.json
if [ -f "$SETTINGS" ]; then
  if python3 -c "import json,sys; d=json.load(open('$SETTINGS')); sys.exit(0 if 'WebSearch' in d.get('permissions',{}).get('deny',[]) else 1)" 2>/dev/null; then
    echo "  ✓ 已禁用（permissions.deny 含 WebSearch）"
    echo "    模型只能用 MCP firecrawl 工具搜索"
  else
    echo "  ⚠ 未禁用，模型仍可用内置 WebSearch"
    echo "    若要强制走本地: claude-mcp-websearch-deny.sh"
  fi
else
  echo "  ✗ 无 $SETTINGS"
fi
