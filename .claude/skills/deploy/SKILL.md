---
name: deploy
description: 将 firecrawl-adapter 部署到 Hermes / Claude Code MCP，让外部 agent 走本地搜索。当用户提到"部署到 Hermes""部署到 Claude Code MCP""MCP 状态"等时使用。
cli_version: ">=1.0.0"
---

# deploy — 部署到外部 agent

让 Hermes 和 Claude Code 的搜索/抓取走本地 adapter。

## Hermes

```bash
.claude/skills/deploy/scripts/hermes-deploy.sh     # 配置 FIRECRAWL_API_URL
.claude/skills/deploy/scripts/hermes-status.sh      # 查看集成状态
.claude/skills/deploy/scripts/hermes-undeploy.sh    # 移除配置
```

在 `~/.hermes/.env` 写入 `FIRECRAWL_API_URL=http://127.0.0.1:3672`，Hermes 重启会话后生效。

## Claude Code MCP

```bash
.claude/skills/deploy/scripts/claude-mcp-install.sh            # 注册
.claude/skills/deploy/scripts/claude-mcp-status.sh             # 状态
.claude/skills/deploy/scripts/claude-mcp-uninstall.sh          # 移除
.claude/skills/deploy/scripts/claude-mcp-websearch-deny.sh      # 禁用内置搜索
.claude/skills/deploy/scripts/claude-mcp-websearch-allow.sh     # 恢复内置搜索
```

注册 `firecrawl-local` MCP 到 user scope（`~/.claude.json`），重启 Claude Code 会话后生效。

## 前置条件

SearXNG + adapter 必须在跑（`/devops start`）。
