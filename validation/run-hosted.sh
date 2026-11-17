#!/usr/bin/env bash
# Only for an explicitly approved, isolated GitHub-hosted Ubuntu runner.
# Source-only preparation is not authorization to publish or run this script.
set -euo pipefail
: "${GITHUB_ACTIONS:?This harness must not run on the live assistant host}"
test "$GITHUB_ACTIONS" = true
test "${RUNNER_ENVIRONMENT:-}" = github-hosted
test "${RUNNER_OS:-}" = Linux
cd "$(dirname "$0")/.."
mkdir -p evidence
export TZ=America/Los_Angeles CARGO_BUILD_JOBS=1 CARGO_INCREMENTAL=0
export CARGO_PROFILE_DEV_DEBUG=0 CARGO_PROFILE_TEST_DEBUG=0
rustc +1.96.0 --version --verbose | tee evidence/toolchain.txt
cargo +1.96.0 --version | tee -a evidence/toolchain.txt
# No lockfile was generated on the source-only authoring host.
if test ! -f Cargo.lock; then cargo +1.96.0 generate-lockfile; fi
sha256sum Cargo.lock | tee evidence/lock.sha256
cargo +1.96.0 tree --locked --edges normal,build --prefix none | tee evidence/normal-build-tree.txt
if grep -E '^(chrono|chrono-tz) v' evidence/normal-build-tree.txt; then
  echo 'Unexpected chrono in candidate normal/build graph' >&2; exit 1
fi
cargo +1.96.0 test --locked --test timestamps --test schedules --no-run 2>&1 | tee evidence/compile.txt
cargo +1.96.0 test --locked --test timestamps -- --list 2>&1 | tee evidence/timestamps-list.txt
cargo +1.96.0 test --locked --test schedules -- --list 2>&1 | tee evidence/schedules-list.txt
test "$(grep -c ': test$' evidence/timestamps-list.txt)" -eq 5
test "$(grep -c ': test$' evidence/schedules-list.txt)" -eq 9
cargo +1.96.0 test --locked --test timestamps --test schedules -- --nocapture --test-threads=1 2>&1 | tee evidence/tests.txt
