import subprocess,hashlib,json,pathlib,sys,stat,os
root=pathlib.Path.cwd()
def git(*a):return subprocess.check_output(['git',*a],text=True).strip()
assert git('rev-parse','HEAD')=='a1780d236088e782caaebc0a84dd4c9f19c04d2d','HEAD drift'
assert git('write-tree')==git('rev-parse','HEAD^{tree}'),'index drift'
assert not git('diff','--name-only','HEAD'),'tracked source drift'
untracked = git('ls-files','--others','--exclude-standard').splitlines()
for name in untracked:
    assert name == 'web/dist/.gitkeep' or (name == 'golden-frames.log' and os.environ.get('ALLOW_UPSTREAM_GOLDEN_LOG') == '1'), 'unexpected untracked source: ' + name
    path = root / name
    assert stat.S_ISREG(path.lstat().st_mode) and not path.is_symlink(), 'placeholder type drift'
    if name == 'web/dist/.gitkeep':
        assert path.read_bytes() == b'', 'placeholder content drift'
    else:
        assert path.stat().st_size <= 20 * 1024 * 1024, 'golden log exceeds bound'
        assert bytes([0]) not in path.read_bytes(), 'golden log is not text'

    assert all(not parent.is_symlink() for parent in [root/'web', root/'web/dist']), 'placeholder parent symlink'

manifest=json.loads(pathlib.Path(__file__).with_suffix('.json').read_text())
for p,v in manifest.items():assert hashlib.sha256((root/p).read_bytes()).hexdigest()==v,p
print('SOURCE_VERIFIED '+git('rev-parse','HEAD')+' tree='+git('rev-parse','HEAD^{tree}')+' '+sys.argv[1])
