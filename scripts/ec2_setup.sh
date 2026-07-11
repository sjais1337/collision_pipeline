#!/usr/bin/env bash
# Install dependencies for the SHA-256 DC search pipeline on Ubuntu EC2.
set -euo pipefail

log() {
  printf '[%s] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*"
}

if [[ "$(id -u)" -eq 0 ]]; then
  SUDO=""
else
  SUDO="sudo"
fi

log "Updating apt indexes"
$SUDO apt-get update

log "Installing system packages"
$SUDO DEBIAN_FRONTEND=noninteractive apt-get install -y \
  python3 \
  python3-venv \
  python3-pip \
  git \
  ca-certificates \
  curl \
  build-essential \
  cmake \
  minisat \
  cryptominisat5 \
  stp

log "Checking STP + CryptoMiniSat"
if ! command -v stp >/dev/null; then
  echo "stp not found after install" >&2
  exit 1
fi

TMP_CVC="$(mktemp /tmp/stp_smoke_XXXXXX.cvc)"
cat >"$TMP_CVC" <<'EOF'
x : BITVECTOR(8);
ASSERT x = 0bin00000001;
QUERY FALSE;
COUNTEREXAMPLE;
EOF

if ! stp "$TMP_CVC" --cryptominisat --threads 2 >/dev/null; then
  echo "stp --cryptominisat smoke test failed" >&2
  rm -f "$TMP_CVC"
  exit 1
fi
rm -f "$TMP_CVC"

log "Checking Python"
python3 - <<'PY'
import sys
print("python", sys.version.split()[0])
PY

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
log "Repo ready at $REPO_DIR"
log "Run ./ec2_smoke_test from the repo root to start the benchmark campaign."
