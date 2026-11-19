from pathlib import Path
import subprocess as sp
import hashlib
import os
import sys

BASE = 'dfc70a2b499a5e5ad777a9174a216a29fda7aa35'
TARGET = 'e7543ac01e7326477217fc00e86cc8084ec1dfcc'
PATCH = '3309cfa6b178faa328a27e7ab43992a1f0813cb4eaecdd434756a1e9403068c9'
MANIFEST = 'c06e67178d5ff326c3f2020c8edb40a263476857fd503ee1245663e282b53895'
LOCK = '364aa9fad68e8e7272cb1e81b0f334a2be6c3d98bf0dc237a52b1c83648522f0'
HERE = Path(__file__).resolve().parent

def require(ok, msg):
    if not ok:
        raise SystemExit(msg)

def git(*args):
    return sp.check_output(['git', *args])

def digest(data):
    return hashlib.sha256(data).hexdigest()

def attest(initial):
    def manifest(name, expected):
        data = (HERE / name).read_bytes()
        require(digest(data) == expected, 'frozen manifest drift: '+name)
        return {p:h for h,p in (s.split('  ') for s in data.decode().splitlines())}
    paths = manifest('files.sha256', MANIFEST)
    checkout = manifest('checkout.sha256', 'f1062f69c528b1600d7c19b17e757e517bb687e98398e0ed29243be7fc3a27c0')
    require(len(paths)==33 and paths.keys()==checkout.keys(), 'manifest set drift')
    require(digest(git('diff','--binary','--full-index', BASE, TARGET)) == PATCH, 'combined patch drift')
    require(git('remote','get-url','origin').decode().strip().removesuffix('.git') == 'https://github.com/ggettert/zeroclaw','source origin drift')
    require(git('rev-parse',TARGET+'^^2').decode().strip() == BASE, 'candidate merge base drift')
    require(set(git('diff','--name-only',BASE,TARGET).decode().splitlines()) == set(paths), 'candidate path set drift')
    for p,h in paths.items():
        require(git('ls-tree',TARGET,'--',p).startswith(b'100644 blob ') and digest(git('show',TARGET+':'+p)) == h, 'candidate Git mode/blob drift: '+p)
    require(git('rev-parse','HEAD').decode().strip()==TARGET, 'execution commit drift')
    require(not git('status','--porcelain','--untracked-files=all'), 'unclean source')
    require(digest(git('show',TARGET+':Cargo.lock'))==LOCK, 'lock blob drift')
    phase = 'before' if initial else 'after'
    for p,h in [*checkout.items(), ('Cargo.lock', LOCK)]:
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
