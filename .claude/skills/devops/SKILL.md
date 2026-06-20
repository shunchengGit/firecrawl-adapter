---
name: devops
description: firecrawl-adapter 项目的研发运维工具集。启停服务、状态日志、测试检查、首次安装。当用户提到"启动/停止服务""看日志""跑测试""检查健康""改端口"等时使用。
cli_version: ">=1.0.0"
---

# firecrawl-adapter DevOps Skill

本 skill 封装 firecrawl-adapter 项目的日常运维。所有脚本位于 `scripts/`，从项目根目录运行。

## 日常使用

```bash
./.claude/skills/devops/scripts/start.sh   # 启动（首次自动安装依赖）
./.claude/skills/devops/scripts/status.sh  # 查看状态
./.claude/skills/devops/scripts/stop.sh    # 停止
```

`start.sh` 会自愈：Docker 没跑 → 自动 `colima start`，缺 `.env` → 自动从 `.env.example` 复制，缺 Python 依赖 → 自动跑 `setup.sh`。

## 服务管理

| 命令 | 作用 |
|------|------|
| `start.sh` | 启动 SearXNG (Docker) + adapter（自愈） |
| `stop.sh` | 停止 adapter + SearXNG（不动 agent-browser） |
| `reload.sh` | 重载 adapter 代码（SearXNG 不动） |
| `status.sh` | SearXNG / adapter / agent-browser 状态 |
| `logs.sh [adapter\|searxng\|redis]` | 查看日志 |

## 首次安装

```bash
./.claude/skills/devops/scripts/setup.sh
```

检查/安装：Docker、Python 3.10+、venv + 依赖、Node.js + agent-browser、`.env`、cookie 共享配置。可重复运行（幂等），`start.sh` 也会在缺依赖时自动调用。

## 质量检查

| 命令 | 作用 |
|------|------|
| `check.sh` | pytest + ruff + mypy 一键 |
| `test.sh [id]` | 全部或单个测试 |
| `lint.sh [--fix]` | ruff check |
| `typecheck.sh` | mypy |

## 配置

端口和地址在项目根 `.env`（已 gitignore，从 `.env.example` 复制）。改完 `.env` 后重启服务生效。`docker compose` 和 adapter（通过 python-dotenv）都会自动加载，无需手动 export。

| 变量 | 默认值 | 用途 |
|------|--------|------|
| `SEARXNG_PORT` | `3671` | SearXNG 主机端口 |
| `ADAPTER_HOST` | `127.0.0.1` | adapter 监听地址 |
| `ADAPTER_PORT` | `3672` | adapter 监听端口 |
| `SEARXNG_BASE` | `http://127.0.0.1:3671` | adapter 指向 SearXNG |
| `FIRECRAWL_API_URL` | `http://127.0.0.1:3672` | Hermes / MCP 指向 adapter |
| `SEARXNG_PROXY` | `http://host.docker.internal:7890` | SearXNG 全局代理（留空=无代理） |

## Python 选择策略

`_env.sh` 按优先级选 Python：项目 `.venv/bin/python`（setup.sh 创建）→ `.env` 里的 `ADAPTER_PYTHON` → 系统 `python3`。系统自带 3.9 无法满足 pyproject.toml 的 3.10+ 要求，所以推荐跑过 setup.sh 后所有脚本自动用 venv。

## 注意事项

- adapter 必须本地跑（Docker 镜像无 agent-browser，反爬兜底不可用）
- SearXNG 必须用 Docker（依赖多、Python 版本要求严）
- 修改 `searxng/settings.yml` 后需 `docker compose restart searxng`
- agent-browser cookie 通过 `AGENT_BROWSER_SESSION_NAME` 链式传递（详见 `/browser`）
- 部署到外部 agent 使用 `/deploy`
