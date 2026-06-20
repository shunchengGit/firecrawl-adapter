#!/usr/bin/env bash
. "$(dirname "$0")/_env.sh"

TARGET="${1:-adapter}"
case "$TARGET" in
  adapter)
    LOG=/tmp/firecrawl-adapter.log
    [ -f "$LOG" ] || { echo "无 adapter 日志（$LOG 不存在，adapter 可能未通过 start.sh 启动）"; exit 1; }
    echo "=== adapter 日志（最近 50 行，-f 跟踪请用 tail -f $LOG）==="
    tail -n 50 "$LOG"
    ;;
  searxng)
    echo "=== searxng 日志（最近 50 行）==="
    docker compose logs --tail=50 searxng
    ;;
  redis)
    echo "=== redis 日志（最近 50 行）==="
    docker compose logs --tail=50 redis
    ;;
  *)
    echo "用法: $0 [adapter|searxng|redis]"
    exit 1
    ;;
esac
