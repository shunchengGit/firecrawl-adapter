#!/usr/bin/env bash
# 从 Hermes 移除本地 adapter 配置：注释掉 ~/.hermes/.env 中的 FIRECRAWL_API_URL
set -e
. "$(dirname "$0")/_env.sh"

HERMES_ENV="${HOME}/.hermes/.env"

echo "==> 从 Hermes 移除 FIRECRAWL_API_URL"

if [ ! -f "${HERMES_ENV}" ]; then
    echo "    ~/.hermes/.env 不存在，无需操作"
    exit 0
fi

if grep -q "^FIRECRAWL_API_URL=" "${HERMES_ENV}" 2>/dev/null; then
    CURRENT_URL=$(grep "^FIRECRAWL_API_URL=" "${HERMES_ENV}" | cut -d= -f2-)
    echo "    当前: ${CURRENT_URL}"

    if [[ "$OSTYPE" == "darwin"* ]]; then
        sed -i '' 's|^FIRECRAWL_API_URL=|# FIRECRAWL_API_URL=|' "${HERMES_ENV}"
    else
        sed -i 's|^FIRECRAWL_API_URL=|# FIRECRAWL_API_URL=|' "${HERMES_ENV}"
    fi
    echo "    已注释（前缀 #）"
else
    echo "    FIRECRAWL_API_URL 未配置，无需操作"
fi

echo
echo "==> 完成"
echo "  Hermes 将回退到默认 web search 后端（如有 FIRECRAWL_API_KEY 则用云端 Firecrawl，否则自动检测 Exa/Tavily/Parallel）"
