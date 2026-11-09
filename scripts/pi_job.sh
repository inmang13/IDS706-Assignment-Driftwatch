#!/usr/bin/env bash
# Run an unattended Pi job on thoth, surviving flaky wifi.
# Usage: scripts/pi_job.sh <prompt-file> <branch> [deadline HH:MM, default 07:30]
# - waits for the network before each attempt, resumes after crashes/outages (prompt reads docs/*_status.md)
# - pushes the branch after each attempt, retrying; never touches main
# Log: logs/pi_job-<branch>.log (gitignored)
set -u
cd "$(dirname "$0")/.."
PROMPT_FILE="${1:?prompt file}"; BRANCH="${2:?branch}"; DEADLINE="${3:-07:30}"
MODEL="${MODEL:-opus}"; MAX_ATTEMPTS="${MAX_ATTEMPTS:-8}"
mkdir -p logs; LOG="logs/pi_job-${BRANCH//\//_}.log"
log(){ echo "[$(date '+%F %T')] $*" | tee -a "$LOG"; }
deadline_s=$(date -d "$DEADLINE" +%s); [ "$deadline_s" -lt "$(date +%s)" ] && deadline_s=$(date -d "tomorrow $DEADLINE" +%s)
past_deadline(){ [ "$(date +%s)" -ge "$deadline_s" ]; }
net_ok(){ curl -s -m 10 -o /dev/null https://api.anthropic.com/ ; }
wait_net(){ local n=0; until net_ok; do n=$((n+1)); [ $((n % 10)) -eq 1 ] && log "network down, waiting"; past_deadline && return 1; sleep 30; done; }
push(){ for i in 1 2 3 4 5; do git push -u origin "$BRANCH" >>"$LOG" 2>&1 && { log "pushed $BRANCH"; return 0; }; log "push failed ($i), retrying"; sleep 60; done; return 1; }
status_line(){ head -1 docs/m*_status.md docs/*_status.md 2>/dev/null | grep -m1 -E 'DONE|STOPPED' ; }

[ "$(git branch --show-current)" = "$BRANCH" ] || { log "not on $BRANCH, refusing"; exit 2; }
ALLOWED=(
  "Bash(make:*)" "Bash(.venv/bin/python:*)" "Bash(.venv/bin/pytest:*)" "Bash(.venv/bin/ruff:*)" "Bash(.venv/bin/black:*)"
  "Bash(git add:*)" "Bash(git commit:*)" "Bash(git status:*)" "Bash(git diff:*)" "Bash(git log:*)" "Bash(git show:*)"
  "Bash(git restore:*)" "Bash(git checkout -- :*)" "Bash(git stash:*)" "Bash(git push origin $BRANCH:*)"
  "Bash(ls:*)" "Bash(cat:*)" "Bash(head:*)" "Bash(tail:*)" "Bash(wc:*)" "Bash(grep:*)" "Bash(mkdir:*)" "Bash(scripts/nip.sh:*)"
  "Read" "Edit" "Write" "Glob" "Grep"
)
log "start: prompt=$PROMPT_FILE branch=$BRANCH model=$MODEL deadline=$(date -d @$deadline_s '+%F %T')"
for attempt in $(seq 1 "$MAX_ATTEMPTS"); do
  past_deadline && { log "deadline reached"; break; }
  wait_net || { log "deadline reached while offline"; break; }
  log "attempt $attempt"
  pre=""; [ "$attempt" -gt 1 ] && pre="RESUMING after an interruption (attempt $attempt). Read docs/m1_status.md and git log first; continue, do not redo. "
  nice -n 10 timeout $(( deadline_s - $(date +%s) )) claude -p --model "$MODEL" --permission-mode acceptEdits \
    --allowedTools "${ALLOWED[@]}" --disallowedTools "WebFetch" "WebSearch" "Bash(pip:*)" "Bash(git push origin main:*)" \
    --max-turns 200 "$pre$(cat "$PROMPT_FILE")" >>"$LOG" 2>&1
  rc=$?; log "claude exited rc=$rc"
  push || log "push gave up; branch is committed locally"
  s=$(status_line); [ -n "$s" ] && { log "status: $s"; break; }
  sleep 60
done
log "finished. status: $(status_line || echo 'no DONE/STOPPED line')"
