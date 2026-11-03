#!/usr/bin/env bash
# Run only in an approved hosted dispatch; this file is NOT sourced from target.
set -euo pipefail
[[ "${GITHUB_ACTIONS:-}" == true && "${GITHUB_REPOSITORY:-}" == ggettert/zeroclaw ]] || exit 2
[[ "${GITHUB_EVENT_NAME:-}" == workflow_dispatch ]] || exit 2
[[ "${TARGET_SHA:-}" =~ ^[0-9a-fA-F]{40}$ ]] || exit 2
case "${STAGE:-}" in shared|root-cli|runtime|gateway|frontend|schema) ;; *) exit 2;; esac
cd "$GITHUB_WORKSPACE/source"
[[ "$(git rev-parse HEAD)" == "${TARGET_SHA,,}" ]] || exit 2
origin=$(git remote get-url origin)
[[ "$origin" == https://github.com/ggettert/zeroclaw || "$origin" == https://github.com/ggettert/zeroclaw.git ]] || exit 2
export CARGO_BUILD_JOBS=1 CARGO_INCREMENTAL=0 CARGO_PROFILE_DEV_DEBUG=0 CARGO_PROFILE_TEST_DEBUG=0
# Bind every lane to the frozen 22-path corrected feature, not merely a matching SHA shape.
sha256sum --check --strict <<'FROZEN_FEATURE'
cba06652b47682d131325efbe48867231c081a8625a147df0474bdda74b3b997  crates/zeroclaw-gateway/src/api_plugins.rs
1e06c674cc3e8c993115cff461cbb65c3ceb6eea45c09b48517c6c3cf3c63eed  crates/zeroclaw-gateway/src/openapi.rs
5ebe39a21df2864a39acbe14368bc9392495813212e23e8e0899a6a97de84f56  crates/zeroclaw-gateway/tests/plugin_catalog_literal_compat.rs
ee071e571447f7b90ab1b21f0373a2bcc357020c8c57bd9e89cf6dcc7e7937a0  crates/zeroclaw-plugins/src/catalog.rs
6c2294ad06e69d9594c08e62217b527881ba6c0b2601db725fb79d5f079db76e  crates/zeroclaw-plugins/src/registry.rs
15e1a293aaec3283c10fff3dfc077b33d37db77dc4938e98e3254e4fb7934258  crates/zeroclaw-plugins/tests/registry_literal_compat.rs
0280d601a29d54d224a73a0bd18cde59dd1ef4cf76460855fe15cf9b775253d3  crates/zeroclaw-runtime/locales/en/cli.ftl
8bd5c196b52f233412506eb4171bd7c8381147cc70cc3ce00c1dbd7ad9a082af  crates/zeroclaw-runtime/src/skills/suggestions.rs
f9962e17ee37ff79f4705a97615c8d58a657814f98882bfc77ab19ae0be0fc67  docs/book/src/plugins/distributing-plugins.md
4351691f87d08753ed46b21b60a5132a3e0353acfac1fb8a8fe95352c7498066  docs/book/src/reference/env-vars.md
0fcd4536bfdf7076d7ea72a63f2fec49ca2cbb3b2230378f115e1b6ce5833ca8  src/main.rs
a02729449475996fa2f6bede5ccad142313fb88ff7e3ef120582810b46820d76  src/plugin_catalog.rs
a0e10106949c168c71ab78bcf1b5d454c5c3e78acfc797549374f6d860ea16aa  src/plugin_registry.rs
a1eea3c3bec4c996d1bc7753c0709a64f17f46653a21debbf25577b300e70d8e  src/plugins/egress_ceremony.rs
5e200872d14d849d2c255e8a5967de89699ae1c1719ae2ca9ede3f793de9e854  src/plugins/update.rs
bded7b2de156370d9bb7119ddc4d92c87bb91858c4d833466d9b47f617eb4495  src/quickstart_plugins/mod.rs
fe4384c5eff1e723ee782aaadb0ed7feead923263c548f36b0d716e6948c5b91  src/quickstart_plugins/model.rs
1c0f676b281f30ecfc2f42eba5f88763c93aec9efdad423336bfde2dd676709c  tests/component/plugin_update_cli.rs
a23c5d029550755f90b5bd2c9e91c067c3769ecf51a2cfc130b92c4744274ed6  web/src/lib/api.ts
2cb2a2a320087ecc2003186e13bc657a4764fdf29d53af8250513160e9f55940  web/src/pages/Plugins.tsx
10ce591d7a4e4dba2d35070626f670418f9401276e6165f2132fdc69d5e4e6d8  web/src/pages/pluginCatalog.test.ts
07640d116504a54c1650d2e8b91086bdac6815b33b18ea21269c495f701c7fff  web/src/pages/pluginCatalog.ts
FROZEN_FEATURE
# No unreviewed extra files relative to cached base (fixture paths are in the allowlist).
expected=$(sed -n '/^sha256sum --check/,/^FROZEN_FEATURE/p' "$GITHUB_WORKSPACE/tooling/scripts/ci/fork_12109_validation.sh" | sed '1d;$d' | cut -c67- | sort)
actual=$(git diff-tree --no-commit-id --name-only -r 03b29bcc68eadf8bd03905b93d6867d3af9d7b87 HEAD | sort)
[[ "$actual" == "$expected" ]] || { echo 'Unexpected target change set'; exit 2; }
# Isolated job scratch, no restored Cargo HOME config or checkout caches.
export CARGO_HOME="$RUNNER_TEMP/12109-cargo" CARGO_TARGET_DIR="$RUNNER_TEMP/12109-target"
mkdir -p "$CARGO_HOME" "$CARGO_TARGET_DIR"
run() { printf '+ '; printf '%q ' "$@"; printf '\n'; "$@"; }
if [[ "$STAGE" != frontend ]]; then
  run cargo --version
  run rustc --version
  # Use stock GNU linker; fail rather than assuming Blacksmith clang/mold setup.
  run cc --version
  run pkg-config --version
fi
# Build one selected test target before listing/running its filtered tests.
# Each selector must discover >=1 non-ignored harness test; fail on empty or ignored.
tests() {
  local selector listing
  local -a args=()
  while [[ "$1" != -- ]]; do args+=("$1"); shift; done
  shift
  run cargo test --locked "${args[@]}" --no-run
  for selector in "$@"; do
    listing=$(run cargo test --locked "${args[@]}" -- "$selector" --list)
    printf '%s\n' "$listing"
    grep -Eq ': test$' <<< "$listing" || { echo "EMPTY selector: $selector"; exit 4; }
    # A focused phase may not silently pass with zero execution / ignored tests.
    run cargo test --locked "${args[@]}" -- "$selector" --test-threads=1 |
      tee "$RUNNER_TEMP/12109-logs/last-test.log"
    grep -Eq 'test result: ok\. [1-9][0-9]* passed; 0 failed; 0 ignored;' "$RUNNER_TEMP/12109-logs/last-test.log" || exit 4
  done
}
case "$STAGE" in
  shared)
    # Small first lane: no WASM backend. Production registry/catalog do not require it.
    tests -p zeroclaw-plugins --no-default-features --lib -- \
      origin_collection_preserves_empty_sources_exact_sets_and_legacy_reader_guard \
      mixed_case_legacy_cache_and_public_command_helpers_remain_compatible \
      cache_refresh_never_widens_an_existing_private_cache \
      raw_registry_arguments_render_for_each_supported_shell \
      new_origin_labels_are_nonempty_private_and_distinguishable \
      catalog::tests::
    tests -p zeroclaw-plugins --no-default-features --test registry_literal_compat -- baseline_registry_literals_remain_source_compatible
    ;;
  root-cli)
    # Real backend + agent runtime are required for Quickstart, without default channel bundle.
    tests -p zeroclaw --no-default-features --features agent-runtime,plugins-wasm-cranelift,channel-filesystem --bin zeroclaw -- \
      registry_selection_preserves_legacy_and_explicit_override_precedence \
      combined_search_retains_actual_origins_and_pinned_install_is_still_ambiguous \
      a_failed_union_keeps_the_previous_cache_and_never_fetches_archives \
      explicit_registry_download_selects_only_the_requested_publisher \
      a_stalled_second_index_keeps_cache_and_requests_no_archive \
      oversized_index_is_rejected_before_json_or_archive_processing \
      mixed_case_http_source_passes_real_preflight_fetch_and_keeps_exact_origin \
      invalid_second_source_is_rejected_before_any_http \
      registry_update_rejects_cross_origin_names_even_with_a_unique_pinned_version \
      selected_origin_load_failure_retry_keeps_raw_origin_and_version \
      successful_choice_labels_do_not_disclose_credentials_or_collapse_publishers \
      multiple_origins_remain_visible_and_create_downloads_only_the_selected_origin \
      selecting_two_publishers_of_one_name_is_refused_before_create
    tests -p zeroclaw --no-default-features --features agent-runtime,plugins-wasm-cranelift,channel-filesystem --test component -- \
      multi_registry_update_requires_explicit_origin_after_original_publisher_removes_package \
      approval_from_environment_selected_origin_pins_that_origin_in_the_real_cli_command \
      successful_union_search_shows_distinct_private_origin_labels_not_credentials
    ;;
  runtime)
    tests -p zeroclaw-runtime --no-default-features --features plugins-wasm-cranelift --lib -- \
      skills::suggestions::tests::union_cache_suggestions_keep_each_publishers_explicit_install_command
    ;;
  gateway)
    tests -p zeroclaw-gateway --no-default-features --features schema-export,plugins-wasm,zeroclaw-plugins/plugins-wasm-cranelift --lib -- api_plugins::tests:: publisher_identity_is_distinct_without_exposing_source_urls
    tests -p zeroclaw-gateway --no-default-features --features schema-export,plugins-wasm,zeroclaw-plugins/plugins-wasm-cranelift --test plugin_catalog_literal_compat -- baseline_gateway_literals_remain_source_compatible
    ;;
  frontend)
    run node --version
    # No npm test lifecycle (it also runs unrelated pretest suites). Type-only imports erased.
    run node --experimental-strip-types --test-reporter=tap --test web/src/pages/pluginCatalog.test.ts |
      tee "$RUNNER_TEMP/12109-logs/frontend-test.log"
    grep -Eq '^# pass [1-9][0-9]*$' "$RUNNER_TEMP/12109-logs/frontend-test.log" || exit 4
    ;;
  schema)
    run node --version
    run npm --version
    # Frozen npm lock; no speculative package installation via npx.
    (cd web && run npm ci --no-audit --no-fund)
    # Same canonical exporter as cargo web gen-api; avoid alias's release profile.
    # xtask has broad owning dependencies, but this selects ONE binary, never workspace build.
    run cargo run --locked -p xtask --bin web -- gen-api
    # Assert additive DTOs actually reached the regenerated contract.
    for schema in OriginAvailablePluginPackage OriginPluginCatalogEntry OriginPluginsResponse; do
      grep -Fq "$schema" target/openapi.json || exit 5
      grep -Fq "$schema" web/src/lib/api-generated.ts || exit 5
    done
    (cd web && run npm run typecheck)
    ;;
esac
run git rev-parse HEAD
run df -h "$RUNNER_TEMP"
run free -h
