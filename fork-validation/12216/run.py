from pathlib import Path
import os, platform, re, subprocess as sp, tempfile


def check(ok, message):
    if not ok:
        raise SystemExit(message)


def run(args, capture=False):
    print('RUN', *args, flush=True)
    out=sp.run(args, stdout=sp.PIPE if capture else None, text=True, encoding='utf-8', errors='replace')
    if capture:
        print(out.stdout,flush=True)
    out.check_returncode()
    return out.stdout or ''

win = os.name=='nt'
check(os.environ['STAGE'] == ('windows' if win else 'linux'), 'runner OS mismatch')
os.environ.pop('ZEROCLAW_PLUGIN_REGISTRY_URL',None)
os.environ.pop('ZEROCLAW_REGISTRY_ARGV_FIXTURE',None)
os.environ['CARGO_TARGET_DIR']=tempfile.mkdtemp(prefix='frozen-12216-', dir=os.environ['RUNNER_TEMP'])
print(platform.platform(), platform.machine(), 'fresh target', os.environ['CARGO_TARGET_DIR'],flush=True)
host = 'x86_64-pc-windows-msvc' if win else 'x86_64-unknown-linux-gnu'
installed=run(['rustup','toolchain','list'],True)
check(re.search(r'^1\.98\.0(?:-'+re.escape(host)+r')?(?:\s|$)',installed,re.M),'Missing preinstalled Rust 1.98.0; no automatic installation or fallback.')
version=run(['rustc','+1.98.0','-vV'],True)
check('release: 1.98.0' in version and 'host: '+host in version,'wrong compiler/host')
targets=run(['rustup','target','list','--installed','--toolchain','1.98.0'],True).splitlines()
check(host in targets and 'wasm32-wasip2' in targets,'Missing preinstalled native or WASI target')
run(['rustfmt','+1.98.0','--version']); run(['cargo','+1.98.0','--version'])

cli=['-p','zeroclaw','--features','plugins-wasm-cranelift']
bin=cli+['--bin','zeroclaw']; component=cli+['--test','component']
plugins=['-p','zeroclaw-plugins','--lib']; rt=['-p','zeroclaw-runtime','--features','plugins-wasm-cranelift','--lib']; gw=['-p','zeroclaw-gateway','--features','plugins-wasm','--lib']

def case(pkg, selector, *required):
    prefix=['cargo','+1.98.0','test','--locked',*pkg]
    if win: prefix+=['--target',host]
    exact=not selector.endswith('::')
    args=prefix+[selector,'--']+(['--exact'] if exact else [])
    listed=set(re.findall(r'^([^\s]+): test$',run(args+['--list'],True),re.M))
    needed={selector} if exact else {selector+s for s in required}
    check(listed and needed <= listed, f'missing test discovery: {needed - listed}')
    print('EXPECTED',len(listed),sorted(listed),flush=True)
    text=run(args+['--test-threads=1'],True)
    passed=set(re.findall(r'^test (\S+) \.\.\. ok$',text,re.M))
    check(passed==listed and f'test result: ok. {len(listed)} passed; 0 failed; 0 ignored;' in text,'incomplete named execution')
    print('QUALIFIED selector',selector,'passed',len(passed),flush=True)

updates='plugins::update::tests::'; quick='quickstart_plugins::tests::'; gate='api_plugins::tests::'; cred='registry_credentials_are_not_projected_into_the_response'; priv='private_origin_load_failure_identifies_source_without_a_retry_recipe'; refuse='registry_approval_and_install_refuse_unprintable_commands'; cc='component::plugin_update_cli::'
cases=['approval_withholds_non_copyable_registry_command_and_keeps_installed_version','successful_union_search_shows_distinct_private_origin_labels_not_credentials','approval_from_environment_selected_origin_pins_that_origin_in_the_real_cli_command','multi_registry_update_requires_explicit_origin_after_original_publisher_removes_package']
parity = 'serialized_registry_id_is_the_origin_label_or_null'
if win:
    case(gw, gate+parity)
    run(['powershell.exe','-NoProfile','-File','scripts/ci/registry_windows_gate.ps1'])
    for s in cases[:2]: case(component,cc+s)
    case(bin,updates+refuse); case(bin,quick+priv); case(gw,gate+cred)
else:
    case(gw,gate,cred,parity)
    run(['cargo','+1.98.0','fmt','--all','--','--check'])
    case(plugins,'registry::tests::','offline_cache_requires_the_selected_stamped_origin','origin_collection_preserves_empty_sources_exact_sets_and_legacy_reader_guard','private_registry_origins_are_fetchable_but_not_copy_ready','cache_staging_collision_preserves_foreign_file_and_canonical_cache')
    case(rt,'skills::suggestions::tests::','union_cache_suggestions_pin_public_origins_and_withhold_private_commands')
    for s in ['plugin_update_cli_strings_are_translated_in_every_locale','quickstart_plugin_step_strings_format_in_every_locale']: case(rt,'i18n::tests::'+s)
    case(bin,updates,refuse)
    case(bin,'plugin_registry::tests::private_registry_error_reports_status_and_label_not_url')
    case(bin,quick+priv); case(bin,quick+'selected_origin_load_failure_retry_keeps_raw_origin_and_version')
    for s in cases: case(component,cc+s)
print('All selected gates completed.',flush=True)
