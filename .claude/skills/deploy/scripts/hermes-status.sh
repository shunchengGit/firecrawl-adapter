#!/usr/bin/env bash
# 检查 Hermes ↔ adapter 集成状态
. "$(dirname "$0")/_env.sh"

HERMES_ENV="${HOME}/.hermes/.env"
HERMES_CONFIG="${HOME}/.hermes/config.yaml"
HERMES_BINARY="${HOME}/.local/bin/hermes"

echo "=== Hermes 安装 ==="
if command -v hermes >/dev/null 2>&1; then
    echo "  binary: $(command -v hermes)"
    HERMES_VERSION=$(hermes --version 2>/dev/null || echo "无法获取版本")
    echo "  version: ${HERMES_VERSION}"
elif [ -f "${HERMES_BINARY}" ]; then
    echo "  binary: ${HERMES_BINARY}"
else
    echo "  ✗ 未安装（未找到 hermes 命令）"
fi

if [ -f "${HERMES_CONFIG}" ]; then
    echo "  config: ${HERMES_CONFIG}"
fi

echo
echo "=== FIRECRAWL_API_URL 配置 ==="
if [ -f "${HERMES_ENV}" ]; then
    if grep -q "^FIRECRAWL_API_URL=" "${HERMES_ENV}" 2>/dev/null; then
        CURRENT_URL=$(grep "^FIRECRAWL_API_URL=" "${HERMES_ENV}" | cut -d= -f2-)
        echo "  ✓ 指向: ${CURRENT_URL}"
    elif grep -q "^# FIRECRAWL_API_URL=" "${HERMES_ENV}" 2>/dev/null; then
        echo "  ⊘ 已注释（被禁用）"
    else
        echo "  ✗ 未配置"
    fi
else
    echo "  ✗ ${HERMES_ENV} 不存在"
fi

echo
echo "=== adapter (port ${ADAPTER_PORT}) ==="
if curl -sf "http://127.0.0.1:${ADAPTER_PORT}/healthz" 2>/dev/null; then
    echo "  ✓ healthy"
else
    echo "  ✗ down"
fi

echo
echo "=== SearXNG (port ${SEARXNG_PORT}) ==="
if curl -sf "http://127.0.0.1:${SEARXNG_PORT}/" -o /dev/null 2>&1; then
    echo "  ✓ reachable"
else
    echo "  ✗ down"
fi

echo
echo "=== 端到端测试 (adapter → SearXNG) ==="
# 只测 adapter health（需 SearXNG 在线才能返回 ok）
HEALTH_JSON=$(curl -sf "http://127.0.0.1:${ADAPTER_PORT}/healthz" 2>/dev/null || echo '')
if echo "${HEALTH_JSON}" | grep -q '"status":"ok"'; then
    echo "  ✓ adapter + SearXNG 链路正常"
elif echo "${HEALTH_JSON}" | grep -q '"status":"degraded"'; then
    echo "  ⚠ adapter 在线但 SearXNG 不可达（degraded）"
elif echo "${HEALTH_JSON}" | grep -q '"status"'; then
    echo "  ⚠ adapter 返回异常: ${HEALTH_JSON}"
else
    echo "  ✗ adapter 不可达，无法测试链路"
fi

echo
echo "=== 总结 ==="
HERMES_CONFIGURED=false
ADAPTER_UP=false
SEARXNG_UP=false

if [ -f "${HERMES_ENV}" ] && grep -q "^FIRECRAWL_API_URL=" "${HERMES_ENV}" 2>/dev/null; then
    HERMES_CONFIGURED=true
fi
if curl -sf "http://127.0.0.1:${ADAPTER_PORT}/healthz" -o /dev/null 2>&1; then
    ADAPTER_UP=true
fi
if curl -sf "http://127.0.0.1:${SEARXNG_PORT}/" -o /dev/null 2>&1; then
    SEARXNG_UP=true
fi

if $HERMES_CONFIGURED && $ADAPTER_UP && $SEARXNG_UP; then
    echo "  ✓ 一切就绪，Hermes web 工具走本地 adapter"
elif ! $HERMES_CONFIGURED; then
    echo "  → 执行 hermes-deploy.sh 配置 Hermes"
elif ! $ADAPTER_UP || ! $SEARXNG_UP; then
    echo "  → 执行 start.sh 启动服务"
fi
