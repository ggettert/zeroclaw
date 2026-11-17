#!/usr/bin/env bash
set -euo pipefail
umask 077
export CARGO_TARGET_DIR="$RUNNER_TEMP/12002-quality-fresh"
test ! -e "$CARGO_TARGET_DIR"
mkdir -p "$RUNNER_TEMP/12002-quality-evidence"
evidence="$RUNNER_TEMP/12002-quality-evidence"
rustc --version; cargo --version; rustfmt --version; cargo clippy --version
python3 harness/scripts/ci/12002_verify_sources.py
sha256sum fixed/scripts/ci/rust_quality_gate.sh fixed/scripts/ci/run_clippy.sh
# One Cargo process at a time. Every independent phase runs despite earlier failure.
run_phase() {
  local name=$1 seconds=$2
  shift 2
  set +e
  timeout --signal=TERM --kill-after=20s "$seconds" "$@" 2>&1 | tee "$evidence/$name.log"
  local pipeline=("${PIPESTATUS[@]}")
  local code=${pipeline[0]}
  if [ "${pipeline[1]}" != 0 ]; then code=125; fi
  set -e
  printf '%s\n' "$code" > "$evidence/$name.exit"
  printf 'PHASE %s exit=%s\n' "$name" "$code"
  sha256sum "$evidence/$name.log"
  python3 harness/scripts/ci/12002_verify_sources.py
}
run_phase quality 1050s bash -c 'cd fixed && ./scripts/ci/rust_quality_gate.sh'
run_phase rustdoc 420s bash -c 'cd fixed && cargo doc --no-deps --workspace --exclude zeroclaw-desktop'
run_phase binary 420s bash -c 'cd fixed && cargo build --locked --bin zeroclaw'
if [ "$(cat "$evidence/binary.exit")" = 0 ]; then
  install -m 0555 "$CARGO_TARGET_DIR/debug/zeroclaw" "$evidence/zeroclaw"
  sha256sum "$evidence/zeroclaw"
  run_phase attribution 200s python3 -B harness/scripts/ci/12002_gateway_acceptance.py --case fixed --binary "$evidence/zeroclaw"
else
  echo 'PHASE attribution UNRUN: binary failed'
  echo 125 > "$evidence/attribution.exit"
fi
python3 - "$evidence" <<'PY'
import json, pathlib, sys
p = pathlib.Path(sys.argv[1])
result = {name: int((p / (name + '.exit')).read_text()) for name in ('quality', 'rustdoc', 'binary', 'attribution')}
log = (p / 'quality.log').read_text()
print(json.dumps({'phase_exits': result, 'quality_subphase_reached': {
    'fmt': '==> rust quality: cargo fmt' in log,
    'clippy': '==> rust quality: cargo clippy' in log,
    'dispatch': '==> rust quality: provider dispatch gate (' in log},
    'quality_composite_passed': result['quality'] == 0,
    'upstream_ci_all_strict_msrv_full_tests_parallel_runtime': 'UNRUN'}))
sys.exit(int(any(result.values())))
PY
