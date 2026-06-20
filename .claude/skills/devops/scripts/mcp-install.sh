#!/usr/bin/env bash
# 注册 firecrawl-local MCP server 到 Claude Code user scope（全局，所有项目可用）
# 指向本地 adapter，让 Claude Code 的搜索/抓取走本地 Firecrawl
set -e
. "$(dirname "$0")/_env.sh"

echo "==> 注册 firecrawl-local MCP (user scope)"
claude mcp add firecrawl-local -s user \
  -e "FIRECRAWL_API_URL=http://127.0.0.1:${ADAPTER_PORT}" \
  -e "FIRECRAWL_API_KEY=local" \
  -- npx -y firecrawl-mcp

echo
echo "==> 验证连接"
claude mcp list 2>&1 | grep -E "firecrawl-local|Connected" || true
echo
echo "==> 完成"
echo "    重启 Claude Code 会话后生效"
echo "    模型会多出 firecrawl_search / firecrawl_scrape 等工具"
