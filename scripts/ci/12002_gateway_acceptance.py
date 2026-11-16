#!/usr/bin/env python3
"""Real binary/HTTP/SQLite A/B acceptance; only the external LLM is a stub.
Usage: python3 12002_gateway_acceptance.py --case baseline|fixed --binary PATH
Private startup output and pairing credentials never enter public diagnostics.
--self-test checks fixture guards only, NOT application acceptance.
"""
import argparse
import hashlib
import http.server
import json
import os
from pathlib import Path
import re
import signal
import sqlite3
import subprocess
import tempfile
import threading
import time
import urllib.request
import uuid

MESSAGES = ["AUTOSAVE_PROBE_ONE", "AUTOSAVE_PROBE_TWO"]
SQL = """SELECT m.key,m.content,m.category,m.session_id,m.namespace,m.agent_id,m.principal_id
FROM memories m JOIN agents a ON a.id=m.agent_id
WHERE a.alias='autosaveprobe' AND m.session_id='autosave-same'
AND (m.key='user_msg' OR m.key GLOB 'user_msg_*') ORDER BY m.created_at,m.key"""
CONFIG = '''schema_version = 4
[providers.models.custom.fixture]
uri = "http://127.0.0.1:PROVIDER_PORT/v1/chat/completions"
api_key = "local-fixture-not-a-credential"
model = "fixture-model"
temperature = 0.0
timeout_secs = 15
live_pricing = false
[agents.autosaveprobe]
enabled = true
model_provider = "custom.fixture"
risk_profile = "fixture"
runtime_profile = "fixture"
[agents.autosaveprobe.memory]
backend = "sqlite"
[risk_profiles.fixture]
level = "supervised"
deny_all_tools = true
[runtime_profiles.fixture]
max_tool_iterations = 1
[memory]
backend = "sqlite"
auto_save = true
embedding_provider = "none"
hygiene_enabled = false
response_cache_enabled = false
consolidation_extract_facts = false
[gateway]
host = "127.0.0.1"
port = 0
require_pairing = true
allow_public_bind = false
[hooks]
enabled = false
[reliability]
provider_retries = 0
'''


class GuardFailure(RuntimeError):
    pass


def need(ok, name):
    if not ok:
        raise GuardFailure(name)


def emit(**fields):
    print(json.dumps(dict(timestamp=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), **fields)), flush=True)


def digest(path):
    h = hashlib.sha256()
    with open(path, 'rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def startup(text):
    # Exact source banner and instruction, no guessed pairing-code length.
    bind = re.search(r'ZeroClaw Gateway listening on http://127\.0\.0\.1:(\d+)', text)
    code = re.search(r'Send: POST /pair with header X-Pairing-Code: ([^\s]+)', text)
    if bind and code:
        port = int(bind.group(1))
        need(0 < port < 65536, 'invalid_startup_port')
        return port, code.group(1)
    return None


def events(raw):
    out = []
    for frame in raw.replace('\r\n', '\n').split('\n\n'):
        name, data = '', []
        for line in frame.splitlines():
            if line.startswith('event:'):
                name = line[6:].lstrip(' ')
            elif line.startswith('data:'):
                data.append(line[5:].lstrip(' '))
        if name:
            out.append((name, json.loads('\n'.join(data))))
    need(bool(out) and out[-1] == ('done', {}), 'sse_missing_terminal_done')
    need(sum(name == 'done' for name, _ in out) == 1, 'sse_duplicate_done')
    need(all(name in ('token', 'done') for name, _ in out), 'sse_error_or_unknown_event')
    need(any(name == 'token' and item.get('text') == 'FIXTURE_OK' for name, item in out), 'sse_fixture_response_missing')
    return len(out)


# No proxy, redirect, cookie jar, or inherited HTTP credentials.
class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())


def request(port, path, headers, body):
    req = urllib.request.Request('http://127.0.0.1:%d%s' % (port, path),
                                 data=json.dumps(body).encode(), headers=headers, method='POST')
    # Socket timeouts alone are idle deadlines, not a whole-request cap.
    remaining = signal.alarm(30)
    started = time.monotonic()
    try:
        with OPENER.open(req, timeout=30) as response:
            need(response.status == 200, 'http_status')
            raw = response.read(1024 * 1024 + 1)
            need(len(raw) <= 1024 * 1024, 'http_response_size')
            return response.headers.get_content_type(), raw.decode()
    finally:
        signal.alarm(max(1, remaining - int(time.monotonic() - started)))


class Fixture(http.server.BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_POST(self):
        try:
            self.connection.settimeout(30)
            need(self.path == '/v1/chat/completions', 'provider_route')
            size = int(self.headers.get('Content-Length', '0'))
            need(0 < size <= 1024 * 1024, 'provider_request_size')
            body = json.loads(self.rfile.read(size))
            need(body.get('model') == 'fixture-model' and body.get('stream') is True, 'provider_model_stream')
            need(not body.get('tools') and not body.get('functions'), 'provider_tools_present')
            messages = body.get('messages', [])
            need(not any(m.get('tool_calls') or m.get('role') == 'tool' for m in messages), 'provider_tool_history')
            user = [m.get('content') for m in messages if m.get('role') == 'user']
            index = len(self.server.requests)
            # agent.rs::enrich_user_message prefixes the provider-facing input;
            # SQLite stores the exact raw message before that enrichment.
            need(index < 2 and user and isinstance(user[-1], str), 'provider_user_message')
            need('[CURRENT DATE & TIME: ' in user[-1] and
                 user[-1].endswith(']\n\n' + MESSAGES[index]), 'provider_user_envelope')
            self.server.requests.append(body)  # private, synthetic wire evidence
            chunks = [
                {'id': 'fixture', 'object': 'chat.completion.chunk', 'model': 'fixture-model',
                 'choices': [{'index': 0, 'delta': {'role': 'assistant', 'content': 'FIXTURE_OK'}, 'finish_reason': None}]},
                {'id': 'fixture', 'object': 'chat.completion.chunk', 'model': 'fixture-model',
                 'choices': [{'index': 0, 'delta': {}, 'finish_reason': 'stop'}]},
            ]
            payload = ''.join('data: ' + json.dumps(c) + '\n\n' for c in chunks) + 'data: [DONE]\n\n'
            encoded = payload.encode()
            self.send_response(200)
            self.send_header('Content-Type', 'text/event-stream')
            self.send_header('Content-Length', str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)
        except Exception:
            self.server.errors.append('provider_contract_failure')
            self.send_error(400, 'fixture contract failure')


def rows(db):
    with sqlite3.connect(db.as_uri() + '?mode=ro', uri=True, timeout=5) as connection:
        aliases = connection.execute("SELECT id FROM agents WHERE alias='autosaveprobe'").fetchall()
        need(len(aliases) == 1 and aliases[0][0], 'alias_identity')
        found = connection.execute(SQL).fetchall()
    return aliases[0][0], found


def check_rows(case, turn, agent_id, found):
    expected = MESSAGES[:turn] if case == 'fixed' else [MESSAGES[turn - 1]]
    need(sorted(r[1] for r in found) == sorted(expected), 'retention_content_mismatch')
    need(len(found) == len(expected), 'retention_count_mismatch')
    for key, content, category, session, namespace, owner, principal in found:
        need((category, session, namespace, owner, principal) ==
             ('conversation', 'autosave-same', 'default', agent_id, None), 'memory_scope_mismatch')
        if case == 'baseline':
            need(key == 'user_msg', 'baseline_key_mismatch')
        else:
            need(key.startswith('user_msg_'), 'fixed_key_prefix')
            parsed = uuid.UUID(key[len('user_msg_'):])
            need(parsed.version == 4 and str(parsed) == key[len('user_msg_'):], 'fixed_key_uuid')
    need(len({r[0] for r in found}) == len(found), 'duplicate_keys')


def group_alive(pid):
    try:
        os.killpg(pid, 0)
        return True
    except ProcessLookupError:
        return False


def cleanup_process(proc):
    if proc is None:
        return
    if group_alive(proc.pid):
        os.killpg(proc.pid, signal.SIGTERM)
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        pass
    if group_alive(proc.pid):
        os.killpg(proc.pid, signal.SIGKILL)
    proc.wait(timeout=5)
    deadline = time.monotonic() + 3
    while group_alive(proc.pid) and time.monotonic() < deadline:
        time.sleep(0.05)
    need(not group_alive(proc.pid), 'owned_process_group_survived')


def run(case, binary):
    binary = binary.resolve(strict=True)
    original_hash = digest(binary)
    emit(case=case, component='binary', path=str(binary), sha256=original_hash)
    proc = server = thread = None
    stage = 'setup'
    root_path = None
    try:
        with tempfile.TemporaryDirectory(prefix='autosave-12002-') as root:
            root_path = Path(root)
            home, config = root_path / 'home', root_path / 'config'
            home.mkdir(); config.mkdir()
            for name in ('config', 'data', 'cache'):
                (home / name).mkdir()
            server = http.server.HTTPServer(('127.0.0.1', 0), Fixture)
            server.requests, server.errors = [], []
            thread = threading.Thread(target=server.serve_forever, kwargs={'poll_interval': 0.1}, daemon=True)
            thread.start()
            (config / 'config.toml').write_text(CONFIG.replace('PROVIDER_PORT', str(server.server_port)))
            env = {'HOME': str(home), 'XDG_CONFIG_HOME': str(home / 'config'),
                   'XDG_DATA_HOME': str(home / 'data'), 'XDG_CACHE_HOME': str(home / 'cache'),
                   'PATH': '/usr/bin:/bin'}
            private_log = root_path / 'startup.log'
            try:
                stage = 'gateway_startup'
                with private_log.open('wb') as log:
                    proc = subprocess.Popen([str(binary), '--config-dir', str(config), 'gateway', 'start',
                                             '--host', '127.0.0.1', '--port', '0'],
                                            env=env, cwd=root, stdout=log, stderr=subprocess.STDOUT,
                                            stdin=subprocess.DEVNULL, start_new_session=True)
                deadline = time.monotonic() + 60
                pair = None
                while time.monotonic() < deadline:
                    need(proc.poll() is None, 'gateway_exited_before_ready')
                    startup_text = private_log.read_text(errors='replace')
                    need('is malformed and was reset to' not in startup_text and
                         'Pairing: DISABLED' not in startup_text, 'degraded_config_or_pairing')
                    pair = startup(startup_text)
                    if pair:
                        break
                    time.sleep(0.1)
                need(pair is not None, 'gateway_ready_timeout')
                stage = 'pairing'
                port, code = pair
                media, raw = request(port, '/pair', {'X-Pairing-Code': code, 'Content-Type': 'application/json'}, {})
                paired = json.loads(raw)
                need(media == 'application/json' and paired.get('paired') is True and
                     paired.get('persisted') is True and isinstance(paired.get('token'), str) and paired['token'], 'pairing_failed')
                token = paired['token']
                emit(case=case, component='pairing', status='passed')
                stable_id = None
                for turn, message in enumerate(MESSAGES, 1):
                    stage = 'webhook_turn_%d' % turn
                    media, raw = request(port, '/webhook?agent=autosaveprobe',
                                         {'Authorization': 'Bearer ' + token, 'Accept': 'text/event-stream',
                                          'Content-Type': 'application/json', 'X-Session-Id': 'autosave-same'},
                                         {'message': message, 'stream': True})
                    need(media == 'text/event-stream', 'webhook_not_sse')
                    count = events(raw)
                    need(len(server.requests) == turn and not server.errors, 'provider_request_evidence')
                    stage = 'sqlite_turn_%d' % turn
                    agent_id, found = rows(config / 'data' / 'memory' / 'brain.db')
                    need(stable_id in (None, agent_id), 'agent_identity_changed')
                    stable_id = agent_id
                    check_rows(case, turn, agent_id, found)
                    emit(case=case, component='turn', turn=turn, sse='done', event_count=count,
                         provider_requests=len(server.requests), rows=found)
                need('is malformed and was reset to' not in private_log.read_text(errors='replace'), 'degraded_runtime_config')
                stage = 'complete'
                emit(case=case, status='baseline_overwrite_reproduced' if case == 'baseline' else 'fixed_retention_passed')
            finally:
                cleanup_process(proc)
                proc = None
                server.shutdown(); server.server_close(); thread.join(timeout=5)
                need(not thread.is_alive(), 'fixture_thread_survived')
                server = thread = None
    except Exception as exc:
        # Only our constant guard identifiers are safe; never raw exceptions/logs.
        emit(case=case, component=stage, status='failed', error_type=type(exc).__name__,
             guard=str(exc) if isinstance(exc, GuardFailure) else 'private_diagnostic_withheld')
        raise RuntimeError('acceptance_failed') from None
    finally:
        cleanup_process(proc)
        if server:
            server.shutdown(); server.server_close()
        if thread:
            thread.join(timeout=5)
            need(not thread.is_alive(), 'fixture_thread_survived')
        need(root_path is None or not root_path.exists(), 'private_state_survived')
        need(digest(binary) == original_hash, 'binary_changed')
        emit(case=case, component='cleanup', owned_processes_remaining=0, private_state_removed=True,
             binary_hash_unchanged=True)


def self_test():
    need('require_pairing = true' in CONFIG and 'deny_all_tools = true' in CONFIG, 'config_guards')
    # Ubuntu 24.04 has stdlib tomllib; local Python 3.9 guard checks do not.
    try:
        import tomllib
    except ImportError:
        emit(component='toml_parser', status='UNRUN_python_requires_3_11')
    else:
        tomllib.loads(CONFIG.replace('PROVIDER_PORT', '12345'))
    need(startup('ZeroClaw Gateway listening on http://127.0.0.1:12345\nSend: POST /pair with header X-Pairing-Code: abc-def') == (12345, 'abc-def'), 'startup_parser')
    need(startup('ZeroClaw Gateway listening on http://0.0.0.0:12345') is None, 'public_bind_guard')
    events('event: token\ndata: {"text":"FIXTURE_OK"}\n\nevent: done\ndata: {}\n\n')
    for bad in ('event: done\ndata: {}\n\n', 'event: error\ndata: {}\n\n',
                'event: token\ndata: {"text":"FIXTURE_OK"}\n\n'):
        try:
            events(bad)
        except RuntimeError:
            pass
        else:
            raise RuntimeError('sse_negative_guard')
    owner = str(uuid.uuid4())
    def row(key, text):
        return (key, text, 'conversation', 'autosave-same', 'default', owner, None)
    check_rows('baseline', 1, owner, [row('user_msg', MESSAGES[0])])
    check_rows('baseline', 2, owner, [row('user_msg', MESSAGES[1])])
    fixed = [row('user_msg_' + str(uuid.uuid4()), m) for m in MESSAGES]
    check_rows('fixed', 2, owner, fixed)
    for case, value in [('fixed', [row('user_msg', MESSAGES[1])]), ('baseline', fixed)]:
        try:
            check_rows(case, 2, owner, value)
        except RuntimeError:
            pass
        else:
            raise RuntimeError('retention_negative_guard')
    # SQL mock proves webhook rows cannot manufacture a retention pass.
    with tempfile.TemporaryDirectory() as root:
        db = Path(root) / 'brain.db'
        with sqlite3.connect(db) as connection:
            connection.executescript('CREATE TABLE agents(id TEXT, alias TEXT); CREATE TABLE memories(key TEXT, content TEXT, category TEXT, session_id TEXT, namespace TEXT, agent_id TEXT, principal_id TEXT, created_at TEXT);')
            connection.execute('INSERT INTO agents VALUES (?,?)', (owner, 'autosaveprobe'))
            connection.executemany('INSERT INTO memories VALUES (?,?,?,?,?,?,?,?)',
                                   [row('user_msg', MESSAGES[1]) + ('now',),
                                    row('webhook_1', MESSAGES[0]) + ('now',)])
        alias, found = rows(db)
        check_rows('baseline', 2, alias, found)
        need(len(found) == 1, 'webhook_exclusion')
    # Wire fixture check is mock-only and exercises no real application.
    server = http.server.HTTPServer(('127.0.0.1', 0), Fixture)
    server.requests, server.errors = [], []
    thread = threading.Thread(target=server.serve_forever, kwargs={'poll_interval': 0.1})
    thread.start()
    try:
        for message in MESSAGES:
            media, payload = request(server.server_port, '/v1/chat/completions',
                                     {'Content-Type': 'application/json'},
                                     {'model': 'fixture-model', 'stream': True, 'messages':
                                      [{'role': 'user', 'content': '[CURRENT DATE & TIME: synthetic]\n\n' + message}]})
            need(media == 'text/event-stream' and payload.endswith('data: [DONE]\n\n'), 'mock_provider_wire')
        need(len(server.requests) == 2 and not server.errors, 'mock_wire_evidence')
    finally:
        server.shutdown(); server.server_close(); thread.join(timeout=5)
        need(not thread.is_alive(), 'mock_server_cleanup')
    proc = subprocess.Popen(['/usr/bin/sleep', '30'], start_new_session=True)
    cleanup_process(proc)
    emit(status='mock_guard_checks_passed', application_acceptance='UNRUN')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--case', choices=('baseline', 'fixed'))
    parser.add_argument('--binary', type=Path)
    parser.add_argument('--self-test', action='store_true')
    args = parser.parse_args()
    def interrupted(signum, frame):
        raise RuntimeError('interrupted')
    signal.signal(signal.SIGTERM, interrupted)
    signal.signal(signal.SIGINT, interrupted)
    signal.signal(signal.SIGALRM, interrupted)
    signal.alarm(180)
    try:
        if args.self_test:
            self_test()
        else:
            need(args.case and args.binary, 'missing_case_or_binary')
            run(args.case, args.binary)
    except Exception:
        emit(status='failed', detail='sanitized_failure_no_private_logs')
        raise SystemExit(1)
    finally:
        signal.alarm(0)
