#!/usr/bin/env python3
"""Noncompiling pinned-source verification; execute from job workspace root."""
import hashlib
import json
from pathlib import Path
import subprocess

manifest = json.loads((Path(__file__).parent / '12002_source_manifest.json').read_text())
for case, expected in manifest.items():
    root = Path(case)
    def git(*args):
        return subprocess.check_output(['git', '-C', str(root), *args], text=True).strip()
    assert git('rev-parse', 'HEAD') == expected['sha'], case + ': source SHA drift'
    assert git('write-tree') == git('rev-parse', 'HEAD^{tree}'), case + ': index tree drift'
    print(json.dumps({'case': case, 'tree': git('rev-parse', 'HEAD^{tree}')}))
    assert not git('status', '--porcelain', '--untracked-files=all'), case + ': dirty source'
    # Clean sources intentionally omit generated web assets; gateway build.rs
    # returns before npm, and default features do not enable embedded-web.
    assert not (root / 'web/src/lib/api-generated.ts').exists(), 'unexpected npm build trigger'
    for name, wanted in expected['files'].items():
        actual = hashlib.sha256((root / name).read_bytes()).hexdigest()
        assert actual == wanted, case + ': file drift: ' + name
        print(json.dumps({'case': case, 'source_sha': expected['sha'], 'file': name, 'sha256': actual}))
