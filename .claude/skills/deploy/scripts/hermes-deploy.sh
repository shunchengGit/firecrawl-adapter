#!/usr/bin/env bash
# 将 firecrawl-adapter 部署到 Hermes：在 ~/.hermes/.env 中配置 FIRECRAWL_API_URL 指向本地 adapter
set -e
. "$(dirname "$0")/_env.sh"

HERMES_ENV="${HOME}/.hermes/.env"
HERMES_REPO="${HOME}/.hermes/hermes-agent"

echo "==> 检查 Hermes 安装"
if [ -f "${HERMES_ENV}" ]; then
    echo "    ✓ 找到 ${HERMES_ENV}"
elif [ -d "${HERMES_REPO}" ]; then
    HERMES_ENV="${HERMES_REPO}/.env"
    if [ -f "${HERMES_ENV}" ]; then
        echo "    ✓ 找到 ${HERMES_ENV}（dev 安装）"
    else
        echo "    ✗ Hermes 目录存在但无 .env 文件"
        echo "    → 创建 ${HERMES_ENV}"
        touch "${HERMES_ENV}"
    fi
else
    echo "    ✗ 未找到 Hermes 安装（~/.hermes/.env 或 ~/.hermes/hermes-agent）"
    echo "    → 请先安装 Hermes: https://github.com/nousresearch/hermes-agent"
    exit 1
fi

echo
echo "==> 配置 FIRECRAWL_API_URL"
TARGET_URL="http://127.0.0.1:${ADAPTER_PORT}"

# 检查是否已配置
if grep -q "^FIRECRAWL_API_URL=" "${HERMES_ENV}" 2>/dev/null; then
    CURRENT_URL=$(grep "^FIRECRAWL_API_URL=" "${HERMES_ENV}" | cut -d= -f2-)
    if [ "${CURRENT_URL}" = "${TARGET_URL}" ]; then
        echo "    已配置: ${TARGET_URL} (不变)"
    else
        echo "    更新: ${CURRENT_URL} → ${TARGET_URL}"
        if [[ "$OSTYPE" == "darwin"* ]]; then
            sed -i '' "s|^FIRECRAWL_API_URL=.*|FIRECRAWL_API_URL=${TARGET_URL}|" "${HERMES_ENV}"
        else
            sed -i "s|^FIRECRAWL_API_URL=.*|FIRECRAWL_API_URL=${TARGET_URL}|" "${HERMES_ENV}"
        fi
    fi
else
    # 追加到文件末尾
    echo "    新增: FIRECRAWL_API_URL=${TARGET_URL}"
    echo "FIRECRAWL_API_URL=${TARGET_URL}" >> "${HERMES_ENV}"
fi

echo
echo "==> 检查 adapter 服务"
ADAPTER_OK=false
if curl -sf "http://127.0.0.1:${ADAPTER_PORT}/healthz" -o /dev/null 2>&1; then
    echo "    ✓ adapter 在运行 (port ${ADAPTER_PORT})"
    HEALTH=$(curl -sf "http://127.0.0.1:${ADAPTER_PORT}/healthz" 2>/dev/null || echo '{"status":"unknown"}')
    echo "    health: ${HEALTH}"
    ADAPTER_OK=true
else
    echo "    ✗ adapter 未运行 (port ${ADAPTER_PORT})"
    echo "    → 请先执行: ./.claude/skills/devops/scripts/start.sh"
fi

echo
echo "==> 检查 SearXNG"
if curl -sf "http://127.0.0.1:${SEARXNG_PORT}/" -o /dev/null 2>&1; then
    echo "    ✓ SearXNG 在运行 (port ${SEARXNG_PORT})"
else
    echo "    ✗ SearXNG 未运行 (port ${SEARXNG_PORT})"
    echo "    → 请先执行: ./.claude/skills/devops/scripts/start.sh"
fi

echo
echo "==> 完成"
echo ""
echo "  Hermes .env:  ${HERMES_ENV}"
echo "  FIRECRAWL:    ${TARGET_URL}"

if $ADAPTER_OK; then
    echo
    echo "  ✓ 部署成功，Hermes 的 web_search/scrape/crawl 将走本地 adapter"
    echo "  → 在 Hermes 会话中直接使用搜索即可"
else
    echo
    echo "  → adapter 启动后 Hermes 自动可用，无需额外配置"
fi
