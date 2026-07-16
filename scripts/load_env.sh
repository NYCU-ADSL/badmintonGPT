#!/usr/bin/env bash
# Export every var in this project's .env so nanobot can resolve ${VAR} in config.json.
# Usage:  source scripts/load_env.sh   then run `nanobot gateway` / `nanobot agent`.
# Reads ONLY this project's .env (no fallback to other projects). Adding a new MCP's
# token = just add lines to .env (e.g. OTHER_CF_CLIENT_ID=...); no edit here needed.

export PATH="$HOME/.local/bin:$PATH"
_GPT_ENV="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/.env"

if [ -f "$_GPT_ENV" ]; then
  set -a                 # auto-export everything sourced below
  # shellcheck disable=SC1090
  . "$_GPT_ENV"          # honours comments (#) and KEY=VALUE lines
  set +a
else
  echo "⚠️  找不到 $_GPT_ENV（請 cp .env.example .env 後填值）" >&2
fi

# config.json 用 ${NANOBOT_MODEL} 解析 Agent 預設模型；未設會讓 nanobot 啟動時報錯，故給預設值。
export NANOBOT_MODEL="${NANOBOT_MODEL:-gpt-5.5}"

# 額外的「Custom」model preset（config.json 的 providers.custom + model_presets.custom，
# WebUI Settings 的模型選單可切換；預設仍用 GPT-5.5）。未設則空字串 —— nanobot 對「未設」的
# ${VAR} 會報錯（空字串不會），故給空預設讓未填時也能啟動；填了 .env 三個值該 preset 才可用。
export CUSTOM_MODEL_API_BASE="${CUSTOM_MODEL_API_BASE:-}"
export CUSTOM_MODEL_API_KEY="${CUSTOM_MODEL_API_KEY:-}"
export CUSTOM_MODEL_API_MODEL="${CUSTOM_MODEL_API_MODEL:-}"

[ -z "$OPENAI_API_KEY" ] && echo "⚠️  OPENAI_API_KEY 未設定（Agent 將無法回應）" >&2
echo "env loaded from .env: OPENAI_API_KEY=${OPENAI_API_KEY:+set} NANOBOT_MODEL=${NANOBOT_MODEL} CUSTOM_MODEL=${CUSTOM_MODEL_API_MODEL:-unset} REELS_CF_CLIENT_ID=${REELS_CF_CLIENT_ID:+set}"
