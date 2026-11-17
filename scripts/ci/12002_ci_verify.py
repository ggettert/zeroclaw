import subprocess,hashlib,json,pathlib,sys
root=pathlib.Path.cwd()
def git(*a):return subprocess.check_output(['git',*a],text=True).strip()
assert git('rev-parse','HEAD')=='a1780d236088e782caaebc0a84dd4c9f19c04d2d','HEAD drift'
assert git('write-tree')==git('rev-parse','HEAD^{tree}'),'index drift'
assert not git('diff','--name-only','HEAD'),'tracked source drift'
assert not git('ls-files','--others','--exclude-standard'),'untracked source drift'
manifest=json.loads(pathlib.Path(__file__).with_suffix('.json').read_text())
for p,v in manifest.items():assert hashlib.sha256((root/p).read_bytes()).hexdigest()==v,p
print('SOURCE_VERIFIED '+git('rev-parse','HEAD')+' tree='+git('rev-parse','HEAD^{tree}')+' '+sys.argv[1])
