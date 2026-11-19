from pathlib import Path
import subprocess as sp
import hashlib
import os
import sys

BASE = 'f1f577c85348acce58a7d98b7462394043757a4d'
TARGET = '42247c1b771196c9dc66ab32ce879241e317d888'
PATCH = 'ccae5adcbd34d18cc2525846672911a760fe4f4c5434665951f4b0733aa700fe'
MANIFEST = 'dfbfa70f7caefff7b4dd35cf85826bf6dc8fc783e1fdc8aa8accc6e38816fe2d'
LOCK = '6fc8a5e9de0fd29a3cff892f17cb7d377728ebfc05522248eb2750c01bd54119'
HERE = Path(__file__).resolve().parent

def require(ok, msg):
    if not ok:
        raise SystemExit(msg)

def git(*args):
    return sp.check_output(['git', *args])

def digest(data):
    return hashlib.sha256(data).hexdigest()

def attest(initial):
    patch = HERE / 'candidate.patch'
    manifest = HERE / 'files.sha256'
    require(digest(patch.read_bytes()) == PATCH and digest(manifest.read_bytes()) == MANIFEST,'frozen input drift')
    paths = {p:h for h,p in (s.split('  ') for s in manifest.read_text().splitlines())}
    require(len(paths) == 20, 'manifest path count')
    require(git('remote','get-url','origin').decode().strip().removesuffix('.git') == 'https://github.com/ggettert/zeroclaw','source origin drift')
    require(git('rev-parse',TARGET+'^').decode().strip() == BASE, 'candidate parent drift')
    require(set(git('diff','--name-only',BASE,TARGET).decode().splitlines()) == set(paths), 'candidate path set drift')
    for p,h in paths.items():
        require(git('ls-tree',TARGET,'--',p).startswith(b'100644 blob ') and digest(git('show',TARGET+':'+p)) == h, 'candidate Git mode/blob drift: '+p)
    if initial:
        require(not git('status','--porcelain') and git('rev-parse','HEAD').decode().strip()==TARGET, 'unclean initial target')
        git('checkout','--detach',BASE)
        require(not git('status','--porcelain'), 'unclean base')
        git('apply','--check',str(patch))
        git('apply',str(patch))
    require(git('rev-parse','HEAD').decode().strip()==BASE, 'execution base drift')
    git('diff','--exit-code','--cached',BASE)
    git('diff','--exit-code',TARGET,'--')
    require(not git('ls-files','--others','--exclude-standard'), 'unexpected untracked source')
    phase = 'before' if initial else 'after'
    for p,h in [*paths.items(), ('Cargo.lock', LOCK)]:
        data = Path(p).read_bytes()
        actual = digest(data)
        print(f'BYTES {phase} {p} sha256={actual} size={len(data)}', flush=True)
        if actual != h:
            blob = git('show', TARGET+':'+p)
            first = next((i for i,(a,b) in enumerate(zip(blob,data)) if a!=b), min(len(blob),len(data)))
            crlf = b'\r\n'
            print(git('ls-files','--eol','--',p).decode().strip(), flush=True)
            raise SystemExit(f'executed bytes drift: {p} expected_sha256={h} expected_size={len(blob)} '
                             f'first_offset={first} expected_crlf={blob.count(crlf)} actual_crlf={data.count(crlf)}')
    print(f'ATTEST base={BASE} candidate={TARGET} patch={PATCH} paths={len(paths)} workflow={os.environ["WORKFLOW_SHA"]}',flush=True)

if __name__ == '__main__':
    require(sys.argv[1] in ('before','after'), 'invalid phase')
    attest(sys.argv[1]=='before')
