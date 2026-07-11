#!/usr/bin/env bash
# Install dependencies for the SHA-256 DC search pipeline on Ubuntu EC2.
#
# Ubuntu EC2 images often lack the stp / cryptominisat5 apt packages. This
# script installs build deps via apt, then builds CryptoMiniSat + STP from
# source when needed.
set -euo pipefail

log() {
  printf '[%s] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*"
}

if [[ "$(id -u)" -eq 0 ]]; then
  SUDO=""
else
  SUDO="sudo"
fi

NPROC="$(nproc 2>/dev/null || echo 4)"
BUILD_ROOT="${SHA2_BUILD_ROOT:-/tmp/sha2-solver-build}"

log "Updating apt indexes"
$SUDO apt-get update

log "Installing base packages and build dependencies"
$SUDO DEBIAN_FRONTEND=noninteractive apt-get install -y \
  python3 \
  python3-venv \
  python3-pip \
  git \
  ca-certificates \
  curl \
  build-essential \
  cmake \
  ninja-build \
  pkg-config \
  bison \
  flex \
  perl \
  help2man \
  libboost-all-dev \
  libgmp-dev \
  zlib1g-dev

try_apt_stp() {
  log "Trying apt packages (universe repo)"
  $SUDO DEBIAN_FRONTEND=noninteractive apt-get install -y \
    software-properties-common >/dev/null 2>&1 || true
  $SUDO add-apt-repository -y universe >/dev/null 2>&1 || true
  $SUDO apt-get update

  local installed=0
  if apt-cache show stp >/dev/null 2>&1; then
    $SUDO DEBIAN_FRONTEND=noninteractive apt-get install -y stp && installed=1
  fi
  if apt-cache show cryptominisat5 >/dev/null 2>&1; then
    $SUDO DEBIAN_FRONTEND=noninteractive apt-get install -y cryptominisat5 || true
  fi
  [[ "$installed" -eq 1 ]]
}

stp_has_cryptominisat() {
  command -v stp >/dev/null && stp --help 2>&1 | grep -q cryptominisat
}

build_cryptominisat() {
  if pkg-config --exists cryptominisat5 2>/dev/null; then
    log "CryptoMiniSat already installed"
    return 0
  fi
  if [[ -f /usr/local/lib/cmake/cryptominisat5/cryptominisat5Config.cmake ]]; then
    log "CryptoMiniSat already installed under /usr/local"
    return 0
  fi

  log "Building CryptoMiniSat from source ($NPROC cores)"
  mkdir -p "$BUILD_ROOT"
  if [[ ! -d "$BUILD_ROOT/cryptominisat/.git" ]]; then
    git clone --depth 1 https://github.com/msoos/cryptominisat.git \
      "$BUILD_ROOT/cryptominisat"
  fi
  cmake -S "$BUILD_ROOT/cryptominisat" -B "$BUILD_ROOT/cryptominisat/build" \
    -G Ninja \
    -DCMAKE_BUILD_TYPE=Release
  cmake --build "$BUILD_ROOT/cryptominisat/build" -j "$NPROC"
  $SUDO cmake --install "$BUILD_ROOT/cryptominisat/build"
  if command -v ldconfig >/dev/null; then
    $SUDO ldconfig
  fi
}

build_stp() {
  if stp_has_cryptominisat; then
    log "STP with CryptoMiniSat already available"
    return 0
  fi

  log "Building STP from source ($NPROC cores)"
  mkdir -p "$BUILD_ROOT"
  if [[ ! -d "$BUILD_ROOT/stp/.git" ]]; then
    git clone --depth 1 https://github.com/stp/stp.git "$BUILD_ROOT/stp"
  fi
  git -C "$BUILD_ROOT/stp" submodule update --init --recursive

  CMS_DIR=""
  for candidate in \
    /usr/local/lib/cmake/cryptominisat5 \
    "$BUILD_ROOT/cryptominisat/build" \
    "$BUILD_ROOT/cryptominisat/build/lib/cmake/cryptominisat5"; do
    if [[ -f "$candidate/cryptominisat5Config.cmake" ]]; then
      CMS_DIR="$candidate"
      break
    fi
  done

  cmake_args=(
    -S "$BUILD_ROOT/stp"
    -B "$BUILD_ROOT/stp/build"
    -G Ninja
    -DCMAKE_BUILD_TYPE=Release
  )
  if [[ -n "$CMS_DIR" ]]; then
    cmake_args+=("-Dcryptominisat5_DIR=$CMS_DIR")
  fi

  cmake "${cmake_args[@]}"
  cmake --build "$BUILD_ROOT/stp/build" -j "$NPROC"
  $SUDO cmake --install "$BUILD_ROOT/stp/build"
  if command -v ldconfig >/dev/null; then
    $SUDO ldconfig
  fi
}

if try_apt_stp && stp_has_cryptominisat; then
  log "Installed STP from apt"
else
  log "apt packages unavailable or missing CryptoMiniSat support; building from source"
  build_cryptominisat
  build_stp
fi

log "Checking STP + CryptoMiniSat"
if ! command -v stp >/dev/null; then
  echo "stp not found after install/build" >&2
  exit 1
fi
if ! stp_has_cryptominisat; then
  echo "stp was installed but --cryptominisat is not available" >&2
  stp --help 2>&1 | head -20 >&2 || true
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
log "Run ./ec2_smoke_test.sh from the repo root to start the benchmark campaign."
