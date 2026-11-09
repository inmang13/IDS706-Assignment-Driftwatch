#!/usr/bin/env bash
# Ask one of Clay's local NIP models a quick question (free; thoth only). Never blocks for long.
# Usage: scripts/nip.sh "question"   (DW_NIP_MODEL=nip-small|nip-medium|nip-large, default nip-small; nip-large is a slow reasoner, ~3 min)
set -u
q="${1:?usage: scripts/nip.sh \"question\"}"
model="${DW_NIP_MODEL:-nip-small}"
body=$(.venv/bin/python -c 'import json,sys; print(json.dumps({"model":sys.argv[1],"messages":[{"role":"user","content":sys.argv[2]}],"max_tokens":1200}))' "$model" "$q")
for try in 1 2; do
  out=$(curl -s -m 300 http://127.0.0.1:11434/v1/chat/completions -H 'content-type: application/json' -d "$body") && printf '%s' "$out" | grep -q '"content"' && break
  out=""; sleep 5
done
[ -n "$out" ] || { echo "nip unavailable"; exit 0; }
printf '%s' "$out" | .venv/bin/python -c 'import json,sys
try: print(json.load(sys.stdin)["choices"][0]["message"]["content"])
except Exception: print("nip unavailable")'
