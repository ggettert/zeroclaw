#!/usr/bin/env bash
# Trusted CI-only launcher; never sourced from candidate checkout.
set -euo pipefail
[[ "${GITHUB_ACTIONS:-}" == true && "${GITHUB_REPOSITORY:-}" == ggettert/zeroclaw ]] || exit 2
[[ "${GITHUB_EVENT_NAME:-}" == workflow_dispatch ]] || exit 2
case "${STAGE:-}" in review-shared|review-runtime|review-format|review-windows) ;; *) exit 2;; esac
python3 "$GITHUB_WORKSPACE/tooling/scripts/ci/fork_12109_verify.py" "$GITHUB_WORKSPACE/source" "$GITHUB_WORKSPACE/tooling/scripts/ci/fork_12109_review_manifest.json"
cd "$GITHUB_WORKSPACE/source"
export CARGO_BUILD_JOBS=1 CARGO_INCREMENTAL=0 CARGO_PROFILE_DEV_DEBUG=0 CARGO_PROFILE_TEST_DEBUG=0
# No restored caches or user Cargo config. Keep platform-native default Cargo home.
export CARGO_TARGET_DIR="$RUNNER_TEMP/12109-target"
mkdir -p "$CARGO_TARGET_DIR"
run() { printf '+ '; printf '%q ' "$@"; printf '\n'; "$@"; }
exact_test() {
  local selector="$1"; shift
  local log="$RUNNER_TEMP/12109-logs/last-test.log"
  run cargo test --locked "$@" "$selector" -- --exact --test-threads=1 2>&1 | tee "$log"
  grep -Fq 'test result: ok. 1 passed; 0 failed; 0 ignored;' "$log" || { echo 'Expected exactly one executed nonignored regression'; exit 4; }
}
case "$STAGE" in
  review-shared)
    exact_test registry::tests::registry_copy_ready_boundary_refuses_unsafe_windows_values_only -p zeroclaw-plugins --no-default-features --lib
    exact_test registry::tests::raw_registry_arguments_render_for_each_supported_shell -p zeroclaw-plugins --no-default-features --lib
    exact_test baseline_registry_literals_remain_source_compatible -p zeroclaw-plugins --no-default-features --test registry_literal_compat
    # Exact previously failing CI backend command, not just an approximate filter.
    run cargo test --locked -p zeroclaw-plugins --no-default-features --features plugins-wasm-cranelift --lib
    ;;
  review-runtime)
    exact_test i18n::tests::quickstart_plugin_step_strings_format_in_every_locale -p zeroclaw-runtime --lib
    exact_test skills::suggestions::tests::union_cache_suggestions_keep_each_publishers_explicit_install_command -p zeroclaw-runtime --no-default-features --features plugins-wasm-cranelift --lib
    ;;
  review-format)
    run cargo fmt --all -- --check
    # Affected plugin crate, same all-targets/-D warnings contract, intentionally
    # NOT a claim to repeat upstream workspace/ci-all or unrelated tools Clippy.
    run cargo clippy --locked -p zeroclaw-plugins --no-default-features --all-targets -- -D warnings
    ;;
  review-windows)
    [[ "${RUNNER_OS:-}" == Windows ]] || exit 2
    command -v powershell.exe >/dev/null
    command -v cmd.exe >/dev/null
    # Gate itself builds fresh recorder and validates exact counts including
    # all three shell tests and CLI/runtime/Quickstart consumers. No skip path.
    run powershell.exe -NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass -File scripts/ci/registry_windows_gate.ps1
    ;;
esac
run git rev-parse HEAD
run git status --short
