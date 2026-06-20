---
name: devops
description: MockFirecrawl 项目的研发运维工具集。用于启停 SearXNG/adapter 服务、查看状态与日志、运行测试与检查、管理 agent-browser 登录态、重配端口等日常 devops 操作。当用户提到"启动/停止服务""看日志""跑测试""检查健康""登录站点注入 cookie""改端口"等本项目的运维需求时使用。
cli_version: ">=1.0.0"
---

# MockFirecrawl DevOps Skill

本 skill 封装 MockFirecrawl 项目的日常研发运维操作。所有脚本位于 `scripts/`，从项目根目录运行。

## 首次安装（一键）

```bash
./.claude/skills/devops/scripts/setup.sh
```

检查/安装并配置：
1. **Docker** — 必须已运行
2. **Python 3.10+** — 自动探测 3.13/3.12/3.11/3.10，避开系统自带的 3.9
3. **项目 venv** — 创建 `.venv/`（已 gitignore），装 `pip install -e ".[dev]"`（含 pytest/ruff/mypy）
4. **Node.js + agent-browser** — 全局安装 `agent-browser`，首次下载 Chrome for Testing
5. **`.env`** — 从 `.env.example` 复制
6. **`~/.zshrc`** — 写入 `export AGENT_BROWSER_SESSION_NAME=firecrawl-adapter`

可重复运行（幂等）。

## 服务管理

| 命令 | 作用 |
|------|------|
| `./.claude/skills/devops/scripts/start.sh` | 启动 SearXNG（Docker）+ adapter（本地后台，用 venv python） |
| `./.claude/skills/devops/scripts/stop.sh` | 停止 adapter + agent-browser daemon + SearXNG |
| `./.claude/skills/devops/scripts/status.sh` | 查看服务状态（SearXNG / adapter / agent-browser） |
| `./.claude/skills/devops/scripts/logs.sh [adapter\|searxng\|redis]` | 查看日志，默认 adapter |
| `./.claude/skills/devops/scripts/restart.sh` | 重启 adapter（SearXNG 不动） |

## 质量检查

| 命令 | 作用 |
|------|------|
| `./.claude/skills/devops/scripts/check.sh` | 一次性跑 pytest + ruff + mypy |
| `./.claude/skills/devops/scripts/test.sh [test_id]` | 跑全部或单个测试 |
| `./.claude/skills/devops/scripts/lint.sh [--fix]` | ruff check（--fix 自动修复） |
| `./.claude/skills/devops/scripts/typecheck.sh` | mypy adapter/ |

## 登录态管理（agent-browser）

| 命令 | 作用 |
|------|------|
| `./.claude/skills/devops/scripts/login.sh <url>` | headed 浏览器打开 URL 手动登录，cookie 自动存到 firecrawl-adapter session |
| `./.claude/skills/devops/scripts/session-show.sh` | 查看已保存的 session cookie |
| `./.claude/skills/devops/scripts/session-clear.sh` | 清空 agent-browser session（退出所有登录） |

## Claude Code MCP 管理

让 Claude Code 的搜索/抓取走本地 adapter（而非 Anthropic 后端的内置 web search）。

| 命令 | 作用 |
|------|------|
| `./.claude/skills/devops/scripts/mcp-install.sh` | 注册 `firecrawl-local` MCP 到 user scope，指向本地 adapter |
| `./.claude/skills/devops/scripts/mcp-uninstall.sh` | 移除 `firecrawl-local` MCP |
| `./.claude/skills/devops/scripts/mcp-status.sh` | 查看 MCP 注册状态 + 连接健康 + 内置 WebSearch 禁用状态 |
| `./.claude/skills/devops/scripts/mcp-websearch-deny.sh` | 在 `~/.claude/settings.json` 的 `permissions.deny` 加 `WebSearch`，强制走 MCP |
| `./.claude/skills/devops/scripts/mcp-websearch-allow.sh` | 移除 deny，恢复内置 WebSearch（与 MCP 并存） |

MCP 注册到 `~/.claude.json`（user scope，所有项目可用）。环境变量 `FIRECRAWL_API_URL=http://127.0.0.1:${ADAPTER_PORT}`、`FIRECRAWL_API_KEY=local`（占位，本地不校验）。使用前确保 SearXNG + adapter 在跑。改了 MCP 或 permissions 后需重启 Claude Code 会话生效。

## 配置

端口和地址在项目根 `.env`（已 gitignore，从 `.env.example` 复制）。改完 `.env` 后重启服务生效。`docker compose` 和 adapter（通过 python-dotenv）都会自动加载，无需手动 export。

| 变量 | 默认值 | 用途 |
|------|--------|------|
| `SEARXNG_PORT` | `3671` | SearXNG 主机端口 |
| `ADAPTER_HOST` | `127.0.0.1` | adapter 监听地址 |
| `ADAPTER_PORT` | `3672` | adapter 监听端口 |
| `SEARXNG_BASE` | `http://127.0.0.1:3671` | adapter 指向 SearXNG |
| `FIRECRAWL_API_URL` | `http://127.0.0.1:3672` | Hermes / MCP 指向 adapter |

## Python 选择策略

`_env.sh` 按优先级选 Python：项目 `.venv/bin/python`（setup.sh 创建）→ `.env` 里的 `ADAPTER_PYTHON` → 系统 `python3`。系统自带 3.9 无法满足 pyproject.toml 的 3.10+ 要求，所以推荐跑过 setup.sh 后所有脚本自动用 venv。

## 注意事项

- adapter 必须本地跑（Docker 镜像无 agent-browser，反爬兜底不可用）
- SearXNG 必须用 Docker（依赖多、Python 版本要求严）
- 修改 `searxng/settings.yml` 后需 `docker compose restart searxng`
- MCP server `firecrawl-local` 已在 Claude Code user scope 注册，使用前确保服务在跑
- agent-browser session cookie 默认 30 天过期（`AGENT_BROWSER_STATE_EXPIRE_DAYS` 可调）
