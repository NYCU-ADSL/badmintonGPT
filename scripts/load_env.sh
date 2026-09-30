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
  echo "⚠️  Cannot find $_GPT_ENV (run cp .env.example .env and fill in the values)" >&2
fi

# config.json resolves the agent's default model from ${NANOBOT_MODEL}; supply a default to avoid startup errors when unset.
export NANOBOT_MODEL="${NANOBOT_MODEL:-gpt-5.5}"

# Additional Custom model preset (providers.custom + model_presets.custom in config.json),
# selectable in WebUI Settings; GPT-5.5 remains the default. Use empty strings when unset:
# nanobot rejects unset ${VAR} values but accepts empty strings. All three .env values are required to use this preset.
export CUSTOM_MODEL_API_BASE="${CUSTOM_MODEL_API_BASE:-}"
export CUSTOM_MODEL_API_KEY="${CUSTOM_MODEL_API_KEY:-}"
export CUSTOM_MODEL_API_MODEL="${CUSTOM_MODEL_API_MODEL:-}"

[ -z "$OPENAI_API_KEY" ] && echo "⚠️  OPENAI_API_KEY is unset (the agent will not be able to respond)" >&2
echo "env loaded from .env: OPENAI_API_KEY=${OPENAI_API_KEY:+set} NANOBOT_MODEL=${NANOBOT_MODEL} CUSTOM_MODEL=${CUSTOM_MODEL_API_MODEL:-unset} REELS_CF_CLIENT_ID=${REELS_CF_CLIENT_ID:+set}"
