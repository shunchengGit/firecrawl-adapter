#!/usr/bin/env bash
# deploy skill - 公共环境
: "${ADAPTER_PORT:=3672}"
: "${SEARXNG_PORT:=3671}"
export ADAPTER_PORT SEARXNG_PORT
