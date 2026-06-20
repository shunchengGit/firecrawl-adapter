#!/usr/bin/env bash
# 从 Claude Code user scope 移除 firecrawl-local MCP server
set -e
. "$(dirname "$0")/_env.sh"

echo "==> 移除 firecrawl-local MCP (user scope)"
claude mcp remove firecrawl-local -s user
echo "==> 完成"
