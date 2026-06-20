#!/usr/bin/env bash
# 关闭所有 agent-browser daemon，清除所有 session state 文件
. "$(dirname "$0")/_env.sh"

echo "==> 关闭 agent-browser daemon"
agent-browser close --all 2>/dev/null || true
sleep 1

echo "==> 清除 session state 文件"
rm -rf ~/.agent-browser/sessions/*.json 2>/dev/null
rm -rf ~/.agent-browser/shared-profile 2>/dev/null
echo "==> 完成（所有登录态已清除）"
