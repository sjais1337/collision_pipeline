#!/usr/bin/env bash
# Detached launcher for the staged O1 -> O2 -> O3 campaign.
#
# This supersedes ec2_smoke_test.sh for the long R=32 EC2 run.
# Defaults: 22 LCs x 2 threads for O1; best 8 O1 survivors go to O2 with equal
# thread split (~4 each on 48 vCPUs). O1 advance < 30 then top-8; O2 advance < 15.
# Stops after O3.
#
# Resume after a stop (once O1 results exist):
#   START_FROM=o2 ./ec2_staged_campaign.sh
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

R="${R:-32}"
JOBS="${JOBS:-22}"
O12_THREADS="${O12_THREADS:-2}"
RESERVE_VCPUS="${RESERVE_VCPUS:-4}"
O12_BUDGET="${O12_BUDGET:-9000}"
O12_MIN_WAIT="${O12_MIN_WAIT:-7200}"
O1_ADVANCE_LT="${O1_ADVANCE_LT:-30}"
O2_ADVANCE_LT="${O2_ADVANCE_LT:-15}"
O2_MAX_JOBS="${O2_MAX_JOBS:-8}"
O3_BUDGET="${O3_BUDGET:-86400}"
O3_START_BOUND="${O3_START_BOUND:-150}"
POLL_SECONDS="${POLL_SECONDS:-300}"
START_FROM="${START_FROM:-o1}"
CAMPAIGN_DIR="${CAMPAIGN_DIR:-$ROOT/campaigns/staged_R${R}}"

FOREGROUND=0
if [[ "${1:-}" == "--foreground" ]]; then
  FOREGROUND=1
  shift
fi

mkdir -p "$CAMPAIGN_DIR"
LOG="$CAMPAIGN_DIR/staged_campaign.log"
PID_FILE="$CAMPAIGN_DIR/staged_campaign.pid"

if [[ "$FOREGROUND" -eq 0 && -z "${STAGED_CAMPAIGN_DETACHED:-}" ]]; then
  export STAGED_CAMPAIGN_DETACHED=1
  : >>"$LOG"
  setsid nohup "$0" --foreground "$@" >>"$LOG" 2>&1 &
  pid=$!
  echo "$pid" >"$PID_FILE"
  echo "Started detached staged campaign (survives SSH logout)."
  echo "  PID:        $pid"
  echo "  Log:        $LOG"
  echo "  Campaign:   $CAMPAIGN_DIR"
  echo "  Start from: $START_FROM"
  echo "  Monitor:    python3 scripts/monitor_campaign.py $CAMPAIGN_DIR"
  echo "  Tail:       tail -f $LOG"
  echo "  Stop:       kill \$(cat $PID_FILE)"
  exit 0
fi

if ! command -v stp >/dev/null; then
  echo "stp not found; run scripts/ec2_setup.sh first" >&2
  exit 1
fi

{
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] staged campaign worker pid=$$"
  echo "  R=$R jobs=$JOBS o12_threads=$O12_THREADS reserve=$RESERVE_VCPUS"
  echo "  o12_budget=$O12_BUDGET o12_min_wait=$O12_MIN_WAIT"
  echo "  o1_lt=$O1_ADVANCE_LT o2_lt=$O2_ADVANCE_LT o2_max=$O2_MAX_JOBS start_from=$START_FROM"
  echo "  o3_budget=$O3_BUDGET o3_start_bound=$O3_START_BOUND campaign_dir=$CAMPAIGN_DIR cpus=$(nproc)"
} | tee -a "$LOG"

echo $$ >"$PID_FILE"

python3 -u "$ROOT/scripts/run_staged_campaign.py" \
  --R "$R" \
  --jobs "$JOBS" \
  --o12-threads "$O12_THREADS" \
  --reserve-vcpus "$RESERVE_VCPUS" \
  --o12-budget "$O12_BUDGET" \
  --o12-min-wait "$O12_MIN_WAIT" \
  --o1-advance-lt "$O1_ADVANCE_LT" \
  --o2-advance-lt "$O2_ADVANCE_LT" \
  --o2-max-jobs "$O2_MAX_JOBS" \
  --o3-budget "$O3_BUDGET" \
  --o3-start-bound "$O3_START_BOUND" \
  --poll-seconds "$POLL_SECONDS" \
  --start-from "$START_FROM" \
  --campaign-dir "$CAMPAIGN_DIR" \
  2>&1 | tee -a "$LOG"

exit "${PIPESTATUS[0]}"
